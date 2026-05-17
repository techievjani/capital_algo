from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from capital_algo.models import Candle
from capital_algo.strategies.asset_breakout import (
    AssetBreakoutStrategy,
    BreakoutContext,
    BreakoutDirection,
    BreakoutRejection,
)


BASE_TIME = datetime(2026, 1, 1, 7, 0, tzinfo=timezone.utc)


def candle(index: int, close: float, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(
        provider="test",
        instrument="BTCUSD",
        timeframe="MINUTE_5",
        timestamp_utc=BASE_TIME + timedelta(minutes=5 * index),
        open=close - 1.0,
        high=high if high is not None else close + 1.0,
        low=low if low is not None else close - 1.0,
        close=close,
        volume=100.0,
    )


def breakout_setup(final_close: float) -> list[Candle]:
    candles = [candle(index, 100.0 + (index * 0.05)) for index in range(220)]
    candles.extend(candle(220 + index, 120.0 + index, high=122.0 + index, low=118.0 + index) for index in range(24))
    candles.append(candle(244, final_close, high=final_close + 1.0, low=final_close - 2.0))
    return candles


class AssetBreakoutStrategyTests(unittest.TestCase):
    def test_long_breakout_signal(self) -> None:
        strategy = AssetBreakoutStrategy(
            {
                "lookback_bars": 24,
                "ema_period": 20,
                "atr_period": 14,
                "target_r": 2.0,
                "atr_stop_mult": 1.0,
                "entry_hours_utc": [3],
            }
        )
        result = strategy.evaluate(BreakoutContext("BTCUSD", breakout_setup(160.0)))
        self.assertTrue(result.should_trade, result)
        self.assertEqual(BreakoutDirection.LONG, result.direction)
        self.assertLess(result.stop_loss, result.entry_price)
        self.assertGreater(result.target_price, result.entry_price)

    def test_reject_outside_session(self) -> None:
        strategy = AssetBreakoutStrategy({"lookback_bars": 24, "ema_period": 20, "entry_hours_utc": [7]})
        result = strategy.evaluate(BreakoutContext("BTCUSD", breakout_setup(160.0)))
        self.assertFalse(result.should_trade)
        self.assertEqual(BreakoutRejection.OUTSIDE_SESSION, result.rejection_reason)


if __name__ == "__main__":
    unittest.main()
