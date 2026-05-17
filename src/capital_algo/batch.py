from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from capital_algo.backtest import BacktestEngine
from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.config.loader import load_json, resolve_config_path
from capital_algo.data.resolver import HistoricalDataResolver
from capital_algo.models import Candle
from capital_algo.reporting.reports import metrics_from_trades
from capital_algo.risk.manager import RiskManager
from capital_algo.sessions import TradingSession, load_sessions
from capital_algo.strategies.orb import ORBStrategy


@dataclass(frozen=True)
class BatchComboResult:
    symbol: str
    session: str
    target_r: float
    stop_loss_mode: str
    report_directory: str
    metrics: dict[str, Any]
    trade_count: int
    rejected_signal_count: int
    candle_count: int


class StaticCandleResolver:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def get_candles(self, symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime) -> list[Candle]:
        return self.candles


class BatchBacktestRunner:
    def __init__(
        self,
        project: dict[str, Any],
        data_resolver: HistoricalDataResolver,
        batch_config: dict[str, Any],
        start_utc: datetime,
        end_utc: datetime,
    ) -> None:
        self.project = project
        self.data_resolver = data_resolver
        self.batch_config = batch_config
        self.start_utc = start_utc
        self.end_utc = end_utc
        self.sessions = load_sessions(project["sessions"])

    def run(self) -> Path:
        batch_id = self.batch_config["batch_id"]
        report_root = resolve_config_path(self.project["root"], self.project["backtest"].get("report_directory", "reports"))
        run_directory = report_root / f"{batch_id}_{self.start_utc:%Y%m%d}_{self.end_utc:%Y%m%d}"
        individual_root = run_directory / "individual_runs"
        individual_root.mkdir(parents=True, exist_ok=True)

        results: list[BatchComboResult] = []
        for symbol in self.batch_config["symbols"]:
            for session_name in self.batch_config["sessions"]:
                print(f"Preparing {symbol} {session_name}", flush=True)
                candles = self._load_session_candles(symbol, self.batch_config.get("timeframe", "MINUTE"), self.sessions[session_name])
                for target_r in self.batch_config.get("target_r_variants", [self.batch_config.get("orb", {}).get("take_profit_r_multiple", 2.0)]):
                    print(f"Backtesting {symbol} {session_name} {float(target_r):g}R", flush=True)
                    result = self._run_combo(symbol, session_name, float(target_r), candles, individual_root)
                    results.append(result)

        self._write_summary(run_directory, results)
        return run_directory

    def _run_combo(
        self,
        symbol: str,
        session_name: str,
        target_r: float,
        candles: list[Candle],
        individual_root: Path,
    ) -> BatchComboResult:
        session = self.sessions[session_name]
        timeframe = self.batch_config.get("timeframe", "MINUTE")
        strategy_config = {
            **self.project["strategy"],
            **self.batch_config.get("orb", {}),
            "strategy_id": f"orb_15m_{session_name}",
            "session_name": session_name,
            "take_profit_r_multiple": target_r,
        }
        backtest_config = {
            **self.project["backtest"],
            **self.batch_config.get("backtest_overrides", {}),
        }
        combo_report_root = individual_root / f"{symbol}_{session_name}_{target_r:g}R"
        engine = BacktestEngine(
            data_resolver=StaticCandleResolver(candles),
            strategy=ORBStrategy(),
            session=session,
            risk_manager=RiskManager(self.project["risk"]),
            broker=SimulatedBroker(
                starting_balance=float(backtest_config["starting_balance"]),
                currency=backtest_config.get("account_currency", "USD"),
                execution_config=backtest_config,
            ),
            report_directory=combo_report_root,
            config_snapshot={
                "app": self.project["app"],
                "strategy": strategy_config,
                "risk": self.project["risk"],
                "backtest": backtest_config,
                "batch": self.batch_config,
            },
            close_at_end=bool(strategy_config.get("close_at_session_end", True)),
        )
        result = engine.run(symbol, timeframe, self.start_utc, self.end_utc)
        return BatchComboResult(
            symbol=symbol,
            session=session_name,
            target_r=target_r,
            stop_loss_mode=strategy_config.get("stop_loss_mode", "opposite_range"),
            report_directory=str(result.report_directory),
            metrics=result.metrics,
            trade_count=result.trade_count,
            rejected_signal_count=result.rejected_signal_count,
            candle_count=len(candles),
        )

    def _load_session_candles(self, symbol: str, timeframe: str, session: TradingSession) -> list[Candle]:
        candles: list[Candle] = []
        for window_start, window_end in session_windows_utc(session, self.start_utc, self.end_utc):
            candles.extend(self.data_resolver.get_candles(symbol, timeframe, window_start, window_end))
        return sorted({(c.timestamp_utc, c.instrument): c for c in candles}.values(), key=lambda item: item.timestamp_utc)

    def _write_summary(self, run_directory: Path, results: list[BatchComboResult]) -> None:
        rows = []
        for result in results:
            row = {
                "symbol": result.symbol,
                "session": result.session,
                "target_r": result.target_r,
                "stop_loss_mode": result.stop_loss_mode,
                "trade_count": result.trade_count,
                "rejected_signal_count": result.rejected_signal_count,
                "candle_count": result.candle_count,
                "report_directory": result.report_directory,
                **result.metrics,
            }
            rows.append(row)

        with (run_directory / "summary.csv").open("w", newline="", encoding="utf-8") as file:
            fieldnames = list(rows[0].keys()) if rows else []
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        (run_directory / "summary.json").write_text(
            json.dumps(
                {
                    "batch_id": self.batch_config["batch_id"],
                    "start_utc": self.start_utc.isoformat(),
                    "end_utc": self.end_utc.isoformat(),
                    "results": rows,
                    "by_session": _aggregate(rows, "session"),
                    "by_symbol": _aggregate(rows, "symbol"),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def load_batch_config(root: Path, path: str) -> dict[str, Any]:
    return load_json(resolve_config_path(root, path))


def session_windows_utc(
    session: TradingSession,
    start_utc: datetime,
    end_utc: datetime,
) -> list[tuple[datetime, datetime]]:
    start_utc = _ensure_utc(start_utc)
    end_utc = _ensure_utc(end_utc)
    zone = ZoneInfo(session.timezone)
    local_start = start_utc.astimezone(zone).date()
    local_end = end_utc.astimezone(zone).date()
    windows = []
    current = local_start
    while current <= local_end:
        if current.weekday() < 5:
            open_local = datetime.combine(current, session.open, tzinfo=zone)
            close_local = datetime.combine(current, session.close, tzinfo=zone)
            open_utc = open_local.astimezone(timezone.utc)
            close_utc = close_local.astimezone(timezone.utc)
            clipped_start = max(open_utc, start_utc)
            clipped_end = min(close_utc, end_utc)
            if clipped_start < clipped_end:
                windows.append((clipped_start, clipped_end))
        current += timedelta(days=1)
    return windows


def _aggregate(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row[key]), []).append(row)

    aggregated = []
    for value, items in sorted(groups.items()):
        starting_balance = sum(float(item["starting_balance"]) for item in items)
        ending_balance = sum(float(item["ending_balance"]) for item in items)
        total_trades = sum(int(item["trade_count"]) for item in items)
        net_profit = sum(float(item["net_profit"]) for item in items)
        win_rates = [float(item["win_rate_pct"]) for item in items if int(item["trade_count"]) > 0]
        profit_factors = [
            float(item["profit_factor"])
            for item in items
            if item.get("profit_factor") not in (None, "")
        ]
        aggregated.append(
            {
                key: value,
                "combo_count": len(items),
                "trade_count": total_trades,
                "net_profit": net_profit,
                "total_return_pct": ((ending_balance - starting_balance) / starting_balance) * 100
                if starting_balance
                else 0,
                "average_win_rate_pct": sum(win_rates) / len(win_rates) if win_rates else 0,
                "average_profit_factor": sum(profit_factors) / len(profit_factors) if profit_factors else None,
            }
        )
    return aggregated


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
