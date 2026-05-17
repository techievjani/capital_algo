from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from capital_algo.models import Candle


CSV_FIELDS = [
    "provider",
    "instrument",
    "timeframe",
    "timestamp_utc",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


def export_candles(path: Path, candles: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for candle in candles:
            writer.writerow(
                {
                    "provider": candle.provider,
                    "instrument": candle.instrument,
                    "timeframe": candle.timeframe,
                    "timestamp_utc": _format_utc(candle.timestamp_utc),
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "volume": "" if candle.volume is None else candle.volume,
                }
            )


def import_candles(path: Path) -> list[Candle]:
    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [
            Candle(
                provider=row["provider"],
                instrument=row["instrument"],
                timeframe=row["timeframe"],
                timestamp_utc=_parse_utc(row["timestamp_utc"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]) if row.get("volume") else None,
            )
            for row in reader
        ]


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

