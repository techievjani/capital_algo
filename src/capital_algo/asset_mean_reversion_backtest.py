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
from capital_algo.forex_pullback_backtest import _aggregate, _format_utc, _parse_utc
from capital_algo.models import Candle, OrderType, Signal, TradeAction
from capital_algo.reporting.reports import metrics_from_trades, write_backtest_report
from capital_algo.risk.manager import RiskManager
from capital_algo.strategies.asset_breakout import AssetBreakoutStrategy, BreakoutContext, BreakoutDirection
from capital_algo.strategies.asset_mean_reversion import (
    AssetMeanReversionStrategy,
    MeanReversionContext,
    MeanReversionDirection,
)


@dataclass(frozen=True)
class AssetMeanReversionBacktestResult:
    report_directory: Path
    summary_path: Path
    rows: list[dict[str, Any]]


def run_cached_asset_mean_reversion_backtest(
    root: Path,
    symbols: list[str] | None = None,
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    strategy_config_path: str = "config/strategies/btc_gold_mean_reversion.json",
    trailing_stop: dict[str, Any] | None = None,
    report_name: str | None = None,
) -> AssetMeanReversionBacktestResult:
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
    symbols = symbols or list(strategy_config.get("symbols", {}).keys()) or _cached_asset_symbols(cache_path, provider)
    if not symbols:
        raise RuntimeError("No cached asset symbols found")

    if start_utc is None or end_utc is None:
        cache_start, cache_end = _cache_bounds(cache_path, provider, symbols)
        start_utc = start_utc or cache_start
        end_utc = end_utc or cache_end

    generated = datetime.now(timezone.utc)
    report_root = resolve_config_path(root, backtest_config.get("report_directory", "reports"))
    run_name = report_name or f"asset_mean_reversion_{start_utc:%Y%m%d}_{end_utc:%Y%m%d}"
    run_directory = report_root / run_name
    individual_directory = run_directory / "individual_runs"
    individual_directory.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        candles_1m = cache.get_candles(provider, symbol, "MINUTE", start_utc, end_utc)
        if not candles_1m:
            rows.append(_empty_row(symbol, "no_cached_candles"))
            continue
        rows.append(
            _run_symbol_backtest(
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
                        "derived_timeframes": ["MINUTE_5"],
                        "start_utc": _format_utc(start_utc),
                        "end_utc": _format_utc(end_utc),
                    },
                },
            )
        )

    summary = _aggregate_summary(rows, generated, start_utc, end_utc, symbols, strategy_config, backtest_config, risk_config)
    run_directory.mkdir(parents=True, exist_ok=True)
    summary_path = run_directory / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_summary_csv(run_directory / "summary.csv", rows)
    return AssetMeanReversionBacktestResult(run_directory, summary_path, rows)


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
    if not candles_5m:
        return _empty_row(symbol, "insufficient_derived_timeframe")

    broker = SimulatedBroker(
        starting_balance=float(backtest_config["starting_balance"]),
        currency=backtest_config.get("account_currency", "USD"),
        execution_config=backtest_config,
    )
    rejected_signals: list[dict[str, Any]] = []
    rejected_evaluations = 0
    generated_signals = 0
    evaluated = 0
    open_entry_index: int | None = None
    symbol_config = strategy_config.get("symbols", {}).get(symbol, {})
    strategy_type = symbol_config.get("strategy_type", strategy_config.get("strategy_type", "mean_reversion"))
    max_hold_bars = int(symbol_config.get("max_hold_bars", strategy_config.get("max_hold_bars", 24)))
    history_bars = max(220, int(strategy_config.get("history_bars", 220)))
    symbol_risk_config = dict(risk_config)
    if "account_risk_per_trade_pct" in symbol_config:
        symbol_risk_config["account_risk_per_trade_pct"] = symbol_config["account_risk_per_trade_pct"]
    if "max_trades_per_day" in symbol_config:
        symbol_risk_config["max_trades_per_day"] = symbol_config["max_trades_per_day"]
    if "fixed_position_size" in symbol_config:
        symbol_risk_config["position_sizing_mode"] = "fixed"
        symbol_risk_config["fixed_position_size"] = symbol_config["fixed_position_size"]
    risk_manager = RiskManager(symbol_risk_config)
    strategy = _build_strategy(strategy_type, strategy_config)

    for index, candle in enumerate(candles_5m):
        timestamp = candle.timestamp_utc.isoformat()
        broker.update_for_bar(symbol, candle.high, candle.low, candle.close, timestamp)
        if not broker.open_trades:
            open_entry_index = None
        if broker.open_trades and open_entry_index is not None and index - open_entry_index >= max_hold_bars:
            broker.close_all({symbol: candle.close}, timestamp, "max_hold")
            open_entry_index = None

        if index + 1 < history_bars or broker.open_trades:
            continue

        evaluation = _evaluate_strategy(
            strategy_type,
            strategy,
            symbol,
            candles_5m[max(0, index + 1 - history_bars) : index + 1],
        )
        evaluated += 1
        if not evaluation.should_trade:
            rejected_evaluations += 1
            continue

        generated_signals += 1
        signal = _evaluation_to_signal(evaluation, strategy_type)
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
        open_entry_index = index
        risk_manager.record_trade()

    if candles_5m:
        broker.close_all({symbol: candles_5m[-1].close}, candles_5m[-1].timestamp_utc.isoformat(), "end_of_backtest")

    metrics = metrics_from_trades(float(backtest_config["starting_balance"]), broker.balance, broker.closed_trades)
    metrics["evaluated_bars"] = evaluated
    metrics["generated_signals"] = generated_signals
    metrics["rejected_evaluations"] = rejected_evaluations
    metrics["risk_rejected_signals"] = len(rejected_signals)
    run_name = f"{symbol}_MINUTE_5_{candles_5m[0].timestamp_utc:%Y%m%dT%H%M%S}_{candles_5m[-1].timestamp_utc:%Y%m%dT%H%M%S}"
    report_dir = write_backtest_report(output_directory, run_name, config_snapshot, metrics, broker.closed_trades, rejected_signals)
    return {
        "symbol": symbol,
        "status": "ok",
        "strategy_type": strategy_type,
        "report_directory": str(report_dir),
        **metrics,
    }


