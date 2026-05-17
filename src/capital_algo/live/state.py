from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LiveState:
    last_processed_candle: dict[str, str] = field(default_factory=dict)
    last_signal_candle: dict[str, str] = field(default_factory=dict)
    daily_trade_counts: dict[str, int] = field(default_factory=dict)
    open_positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    order_events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "LiveState":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            last_processed_candle=dict(data.get("last_processed_candle", {})),
            last_signal_candle=dict(data.get("last_signal_candle", {})),
            daily_trade_counts=dict(data.get("daily_trade_counts", {})),
            open_positions=dict(data.get("open_positions", {})),
            pending_orders=dict(data.get("pending_orders", {})),
            order_events=list(data.get("order_events", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True), encoding="utf-8")

    def trade_count_key(self, symbol: str, day: str) -> str:
        return f"{symbol}:{day}"

    def global_trade_count_key(self, day: str) -> str:
        return f"GLOBAL:{day}"

    def append_order_event(self, event: dict[str, Any], max_events: int = 500) -> None:
        self.order_events.append(event)
        if len(self.order_events) > max_events:
            self.order_events = self.order_events[-max_events:]
