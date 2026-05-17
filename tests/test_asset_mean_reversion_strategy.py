from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from capital_algo.models import Candle
from capital_algo.strategies.asset_mean_reversion import (
    AssetMeanReversionStrategy,
    MeanReversionContext,
    MeanReversionDirection,
    MeanReversionRejection,
)


BASE_TIME = datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)


def candle(index: int, close: float, open_: float | None = None) -> Candle:
    open_value = close if open_ is None else open_
    high = max(open_value, close) + 2.0
    low = min(open_value, close) - 2.0
    return Candle(
        provider="test",
        instrument="BTCUSD",
        timeframe="MINUTE_5",
        timestamp_utc=BASE_TIME + timedelta(minutes=5 * index),
        open=open_value,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def long_setup() -> list[Candle]:
    candles = [candle(index, 100.0 + (index * 0.01)) for index in range(118)]
    candles.extend(
        [
            candle(118, 92.0, open_=100.0),
            candle(119, 88.0, open_=92.0),
        ]
    )
    return candles


def short_setup() -> list[Candle]:
    candles = [candle(index, 100.0 - (index * 0.01)) for index in range(118)]
    candles.extend(
        [
            candle(118, 108.0, open_=100.0),
            candle(119, 112.0, open_=108.0),
        ]
    )
    return candles


class AssetMeanReversionStrategyTests(unittest.TestCase):
    def test_long_atr_mean_reversion_signal(self) -> None:
        strategy = AssetMeanReversionStrategy(
            {
                "ema_period": 20,
                "atr_period": 14,
                "rsi_period": 14,
                "z_score": 1.0,
                "target_r": 1.5,
                "atr_stop_mult": 1.0,
                "entry_hours_utc": [5],
            }
        )
        result = strategy.evaluate(MeanReversionContext("BTCUSD", long_setup()))
        self.assertTrue(result.should_trade, result)
        self.assertEqual(MeanReversionDirection.LONG, result.direction)
        self.assertLess(result.stop_loss, result.entry_price)
        self.assertGreater(result.target_price, result.entry_price)

    def test_short_atr_mean_reversion_signal(self) -> None:
        strategy = AssetMeanReversionStrategy(
            {
                "ema_period": 20,
                "atr_period": 14,
                "rsi_period": 14,
                "z_score": 1.0,
                "target_r": 1.5,
                "atr_stop_mult": 1.0,
                "entry_hours_utc": [5],
            }
        )
        result = strategy.evaluate(MeanReversionContext("BTCUSD", short_setup()))
        self.assertTrue(result.should_trade, result)
        self.assertEqual(MeanReversionDirection.SHORT, result.direction)
        self.assertGreater(result.stop_loss, result.entry_price)
        self.assertLess(result.target_price, result.entry_price)

    def test_reject_outside_session(self) -> None:
        strategy = AssetMeanReversionStrategy({"ema_period": 20, "entry_hours_utc": [7]})
        result = strategy.evaluate(MeanReversionContext("BTCUSD", long_setup()))
        self.assertFalse(result.should_trade)
        self.assertEqual(MeanReversionRejection.OUTSIDE_SESSION, result.rejection_reason)


if __name__ == "__main__":
    unittest.main()
