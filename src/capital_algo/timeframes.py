from __future__ import annotations

from datetime import timedelta


TIMEFRAME_SECONDS = {
    "MINUTE": 60,
    "MINUTE_5": 300,
    "MINUTE_15": 900,
    "MINUTE_30": 1800,
    "HOUR": 3600,
    "HOUR_4": 14400,
    "DAY": 86400,
    "WEEK": 604800,
}


def timeframe_delta(timeframe: str) -> timedelta:
    try:
        return timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc

