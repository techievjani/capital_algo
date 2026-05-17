from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from capital_algo.models import Candle
from capital_algo.strategies.forex_pullback import (
    ForexPullbackContext,
    ForexTrendPullbackScalper,
    NewsEvent,
    RejectionReason,
    TradeDirection,
)


BASE_TIME = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def candle(index: int, close: float, timeframe: str = "MINUTE", open_: float | None = None, high: float | None = None, low: float | None = None) -> Candle:
    open_value = close - 0.0002 if open_ is None else open_
    return Candle(
        provider="test",
        instrument="EURUSD",
        timeframe=timeframe,
        timestamp_utc=BASE_TIME + timedelta(minutes=index),
        open=open_value,
        high=max(high if high is not None else close + 0.0002, open_value, close),
        low=min(low if low is not None else close - 0.0002, open_value, close),
        close=close,
        volume=100.0,
    )


def trend_candles(count: int, start: float, step: float, timeframe: str) -> list[Candle]:
    return [candle(i, start + (i * step), timeframe=timeframe) for i in range(count)]


def long_1m() -> list[Candle]:
    candles = trend_candles(35, 1.1000, 0.00012, "MINUTE")
    # impulse, then pullback to the EMA/VWAP area without breaking swing, then bullish trigger
    candles[-9] = candle(26, 1.1050, low=1.1047, high=1.1053)
    candles[-8] = candle(27, 1.1055, low=1.1051, high=1.1058)
    candles[-7] = candle(28, 1.1062, low=1.1058, high=1.1065)
    candles[-6] = candle(29, 1.1053, low=1.1048, high=1.1058)
    candles[-5] = candle(30, 1.1051, low=1.1047, high=1.1055)
    candles[-4] = candle(31, 1.1054, low=1.1049, high=1.1056)
    candles[-3] = candle(32, 1.1058, low=1.1053, high=1.1060)
    candles[-2] = candle(33, 1.1061, low=1.1056, high=1.1062)
    candles[-1] = candle(34, 1.1067, open_=1.1059, low=1.1058, high=1.1068)
    return candles


def short_1m() -> list[Candle]:
    candles = trend_candles(35, 1.1100, -0.00012, "MINUTE")
    candles[-9] = candle(26, 1.1050, open_=1.1054, low=1.1047, high=1.1056)
    candles[-8] = candle(27, 1.1045, open_=1.1049, low=1.1042, high=1.1050)
    candles[-7] = candle(28, 1.1038, open_=1.1043, low=1.1035, high=1.1044)
    candles[-6] = candle(29, 1.1047, open_=1.1040, low=1.1039, high=1.1052)
    candles[-5] = candle(30, 1.1049, open_=1.1043, low=1.1041, high=1.1053)
    candles[-4] = candle(31, 1.1046, open_=1.1050, low=1.1044, high=1.1051)
    candles[-3] = candle(32, 1.1042, open_=1.1047, low=1.1040, high=1.1048)
    candles[-2] = candle(33, 1.1039, open_=1.1043, low=1.1038, high=1.1044)
    candles[-1] = candle(34, 1.1032, open_=1.1040, low=1.1031, high=1.1041)
    return candles


def long_context(**overrides) -> ForexPullbackContext:
    ctx = ForexPullbackContext(
        symbol="EURUSD",
        current_time=BASE_TIME + timedelta(minutes=35),
        candles_1m=long_1m(),
        candles_5m=trend_candles(45, 1.0800, 0.00045, "MINUTE_5"),
        candles_15m=trend_candles(60, 1.0600, 0.00055, "MINUTE_15"),
        current_spread=0.8,
        config={
            "indicators": {"adx_min": 5},
            "filters": {"max_vwap_crosses": 99},
            "min_impulse_pips": {"EURUSD": 3},
            "pullback_buffer_pips": {"EURUSD": 8},
        },
    )
    return replace(ctx, **overrides)


