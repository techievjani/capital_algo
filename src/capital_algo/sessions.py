from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TradingSession:
    name: str
    timezone: str
    open: time
    close: time

    def local_time(self, timestamp_utc: datetime) -> time:
        return timestamp_utc.astimezone(ZoneInfo(self.timezone)).time()

    def trading_day(self, timestamp_utc: datetime) -> str:
        return timestamp_utc.astimezone(ZoneInfo(self.timezone)).date().isoformat()

    def contains(self, timestamp_utc: datetime) -> bool:
        current = self.local_time(timestamp_utc)
        return self.open <= current <= self.close

    @classmethod
    def from_strings(cls, name: str, timezone: str, open_time: str, close_time: str) -> "TradingSession":
        return cls(name=name, timezone=timezone, open=_parse_time(open_time), close=_parse_time(close_time))


def load_sessions(config: dict) -> dict[str, TradingSession]:
    sessions = {}
    for name, raw in config.get("sessions", {}).items():
        sessions[name] = TradingSession.from_strings(name, raw["timezone"], raw["open"], raw["close"])
    return sessions


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))
