from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from capital_algo.models import Candle


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class RejectionReason(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    LOW_ADX = "LOW_ADX"
    VWAP_CHOP = "VWAP_CHOP"
    SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
    NEWS_BLACKOUT = "NEWS_BLACKOUT"
    NO_TREND_BIAS = "NO_TREND_BIAS"
    FLAT_OR_WRONG_EMA_SLOPE = "FLAT_OR_WRONG_EMA_SLOPE"
    PRICE_NOT_ABOVE_VWAP = "PRICE_NOT_ABOVE_VWAP"
    PRICE_NOT_BELOW_VWAP = "PRICE_NOT_BELOW_VWAP"
    NO_VALID_IMPULSE = "NO_VALID_IMPULSE"
    NO_VALID_PULLBACK = "NO_VALID_PULLBACK"
    PULLBACK_BROKE_SWING = "PULLBACK_BROKE_SWING"
    POOR_CANDLE_QUALITY = "POOR_CANDLE_QUALITY"
    ENTRY_TRIGGER_NOT_CONFIRMED = "ENTRY_TRIGGER_NOT_CONFIRMED"
    RISK_REWARD_INVALID = "RISK_REWARD_INVALID"


@dataclass(frozen=True)
class NewsEvent:
    timestamp_utc: datetime
    impact: str
    symbol: str | None = None
    currency: str | None = None
    title: str = ""


@dataclass(frozen=True)
class ForexPullbackContext:
    symbol: str
    current_time: datetime
    candles_1m: list[Candle]
    candles_5m: list[Candle]
    candles_15m: list[Candle]
    current_spread: float | None
    config: dict[str, Any]
    news_events: list[NewsEvent] = field(default_factory=list)


@dataclass(frozen=True)
class StrategyEvaluation:
    should_trade: bool
    symbol: str
    direction: TradeDirection | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    target_price: float | None = None
    risk_pips: float | None = None
    target_r: float | None = None
    reason: str | None = None
    rejection_reason: RejectionReason | None = None
    details: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def reject(
        cls,
        symbol: str,
        reason: RejectionReason,
        details: str,
        metadata: dict[str, Any] | None = None,
    ) -> "StrategyEvaluation":
        return cls(
            should_trade=False,
            symbol=symbol,
            rejection_reason=reason,
            details=details,
            metadata=metadata or {},
        )

