from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.config.loader import load_json, resolve_config_path
from capital_algo.data.sqlite_cache import SQLiteMarketDataCache
from capital_algo.models import Candle, Signal, OrderType, TradeAction
from capital_algo.reporting.reports import metrics_from_trades, write_backtest_report
from capital_algo.risk.manager import RiskManager
from capital_algo.strategies.forex_pullback import ForexPullbackContext, ForexTrendPullbackScalper, TradeDirection


@dataclass(frozen=True)
class ForexPullbackBacktestResult:
    report_directory: Path
    summary_path: Path
    rows: list[dict[str, Any]]


def run_cached_forex_pullback_backtest(
    root: Path,
    symbols: list[str] | None = None,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    strategy_config_path: str = "config/strategies/forex_pullback_scalper.json",
    allow_missing_spread: bool = True,
    disable_news_filter: bool = True,
    trailing_stop: dict[str, Any] | None = None,
    report_name: str | None = None,
) -> ForexPullbackBacktestResult:
    root = root.resolve()
    app_config = load_json(root / "config" / "app.json")
    data_config = load_json(resolve_config_path(root, app_config.get("data_config", "config/data/cache.json")))
    backtest_config = load_json(resolve_config_path(root, app_config.get("backtest_config", "config/backtest.json")))
    risk_config = load_json(root / "config" / "risk.json")
    strategy_config = load_json(resolve_config_path(root, strategy_config_path))

    if trailing_stop is not None:
        backtest_config["trailing_stop"] = trailing_stop

    cache_path = resolve_config_path(root, data_config["historical_store"]["path"])
    cache = SQLiteMarketDataCache(cache_path)
    cache.initialize()

    provider = data_config.get("fallback_data_provider", "capital")
    symbols = symbols or _cached_forex_symbols(cache_path, provider)
    if not symbols:
        raise RuntimeError("No cached forex symbols found")

    strategy_config = _prepare_strategy_config(strategy_config, symbols, allow_missing_spread, disable_news_filter)

    if start_utc is None or end_utc is None:
        cache_start, cache_end = _cache_bounds(cache_path, provider, symbols)
        start_utc = start_utc or cache_start
        end_utc = end_utc or cache_end

    generated = datetime.now(timezone.utc)
    report_root = resolve_config_path(root, backtest_config.get("report_directory", "reports"))
    run_name = report_name or f"forex_pullback_pnl_{start_utc:%Y%m%d}_{end_utc:%Y%m%d}"
    run_directory = report_root / run_name
    individual_directory = run_directory / "individual_runs"
    individual_directory.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        candles_1m = cache.get_candles(provider, symbol, "MINUTE", start_utc, end_utc)
        if not candles_1m:
            rows.append(_empty_row(symbol, "no_cached_candles"))
            continue
        symbol_result = _run_symbol_backtest(
            symbol=symbol,
            candles_1m=candles_1m,
            strategy_config=strategy_config,
            backtest_config=backtest_config,
            risk_config=risk_config,
            output_directory=individual_directory,
            config_snapshot={
                "strategy": strategy_config,
                "backtest": backtest_config,
                "risk": risk_config,
                "data": {
                    "provider": provider,
                    "source": str(cache_path),
                    "timeframe": "MINUTE",
                    "start_utc": _format_utc(start_utc),
                    "end_utc": _format_utc(end_utc),
                    "derived_timeframes": ["MINUTE_5", "MINUTE_15"],
                },
            },
        )
        rows.append(symbol_result)

    summary = _aggregate_summary(rows, generated, start_utc, end_utc, symbols, strategy_config, backtest_config, risk_config)
    run_directory.mkdir(parents=True, exist_ok=True)
    summary_path = run_directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_summary_csv(run_directory / "summary.csv", rows)
    return ForexPullbackBacktestResult(run_directory, summary_path, rows)


