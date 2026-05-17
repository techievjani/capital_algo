from __future__ import annotations

from dataclasses import dataclass

from capital_algo.models import Candle
from capital_algo.strategies.forex_pullback import indicators
from capital_algo.strategies.forex_pullback.config import symbol_value
from capital_algo.strategies.forex_pullback.models import ForexPullbackContext, RejectionReason, TradeDirection


@dataclass(frozen=True)
class PullbackResult:
    valid: bool
    rejection_reason: RejectionReason | None
    details: str
    swing_low: float | None = None
    swing_high: float | None = None
    pullback_high: float | None = None
    pullback_low: float | None = None
    metadata: dict | None = None


def detect_pullback(context: ForexPullbackContext, config: dict, direction: TradeDirection) -> PullbackResult:
    swing_lookback = int(config["lookbacks"]["swing"])
    impulse_lookback = int(config["lookbacks"]["impulse"])
    pullback_lookback = int(config["lookbacks"]["pullback"])
    if len(context.candles_1m) < max(swing_lookback, impulse_lookback, pullback_lookback) + 3:
        return PullbackResult(False, RejectionReason.INSUFFICIENT_DATA, "Not enough 1m candles")

    pip_size = symbol_value(config, "pip_size", context.symbol)
    min_impulse = symbol_value(config, "min_impulse_pips", context.symbol) * pip_size
    buffer = symbol_value(config, "pullback_buffer_pips", context.symbol) * pip_size
    candles = context.candles_1m
    impulse_candles = candles[-impulse_lookback - 1 : -1]
    pullback_candles = candles[-pullback_lookback - 1 : -1]
    swing_reference_candles = candles[: -pullback_lookback - 1]
    latest = candles[-1]
    swing_low = indicators.recent_swing_low(swing_reference_candles, swing_lookback)
    swing_high = indicators.recent_swing_high(swing_reference_candles, swing_lookback)
    ema_fast = indicators.ema(candles[:-1], int(config["indicators"]["ema_1m_fast"]))
    ema_slow = indicators.ema(candles[:-1], int(config["indicators"]["ema_1m_slow"]))
    vwap_1m = indicators.vwap(candles[:-1])
    if None in (swing_low, swing_high, ema_fast, ema_slow, vwap_1m):
        return PullbackResult(False, RejectionReason.INSUFFICIENT_DATA, "Pullback indicators could not be calculated")

    if direction == TradeDirection.LONG:
        if not _long_impulse(impulse_candles, min_impulse):
            return PullbackResult(False, RejectionReason.NO_VALID_IMPULSE, "No upward impulse")
        if min(candle.low for candle in pullback_candles) < swing_low:
            return PullbackResult(False, RejectionReason.PULLBACK_BROKE_SWING, "Pullback broke recent swing low", swing_low, swing_high)
        if not _touched_zone(pullback_candles, [ema_fast, ema_slow, vwap_1m], buffer):
            return PullbackResult(False, RejectionReason.NO_VALID_PULLBACK, "Pullback did not touch EMA/VWAP zone", swing_low, swing_high)
        return PullbackResult(
            True,
            None,
            "Long pullback valid",
            swing_low=swing_low,
            swing_high=swing_high,
            pullback_high=max(candle.high for candle in pullback_candles),
            pullback_low=min(candle.low for candle in pullback_candles),
            metadata={"ema_1m_9": ema_fast, "ema_1m_20": ema_slow, "vwap_1m": vwap_1m},
        )

    if not _short_impulse(impulse_candles, min_impulse):
        return PullbackResult(False, RejectionReason.NO_VALID_IMPULSE, "No downward impulse")
    if max(candle.high for candle in pullback_candles) > swing_high:
        return PullbackResult(False, RejectionReason.PULLBACK_BROKE_SWING, "Pullback broke recent swing high", swing_low, swing_high)
    if not _touched_zone(pullback_candles, [ema_fast, ema_slow, vwap_1m], buffer):
        return PullbackResult(False, RejectionReason.NO_VALID_PULLBACK, "Pullback did not touch EMA/VWAP zone", swing_low, swing_high)
    return PullbackResult(
        True,
        None,
        "Short pullback valid",
        swing_low=swing_low,
        swing_high=swing_high,
        pullback_high=max(candle.high for candle in pullback_candles),
        pullback_low=min(candle.low for candle in pullback_candles),
        metadata={"ema_1m_9": ema_fast, "ema_1m_20": ema_slow, "vwap_1m": vwap_1m},
    )


def _long_impulse(candles: list[Candle], min_move: float) -> bool:
    return candles[-1].high > candles[0].high and candles[-1].low > candles[0].low and candles[-1].high - candles[0].low >= min_move


def _short_impulse(candles: list[Candle], min_move: float) -> bool:
    return candles[-1].low < candles[0].low and candles[-1].high < candles[0].high and candles[0].high - candles[-1].low >= min_move


def _touched_zone(candles: list[Candle], levels: list[float], buffer: float) -> bool:
    for candle in candles:
        for level in levels:
            if candle.low - buffer <= level <= candle.high + buffer:
                return True
    return False
