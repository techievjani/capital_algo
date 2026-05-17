from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from capital_algo.models import Candle


class MeanReversionDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class MeanReversionRejection(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    NO_MEAN_REVERSION_SETUP = "NO_MEAN_REVERSION_SETUP"
    INVALID_RISK = "INVALID_RISK"


@dataclass(frozen=True)
class MeanReversionContext:
    symbol: str
    candles_5m: list[Candle]
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MeanReversionEvaluation:
    symbol: str
    should_trade: bool
    direction: MeanReversionDirection | None = None
    rejection_reason: MeanReversionRejection | None = None
    reason: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def reject(
        cls,
        symbol: str,
        reason: MeanReversionRejection,
        metadata: dict[str, Any] | None = None,
    ) -> "MeanReversionEvaluation":
        return cls(symbol=symbol, should_trade=False, rejection_reason=reason, metadata=metadata or {})


class AssetMeanReversionStrategy:
    """ATR stretch mean-reversion strategy for independently tuned assets."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def evaluate(self, context: MeanReversionContext) -> MeanReversionEvaluation:
        config = _deep_merge(self.config, context.config)
        symbol_config = _symbol_config(config, context.symbol)
        ema_period = int(symbol_config.get("ema_period", config.get("ema_period", 100)))
        atr_period = int(symbol_config.get("atr_period", config.get("atr_period", 14)))
        rsi_period = int(symbol_config.get("rsi_period", config.get("rsi_period", 14)))
        min_bars = max(ema_period, atr_period + 1, rsi_period + 1) + 2
        if len(context.candles_5m) < min_bars:
            return MeanReversionEvaluation.reject(context.symbol, MeanReversionRejection.INSUFFICIENT_DATA)

        current = context.candles_5m[-1]
        entry_hours = symbol_config.get("entry_hours_utc", config.get("entry_hours_utc"))
        if entry_hours is not None and current.timestamp_utc.hour not in set(int(hour) for hour in entry_hours):
            return MeanReversionEvaluation.reject(
                context.symbol,
                MeanReversionRejection.OUTSIDE_SESSION,
                {"hour_utc": current.timestamp_utc.hour},
            )

        closes = [candle.close for candle in context.candles_5m]
        ema_value = _ema(closes, ema_period)
        atr_value = _atr(context.candles_5m, atr_period)
        rsi_value = _rsi(closes, rsi_period)
        if ema_value is None or atr_value is None or atr_value <= 0 or rsi_value is None:
            return MeanReversionEvaluation.reject(context.symbol, MeanReversionRejection.INSUFFICIENT_DATA)

        z_score = float(symbol_config.get("z_score", config.get("z_score", 2.0)))
        atr_stop_mult = float(symbol_config.get("atr_stop_mult", config.get("atr_stop_mult", 1.0)))
        target_r = float(symbol_config.get("target_r", config.get("target_r", 1.5)))
        oversold_rsi = float(symbol_config.get("oversold_rsi", config.get("oversold_rsi", 30.0)))
        overbought_rsi = float(symbol_config.get("overbought_rsi", config.get("overbought_rsi", 70.0)))

        upper_band = ema_value + (z_score * atr_value)
        lower_band = ema_value - (z_score * atr_value)
        metadata = {
            "close": current.close,
            "ema": ema_value,
            "atr": atr_value,
            "rsi": rsi_value,
            "upper_band": upper_band,
            "lower_band": lower_band,
            "z_score": z_score,
            "atr_stop_mult": atr_stop_mult,
            "target_r": target_r,
            "timeframe": current.timeframe,
        }

        if current.close <= lower_band and rsi_value <= oversold_rsi:
            return _build_trade(
                context.symbol,
                MeanReversionDirection.LONG,
                current.close,
                atr_value,
                atr_stop_mult,
                target_r,
                "LONG_ATR_MEAN_REVERSION",
                metadata,
            )
        if current.close >= upper_band and rsi_value >= overbought_rsi:
            return _build_trade(
                context.symbol,
                MeanReversionDirection.SHORT,
                current.close,
                atr_value,
                atr_stop_mult,
                target_r,
                "SHORT_ATR_MEAN_REVERSION",
                metadata,
            )
        return MeanReversionEvaluation.reject(context.symbol, MeanReversionRejection.NO_MEAN_REVERSION_SETUP, metadata)


def _build_trade(
    symbol: str,
    direction: MeanReversionDirection,
    entry: float,
    atr_value: float,
    atr_stop_mult: float,
    target_r: float,
    reason: str,
    metadata: dict[str, Any],
) -> MeanReversionEvaluation:
    risk = atr_value * atr_stop_mult
    if risk <= 0:
        return MeanReversionEvaluation.reject(symbol, MeanReversionRejection.INVALID_RISK, metadata)
    if direction == MeanReversionDirection.LONG:
        stop_loss = entry - risk
        target_price = entry + (risk * target_r)
    else:
        stop_loss = entry + risk
        target_price = entry - (risk * target_r)
    return MeanReversionEvaluation(
        symbol=symbol,
        should_trade=True,
        direction=direction,
        reason=reason,
        entry_price=entry,
        stop_loss=stop_loss,
        target_price=target_price,
        metadata=metadata,
    )


def _symbol_config(config: dict[str, Any], symbol: str) -> dict[str, Any]:
    return dict(config.get("symbols", {}).get(symbol, {}))


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


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    if average_loss == 0:
        return 100.0
    relative_strength = average_gain / average_loss
    return 100 - (100 / (1 + relative_strength))