def _run_symbol_backtest(
    symbol: str,
    candles_1m: list[Candle],
    strategy_config: dict[str, Any],
    backtest_config: dict[str, Any],
    risk_config: dict[str, Any],
    output_directory: Path,
    config_snapshot: dict[str, Any],
) -> dict[str, Any]:
    candles_5m = _aggregate(candles_1m, 5, "MINUTE_5")
    candles_15m = _aggregate(candles_1m, 15, "MINUTE_15")
    if not candles_5m or not candles_15m:
        return _empty_row(symbol, "insufficient_derived_timeframes")

    end_5 = [candle.timestamp_utc.timestamp() + (4 * 60) for candle in candles_5m]
    end_15 = [candle.timestamp_utc.timestamp() + (14 * 60) for candle in candles_15m]
    engine = ForexTrendPullbackScalper(strategy_config)
    symbol_risk_config = dict(risk_config)
    fixed_sizes = strategy_config.get("fixed_position_sizes", {})
    if symbol in fixed_sizes:
        symbol_risk_config["position_sizing_mode"] = "fixed"
        symbol_risk_config["fixed_position_size"] = fixed_sizes[symbol]
    broker = SimulatedBroker(
        starting_balance=float(backtest_config["starting_balance"]),
        currency=backtest_config.get("account_currency", "USD"),
        execution_config=backtest_config,
    )
    risk_manager = RiskManager(symbol_risk_config)
    rejected_signals: list[dict[str, Any]] = []
    rejected_evaluations = 0
    generated_signals = 0
    evaluated = 0

    min_1m = 80
    min_5m = 80
    min_15m = 80
    for index, candle in enumerate(candles_1m):
        timestamp = candle.timestamp_utc.isoformat()
        broker.update_for_bar(symbol, candle.high, candle.low, candle.close, timestamp)
        five_index = _rightmost_completed_index(end_5, candle.timestamp_utc.timestamp())
        fifteen_index = _rightmost_completed_index(end_15, candle.timestamp_utc.timestamp())
        if index + 1 < min_1m or five_index + 1 < min_5m or fifteen_index + 1 < min_15m:
            continue

        context = ForexPullbackContext(
            symbol=symbol,
            current_time=candle.timestamp_utc,
            candles_1m=candles_1m[max(0, index + 1 - min_1m) : index + 1],
            candles_5m=candles_5m[max(0, five_index + 1 - min_5m) : five_index + 1],
            candles_15m=candles_15m[max(0, fifteen_index + 1 - min_15m) : fifteen_index + 1],
            current_spread=None,
            config={},
            news_events=[],
        )
        evaluation = engine.evaluate(context)
        evaluated += 1
        if not evaluation.should_trade:
            rejected_evaluations += 1
            continue

        generated_signals += 1
        signal = _evaluation_to_signal(evaluation)
        decision = risk_manager.evaluate(
            signal,
            broker.get_account_snapshot(),
            evaluation.entry_price or candle.close,
            trading_day=candle.timestamp_utc.date().isoformat(),
        )
        if not decision.approved or decision.order is None:
            rejected_signals.append(
                {
                    "timestamp": timestamp,
                    "instrument": symbol,
                    "reason": decision.reason,
                    "signal_reason": signal.reason,
                }
            )
            continue
        broker.submit_order_at_price(decision.order, evaluation.entry_price or candle.close, timestamp)
        risk_manager.record_trade()

    if candles_1m:
        broker.close_all({symbol: candles_1m[-1].close}, candles_1m[-1].timestamp_utc.isoformat(), "end_of_backtest")

    metrics = metrics_from_trades(float(backtest_config["starting_balance"]), broker.balance, broker.closed_trades)
    metrics["evaluated_bars"] = evaluated
    metrics["generated_signals"] = generated_signals
    metrics["rejected_evaluations"] = rejected_evaluations
    metrics["risk_rejected_signals"] = len(rejected_signals)
    run_name = f"{symbol}_MINUTE_{candles_1m[0].timestamp_utc:%Y%m%dT%H%M%S}_{candles_1m[-1].timestamp_utc:%Y%m%dT%H%M%S}"
    report_dir = write_backtest_report(output_directory, run_name, config_snapshot, metrics, broker.closed_trades, rejected_signals)
    return {
        "symbol": symbol,
        "status": "ok",
        "report_directory": str(report_dir),
        **metrics,
    }


def _evaluation_to_signal(evaluation) -> Signal:
    action = TradeAction.BUY if evaluation.direction == TradeDirection.LONG else TradeAction.SELL
    return Signal(
        strategy_id="forex_pullback_scalper",
        instrument=evaluation.symbol,
        action=action,
        entry_type=OrderType.MARKET,
        reason=evaluation.reason or "FOREX_PULLBACK_SIGNAL",
        stop_loss=evaluation.stop_loss,
        take_profit=evaluation.target_price,
        metadata=evaluation.metadata,
    )


def _prepare_strategy_config(
    config: dict[str, Any],
    symbols: list[str],
    allow_missing_spread: bool,
    disable_news_filter: bool,
) -> dict[str, Any]:
    prepared = json.loads(json.dumps(config))
    prepared["symbols"] = symbols
    prepared.setdefault("filters", {})["allow_missing_spread"] = allow_missing_spread
    prepared.setdefault("news_blackout", {})["enabled"] = not disable_news_filter
    _ensure_symbol_map(prepared, "pip_size", symbols, lambda symbol: 0.01 if symbol.endswith("JPY") else 0.0001)
    _ensure_symbol_map(prepared, "max_spread", symbols, lambda symbol: 999.0)
    _ensure_symbol_map(prepared, "min_impulse_pips", symbols, lambda symbol: 6.0 if symbol.endswith("JPY") else 5.0)
    _ensure_symbol_map(prepared, "pullback_buffer_pips", symbols, lambda symbol: 2.0 if symbol.endswith("JPY") else 1.5)
    _ensure_symbol_map(prepared, "stop_buffer_pips", symbols, lambda symbol: 1.5 if symbol.endswith("JPY") else 1.0)
    return prepared


