from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.data.resolver import HistoricalDataResolver
from capital_algo.models import Candle
from capital_algo.reporting.reports import metrics_from_trades, write_backtest_report
from capital_algo.risk.manager import RiskManager
from capital_algo.sessions import TradingSession
from capital_algo.strategies.base import Strategy
from capital_algo.timeframes import timeframe_delta


@dataclass(frozen=True)
class BacktestResult:
    report_directory: Path
    metrics: dict[str, Any]
    trade_count: int
    rejected_signal_count: int


class BacktestEngine:
    def __init__(
        self,
        data_resolver: HistoricalDataResolver,
        strategy: Strategy,
        session: TradingSession,
        risk_manager: RiskManager,
        broker: SimulatedBroker,
        report_directory: Path,
        config_snapshot: dict[str, Any],
        close_at_end: bool = True,
    ) -> None:
        self.data_resolver = data_resolver
        self.strategy = strategy
        self.session = session
        self.risk_manager = risk_manager
        self.broker = broker
        self.report_directory = report_directory
        self.config_snapshot = config_snapshot
        self.close_at_end = close_at_end
        self.rejected_signals: list[dict[str, Any]] = []

    def run(self, symbol: str, timeframe: str, start_utc, end_utc) -> BacktestResult:
        candles = self.data_resolver.get_candles(symbol, timeframe, start_utc, end_utc)
        self.strategy.initialize(self.config_snapshot["strategy"], {"mode": "backtest"})

        last_prices: dict[str, float] = {}
        starting_balance = self.broker.balance
        timeframe_minutes = timeframe_delta(timeframe).total_seconds() / 60
        for candle in candles:
            timestamp = candle.timestamp_utc.isoformat()
            last_prices[candle.instrument] = candle.close
            self.broker.update_for_bar(candle.instrument, candle.high, candle.low, candle.close, timestamp)

            signals = self.strategy.on_bar(
                candle,
                {
                    "session": self.session,
                    "mode": "backtest",
                    "timeframe": timeframe,
                    "timeframe_minutes": timeframe_minutes,
                },
            )
            for signal in signals:
                decision = self.risk_manager.evaluate(
                    signal,
                    self.broker.get_account_snapshot(),
                    candle.close,
                    trading_day=self.session.trading_day(candle.timestamp_utc),
                )
                if not decision.approved or decision.order is None:
                    self.rejected_signals.append(
                        {
                            "timestamp": timestamp,
                            "instrument": signal.instrument,
                            "reason": decision.reason,
                            "signal_reason": signal.reason,
                        }
                    )
                    continue
                self.broker.submit_order_at_price(decision.order, candle.close, timestamp)
                self.risk_manager.record_trade()

        if self.close_at_end and last_prices:
            self.broker.close_all(last_prices, candles[-1].timestamp_utc.isoformat(), "end_of_backtest")

        metrics = metrics_from_trades(starting_balance, self.broker.balance, self.broker.closed_trades)
        run_name = f"{symbol}_{timeframe}_{start_utc:%Y%m%dT%H%M%S}_{end_utc:%Y%m%dT%H%M%S}"
        report_dir = write_backtest_report(
            self.report_directory,
            run_name,
            self.config_snapshot,
            metrics,
            self.broker.closed_trades,
            self.rejected_signals,
        )
        return BacktestResult(
            report_directory=report_dir,
            metrics=metrics,
            trade_count=len(self.broker.closed_trades),
            rejected_signal_count=len(self.rejected_signals),
        )


def sort_candles(candles: list[Candle]) -> list[Candle]:
    return sorted(candles, key=lambda candle: (candle.timestamp_utc, candle.instrument))