def _build_strategy(strategy_type: str, strategy_config: dict[str, Any]) -> AssetMeanReversionStrategy | AssetBreakoutStrategy:
    if strategy_type == "mean_reversion":
        return AssetMeanReversionStrategy(strategy_config)
    if strategy_type == "breakout":
        return AssetBreakoutStrategy(strategy_config)
    raise RuntimeError(f"Unsupported asset strategy_type: {strategy_type}")


def _evaluate_strategy(
    strategy_type: str,
    strategy: AssetMeanReversionStrategy | AssetBreakoutStrategy,
    symbol: str,
    candles_5m: list[Candle],
):
    if strategy_type == "mean_reversion":
        return strategy.evaluate(MeanReversionContext(symbol=symbol, candles_5m=candles_5m))
    if strategy_type == "breakout":
        return strategy.evaluate(BreakoutContext(symbol=symbol, candles_5m=candles_5m))
    raise RuntimeError(f"Unsupported asset strategy_type: {strategy_type}")


def _evaluation_to_signal(evaluation, strategy_type: str) -> Signal:
    direction = evaluation.direction
    is_long = direction in {MeanReversionDirection.LONG, BreakoutDirection.LONG}
    action = TradeAction.BUY if is_long else TradeAction.SELL
    return Signal(
        strategy_id=f"asset_{strategy_type}_v1",
        instrument=evaluation.symbol,
        action=action,
        entry_type=OrderType.MARKET,
        reason=evaluation.reason or "ASSET_SIGNAL",
        stop_loss=evaluation.stop_loss,
        take_profit=evaluation.target_price,
        metadata=evaluation.metadata,
    )


def _cached_asset_symbols(cache_path: Path, provider: str) -> list[str]:
    with sqlite3.connect(cache_path) as connection:
        rows = connection.execute(
            """
            SELECT instrument, COUNT(*) AS candle_count
            FROM candles
            WHERE provider = ?
              AND timeframe = 'MINUTE'
              AND instrument IN ('BTCUSD', 'GOLD')
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
        "strategy_type",
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
