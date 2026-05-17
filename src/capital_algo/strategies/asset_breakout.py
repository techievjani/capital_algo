from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from capital_algo.models import Candle


class BreakoutDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class BreakoutRejection(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    NO_BREAKOUT = "NO_BREAKOUT"
    INVALID_RISK = "INVALID_RISK"


@dataclass(frozen=True)
class BreakoutContext:
    symbol: str
    candles_5m: list[Candle]
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BreakoutEvaluation:
    symbol: str
    should_trade: bool
    direction: BreakoutDirection | None = None
    rejection_reason: BreakoutRejection | None = None
    reason: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def reject(
        cls,
        symbol: str,
        reason: BreakoutRejection,
        metadata: dict[str, Any] | None = None,
    ) -> "BreakoutEvaluation":
        return cls(symbol=symbol, should_trade=False, rejection_reason=reason, metadata=metadata or {})


class AssetBreakoutStrategy:
    """Rolling-range breakout with EMA trend filter and ATR stop."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def evaluate(self, context: BreakoutContext) -> BreakoutEvaluation:
        config = _deep_merge(self.config, context.config)
        symbol_config = dict(config.get("symbols", {}).get(context.symbol, {}))
        lookback_bars = int(symbol_config.get("lookback_bars", config.get("lookback_bars", 24)))
        ema_period = int(symbol_config.get("ema_period", config.get("ema_period", 200)))
        atr_period = int(symbol_config.get("atr_period", config.get("atr_period", 14)))
        min_bars = max(lookback_bars + 1, ema_period, atr_period + 1) + 1
        if len(context.candles_5m) < min_bars:
            return BreakoutEvaluation.reject(context.symbol, BreakoutRejection.INSUFFICIENT_DATA)

        current = context.candles_5m[-1]
        entry_hours = symbol_config.get("entry_hours_utc", config.get("entry_hours_utc"))
        if entry_hours is not None and current.timestamp_utc.hour not in set(int(hour) for hour in entry_hours):
            return BreakoutEvaluation.reject(
                context.symbol,
                BreakoutRejection.OUTSIDE_SESSION,
                {"hour_utc": current.timestamp_utc.hour},
            )

        previous_range = context.candles_5m[-lookback_bars - 1 : -1]
        rolling_high = max(candle.high for candle in previous_range)
        rolling_low = min(candle.low for candle in previous_range)
        closes = [candle.close for candle in context.candles_5m]
        ema_value = _ema(closes, ema_period)
        atr_value = _atr(context.candles_5m, atr_period)
        if ema_value is None or atr_value is None or atr_value <= 0:
            return BreakoutEvaluation.reject(context.symbol, BreakoutRejection.INSUFFICIENT_DATA)

        atr_stop_mult = float(symbol_config.get("atr_stop_mult", config.get("atr_stop_mult", 1.0)))
        target_r = float(symbol_config.get("target_r", config.get("target_r", 2.0)))
        metadata = {
            "close": current.close,
            "ema": ema_value,
            "atr": atr_value,
            "rolling_high": rolling_high,
            "rolling_low": rolling_low,
            "lookback_bars": lookback_bars,
            "atr_stop_mult": atr_stop_mult,
            "target_r": target_r,
            "timeframe": current.timeframe,
        }

        if current.close > rolling_high and current.close > ema_value:
            return _build_trade(
                context.symbol,
                BreakoutDirection.LONG,
                current.close,
                atr_value,
                atr_stop_mult,
                target_r,
                "LONG_RANGE_BREAKOUT",
                metadata,
            )
        if current.close < rolling_low and current.close < ema_value:
            return _build_trade(
                context.symbol,
                BreakoutDirection.SHORT,
                current.close,
                atr_value,
                atr_stop_mult,
                target_r,
                "SHORT_RANGE_BREAKOUT",
                metadata,
            )
        return BreakoutEvaluation.reject(context.symbol, BreakoutRejection.NO_BREAKOUT, metadata)


def _build_trade(
    symbol: str,
    direction: BreakoutDirection,
    entry: float,
    atr_value: float,
    atr_stop_mult: float,
    target_r: float,
    reason: str,
    metadata: dict[str, Any],
) -> BreakoutEvaluation:
    risk = atr_value * atr_stop_mult
    if risk <= 0:
        return BreakoutEvaluation.reject(symbol, BreakoutRejection.INVALID_RISK, metadata)
    if direction == BreakoutDirection.LONG:
        stop_loss = entry - risk
        target_price = entry + (risk * target_r)
    else:
        stop_loss = entry + risk
        target_price = entry - (risk * target_r)
    return BreakoutEvaluation(
        symbol=symbol,
        should_trade=True,
        direction=direction,
        reason=reason,
        entry_price=entry,
        stop_loss=stop_loss,
        target_price=target_price,
        metadata=metadata,
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    ema_value = sum(values[:period]) / period
    for value in values[period:]:
        ema_value = (value * alpha) + (ema_value * (1 - alpha))
    return ema_value


def _atr(candles: list[Candle], period: int) -> float | None:
    if len(candles) < period + 1:
        return None
    true_ranges: list[float] = []
    for previous, current in zip(candles[:-1], candles[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    return sum(true_ranges[-period:]) / period if len(true_ranges) >= period else None
