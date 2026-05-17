from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    enabled: bool
    session: str
    broker_mappings: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class Candle:
    provider: str
    instrument: str
    timeframe: str
    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Tick:
    provider: str
    instrument: str
    timestamp_utc: datetime
    bid: float | None
    ask: float | None
    last: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    instrument: str
    action: TradeAction
    entry_type: OrderType
    reason: str
    stop_loss: float | None = None
    take_profit: float | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderRequest:
    instrument: str
    action: TradeAction
    order_type: OrderType
    size: float
    stop_loss: float | None = None
    take_profit: float | None = None
    limit_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    status: OrderStatus
    broker_order_id: str | None = None
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Position:
    instrument: str
    size: float
    average_price: float
    unrealized_pnl: float = 0.0
    broker_position_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountSnapshot:
    account_id: str
    currency: str
    balance: float
    equity: float
    available_funds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