def short_context(**overrides) -> ForexPullbackContext:
    ctx = ForexPullbackContext(
        symbol="EURUSD",
        current_time=BASE_TIME + timedelta(minutes=35),
        candles_1m=short_1m(),
        candles_5m=trend_candles(45, 1.1200, -0.00045, "MINUTE_5"),
        candles_15m=trend_candles(60, 1.1400, -0.00055, "MINUTE_15"),
        current_spread=0.8,
        config={
            "indicators": {"adx_min": 5},
            "filters": {"max_vwap_crosses": 99},
            "min_impulse_pips": {"EURUSD": 3},
            "pullback_buffer_pips": {"EURUSD": 8},
        },
    )
    return replace(ctx, **overrides)


class ForexPullbackEngineTests(unittest.TestCase):
    def test_valid_long_pullback_signal(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(long_context())
        self.assertTrue(result.should_trade, result)
        self.assertEqual(TradeDirection.LONG, result.direction)

    def test_valid_short_pullback_signal(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(short_context())
        self.assertTrue(result.should_trade, result)
        self.assertEqual(TradeDirection.SHORT, result.direction)

    def test_long_bias_valid(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(long_context())
        self.assertTrue(result.should_trade, result)
        self.assertEqual("LONG_TREND_PULLBACK_CONFIRMED", result.reason)
        self.assertGreater(result.metadata["ema_15m_50_slope"], 0)
        self.assertGreater(result.metadata["ema_5m_20_slope"], 0)

    def test_short_bias_valid(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(short_context())
        self.assertTrue(result.should_trade, result)
        self.assertEqual("SHORT_TREND_PULLBACK_CONFIRMED", result.reason)
        self.assertLess(result.metadata["ema_15m_50_slope"], 0)
        self.assertLess(result.metadata["ema_5m_20_slope"], 0)

    def test_reject_low_adx(self) -> None:
        ctx = long_context(config={"indicators": {"adx_min": 101}, "filters": {"max_vwap_crosses": 99}})
        result = ForexTrendPullbackScalper().evaluate(ctx)
        self.assertEqual(RejectionReason.LOW_ADX, result.rejection_reason)

    def test_reject_spread_too_high(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(long_context(current_spread=9.0))
        self.assertEqual(RejectionReason.SPREAD_TOO_HIGH, result.rejection_reason)

    def test_reject_news_blackout(self) -> None:
        event = NewsEvent(timestamp_utc=BASE_TIME + timedelta(minutes=35), impact="high", currency="EUR")
        result = ForexTrendPullbackScalper().evaluate(long_context(news_events=[event]))
        self.assertEqual(RejectionReason.NEWS_BLACKOUT, result.rejection_reason)

    def test_reject_outside_learned_entry_hours(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(long_context(config={
            "filters": {"entry_hours_utc": [7, 9, 16], "max_vwap_crosses": 99},
            "indicators": {"adx_min": 5},
        }))
        self.assertEqual(RejectionReason.OUTSIDE_SESSION, result.rejection_reason)

    def test_reject_insufficient_data(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_1m=long_1m()[:5]))
        self.assertEqual(RejectionReason.INSUFFICIENT_DATA, result.rejection_reason)

    def test_reject_vwap_chop(self) -> None:
        choppy = [candle(i, 1.1000 + (0.0005 if i % 2 == 0 else -0.0005)) for i in range(35)]
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_1m=choppy, config={"indicators": {"adx_min": 5}}))
        self.assertEqual(RejectionReason.VWAP_CHOP, result.rejection_reason)

    def test_reject_flat_ema_slope(self) -> None:
        flat_15 = trend_candles(60, 1.1000, 0.0, "MINUTE_15")
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_15m=flat_15))
        self.assertEqual(RejectionReason.FLAT_OR_WRONG_EMA_SLOPE, result.rejection_reason)

    def test_reject_long_price_below_vwap(self) -> None:
        weak_5 = trend_candles(45, 1.0800, 0.00045, "MINUTE_5")
        weak_5[-1] = replace(weak_5[-1], close=1.0880, low=1.0878)
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_5m=weak_5))
        self.assertEqual(RejectionReason.PRICE_NOT_ABOVE_VWAP, result.rejection_reason)

    def test_reject_short_price_above_vwap(self) -> None:
        weak_5 = trend_candles(45, 1.1200, -0.00045, "MINUTE_5")
        weak_5[-1] = replace(weak_5[-1], close=1.1110, high=1.1112)
        result = ForexTrendPullbackScalper().evaluate(short_context(candles_5m=weak_5))
        self.assertEqual(RejectionReason.PRICE_NOT_BELOW_VWAP, result.rejection_reason)

    def test_reject_pullback_breaks_swing(self) -> None:
        candles = long_1m()
        candles[-5] = replace(candles[-5], low=1.0900)
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_1m=candles))
        self.assertEqual(RejectionReason.PULLBACK_BROKE_SWING, result.rejection_reason)

    def test_reject_no_valid_impulse(self) -> None:
        candles = long_1m()
        for index in range(26, 34):
            candles[index] = replace(candles[index], high=1.1050, low=1.1047, close=1.1049)
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_1m=candles))
        self.assertEqual(RejectionReason.NO_VALID_IMPULSE, result.rejection_reason)

    def test_reject_no_valid_pullback(self) -> None:
        candles = long_1m()
        for index in range(29, 34):
            candles[index] = replace(candles[index], high=1.1095, low=1.1090, close=1.1092)
        candles[-1] = candle(34, 1.1100, open_=1.1094, low=1.1093, high=1.1101)
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_1m=candles, config={
            "indicators": {"adx_min": 5},
            "filters": {"max_vwap_crosses": 99},
            "min_impulse_pips": {"EURUSD": 3},
            "pullback_buffer_pips": {"EURUSD": 0.1},
        }))
        self.assertEqual(RejectionReason.NO_VALID_PULLBACK, result.rejection_reason)

    def test_reject_conflicting_timeframe_state(self) -> None:
        bearish_5 = trend_candles(45, 1.1200, -0.00045, "MINUTE_5")
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_5m=bearish_5))
        self.assertEqual(RejectionReason.NO_TREND_BIAS, result.rejection_reason)

    def test_reject_poor_candle_quality(self) -> None:
        candles = long_1m()
        candles[-1] = candle(34, 1.1067, open_=1.1065, low=1.1050, high=1.1080)
        result = ForexTrendPullbackScalper().evaluate(long_context(candles_1m=candles))
        self.assertEqual(RejectionReason.POOR_CANDLE_QUALITY, result.rejection_reason)

    def test_long_sl_and_target(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(long_context(config={"indicators": {"adx_min": 5}, "filters": {"max_vwap_crosses": 99}, "target_r": 1.0}))
        self.assertTrue(result.should_trade)
        self.assertAlmostEqual(result.target_price - result.entry_price, result.entry_price - result.stop_loss)

    def test_short_sl_and_target(self) -> None:
        result = ForexTrendPullbackScalper().evaluate(short_context(config={"indicators": {"adx_min": 5}, "filters": {"max_vwap_crosses": 99}, "target_r": 1.0}))
        self.assertTrue(result.should_trade)
        self.assertAlmostEqual(result.entry_price - result.target_price, result.stop_loss - result.entry_price)

    def test_prevent_duplicate_signal_same_candle(self) -> None:
        engine = ForexTrendPullbackScalper()
        first = engine.evaluate(long_context())
        second = engine.evaluate(long_context())
        self.assertTrue(first.should_trade)
        self.assertEqual(RejectionReason.ENTRY_TRIGGER_NOT_CONFIRMED, second.rejection_reason)


if __name__ == "__main__":
    unittest.main()