def _ensure_symbol_map(config: dict[str, Any], key: str, symbols: list[str], default_factory) -> None:
    values = config.setdefault(key, {})
    for symbol in symbols:
        values.setdefault(symbol, default_factory(symbol))


def _aggregate(candles: list[Candle], minutes: int, timeframe: str) -> list[Candle]:
    result: list[Candle] = []
    bucket: list[Candle] = []
    current = None
    for candle in candles:
        bucket_start = candle.timestamp_utc.replace(
            minute=(candle.timestamp_utc.minute // minutes) * minutes,
            second=0,
            microsecond=0,
        )
        if current is None:
            current = bucket_start
        if bucket_start != current:
            if len(bucket) == minutes:
                result.append(_aggregate_bucket(bucket, timeframe, current))
            bucket = []
            current = bucket_start
        bucket.append(candle)
    if len(bucket) == minutes and current is not None:
        result.append(_aggregate_bucket(bucket, timeframe, current))
    return result


def _aggregate_bucket(bucket: list[Candle], timeframe: str, timestamp: datetime) -> Candle:
    return Candle(
        provider=bucket[0].provider,
        instrument=bucket[0].instrument,
        timeframe=timeframe,
        timestamp_utc=timestamp,
        open=bucket[0].open,
        high=max(candle.high for candle in bucket),
        low=min(candle.low for candle in bucket),
        close=bucket[-1].close,
        volume=sum(candle.volume or 1.0 for candle in bucket),
    )


def _rightmost_completed_index(completed_timestamps: list[float], timestamp: float) -> int:
    left = 0
    right = len(completed_timestamps)
    while left < right:
        middle = (left + right) // 2
        if completed_timestamps[middle] <= timestamp:
            left = middle + 1
        else:
            right = middle
    return left - 1


def _cached_forex_symbols(cache_path: Path, provider: str) -> list[str]:
    with sqlite3.connect(cache_path) as connection:
        rows = connection.execute(
            """
            SELECT instrument, COUNT(*) AS candle_count
            FROM candles
            WHERE provider = ?
              AND timeframe = 'MINUTE'
              AND length(instrument) = 6
            GROUP BY instrument
            HAVING candle_count >= 1000
            ORDER BY instrument
            """,
            (provider,),
        ).fetchall()
    return [row[0] for row in rows]


def _cache_bounds(cache_path: Path, provider: str, symbols: list[str]) -> tuple[datetime, datetime]:
    placeholders = ",".join("?" for _ in symbols)
    with sqlite3.connect(cache_path) as connection:
        row = connection.execute(
            f"""
            SELECT MIN(timestamp_utc), MAX(timestamp_utc)
            FROM candles
            WHERE provider = ?
              AND timeframe = 'MINUTE'
              AND instrument IN ({placeholders})
            """,
            [provider, *symbols],
        ).fetchone()
    if row is None or row[0] is None or row[1] is None:
        raise RuntimeError("Cached symbols have no candle bounds")
    return _parse_utc(row[0]), _parse_utc(row[1])


def _aggregate_summary(
    rows: list[dict[str, Any]],
    generated: datetime,
    start_utc: datetime,
    end_utc: datetime,
    symbols: list[str],
    strategy_config: dict[str, Any],
    backtest_config: dict[str, Any],
    risk_config: dict[str, Any],
) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    return {
        "generated_at": generated.isoformat(),
        "start_utc": _format_utc(start_utc),
        "end_utc": _format_utc(end_utc),
        "symbols": symbols,
        "totals": {
            "trade_count": sum(int(row.get("trade_count", 0)) for row in ok_rows),
            "net_profit": sum(float(row.get("net_profit", 0.0)) for row in ok_rows),
            "generated_signals": sum(int(row.get("generated_signals", 0)) for row in ok_rows),
            "risk_rejected_signals": sum(int(row.get("risk_rejected_signals", 0)) for row in ok_rows),
        },
        "rows": rows,
        "config": {
            "strategy": strategy_config,
            "backtest": backtest_config,
            "risk": risk_config,
        },
    }


def _write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "symbol",
        "status",
        "starting_balance",
        "ending_balance",
        "net_profit",
        "total_return_pct",
        "trade_count",
        "win_rate_pct",
        "profit_factor",
        "best_trade",
        "worst_trade",
        "generated_signals",
        "risk_rejected_signals",
        "report_directory",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})


def _empty_row(symbol: str, status: str) -> dict[str, Any]:
    return {"symbol": symbol, "status": status}


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
