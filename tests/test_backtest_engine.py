from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from capital_algo.backtest import BacktestEngine
from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.models import Candle
from capital_algo.risk.manager import RiskManager
from capital_algo.sessions import TradingSession
from capital_algo.strategies.orb import ORBStrategy


class StaticResolver:
    def __init__(self, candles):
        self.candles = candles

    def get_candles(self, symbol, timeframe, start_utc, end_utc):
        return self.candles


class BacktestEngineTests(unittest.TestCase):
    def test_runs_orb_backtest_from_static_candles(self) -> None:
        candles = [
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc), 10, 11, 9, 10),
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 31, tzinfo=timezone.utc), 10, 12, 9, 11),
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 32, tzinfo=timezone.utc), 12, 13, 11, 12.5),
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 33, tzinfo=timezone.utc), 12.5, 20, 12, 19),
        ]
        strategy_config = {
            "strategy_id": "orb_v1",
            "opening_range_minutes": 2,
            "trade_direction": "both",
            "entry_buffer_points": 0,
            "take_profit_r_multiple": 1.0,
            "max_trades_per_session": 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            engine = BacktestEngine(
                data_resolver=StaticResolver(candles),
                strategy=ORBStrategy(),
                session=TradingSession.from_strings("test", "UTC", "13:30", "20:00"),
                risk_manager=RiskManager(
                    {
                        "account_risk_per_trade_pct": 1.0,
                        "max_daily_loss_pct": 2.0,
                        "max_open_positions": 2,
                        "max_trades_per_day": 3,
                        "allow_live_trading": False,
                    }
                ),
                broker=SimulatedBroker(10000),
                report_directory=Path(tmp),
                config_snapshot={"strategy": strategy_config},
            )

            result = engine.run("US100", "MINUTE", candles[0].timestamp_utc, candles[-1].timestamp_utc)

        self.assertEqual(1, result.trade_count)
        self.assertGreater(result.metrics["net_profit"], 0)


if __name__ == "__main__":
    unittest.main()

