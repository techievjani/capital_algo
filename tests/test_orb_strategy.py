from __future__ import annotations

import unittest
from datetime import datetime, timezone

from capital_algo.models import Candle, TradeAction
from capital_algo.sessions import TradingSession
from capital_algo.strategies.orb import ORBStrategy


class ORBStrategyTests(unittest.TestCase):
    def test_emits_long_breakout_after_range(self) -> None:
        strategy = ORBStrategy()
        strategy.initialize(
            {
                "strategy_id": "orb_v1",
                "opening_range_minutes": 2,
                "trade_direction": "both",
                "entry_buffer_points": 0,
                "take_profit_r_multiple": 2.0,
                "max_trades_per_session": 1,
            },
            {},
        )
        session = TradingSession.from_strings("test", "UTC", "13:30", "20:00")
        bars = [
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc), 10, 11, 9, 10),
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 31, tzinfo=timezone.utc), 10, 12, 9, 11),
            Candle("test", "US100", "MINUTE", datetime(2026, 1, 1, 13, 32, tzinfo=timezone.utc), 12, 13, 11, 12.5),
        ]

        signals = []
        for bar in bars:
            signals.extend(strategy.on_bar(bar, {"session": session}))

        self.assertEqual(1, len(signals))
        self.assertEqual(TradeAction.BUY, signals[0].action)


if __name__ == "__main__":
    unittest.main()

