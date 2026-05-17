from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from capital_algo.models import Candle


@dataclass(frozen=True)
class DateRange:
    start_utc: datetime
    end_utc: datetime


class SQLiteMarketDataCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_path = Path(__file__).with_name("sqlite_schema.sql")

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(self._schema_path.read_text(encoding="utf-8"))

    def upsert_candles(self, candles: list[Candle], fetched_at: datetime | None = None) -> int:
        if not candles:
            return 0
        fetched_at = fetched_at or datetime.now(timezone.utc)
        rows = [
            (
                candle.provider,
                candle.instrument,
                candle.timeframe,
                _format_utc(candle.timestamp_utc),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                _format_utc(fetched_at),
                json.dumps(candle.metadata, sort_keys=True) if candle.metadata else None,
            )
            for candle in candles
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO candles (
                    provider, instrument, timeframe, timestamp_utc,
                    open, high, low, close, volume, source_fetched_at, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, instrument, timeframe, timestamp_utc)
                DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    source_fetched_at = excluded.source_fetched_at,
                    metadata_json = excluded.metadata_json
                """,
                rows,
            )
        return len(rows)

    def get_candles(
        self,
        provider: str,
        instrument: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT provider, instrument, timeframe, timestamp_utc, open, high, low, close, volume, metadata_json
                FROM candles
                WHERE provider = ?
                  AND instrument = ?
                  AND timeframe = ?
                  AND timestamp_utc >= ?
                  AND timestamp_utc <= ?
                ORDER BY timestamp_utc ASC
                """,
                (provider, instrument, timeframe, _format_utc(start_utc), _format_utc(end_utc)),
            ).fetchall()

        return [
            Candle(
                provider=row["provider"],
                instrument=row["instrument"],
                timeframe=row["timeframe"],
                timestamp_utc=_parse_utc(row["timestamp_utc"]),
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            )
            for row in rows
        ]

    def record_fetch(
        self,
        provider: str,
        instrument: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
        status: str,
        candle_count: int,
        notes: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO fetch_log (
                    provider, instrument, timeframe, from_utc, to_utc,
                    fetched_at, status, candle_count, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    instrument,
                    timeframe,
                    _format_utc(start_utc),
                    _format_utc(end_utc),
                    _format_utc(datetime.now(timezone.utc)),
                    status,
                    candle_count,
                    notes,
                ),
            )

    def covered_ranges(
        self,
        provider: str,
        instrument: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[DateRange]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT from_utc, to_utc
                FROM fetch_log
                WHERE provider = ?
                  AND instrument = ?
                  AND timeframe = ?
                  AND status = 'success'
                  AND to_utc >= ?
                  AND from_utc <= ?
                ORDER BY from_utc ASC
                """,
                (provider, instrument, timeframe, _format_utc(start_utc), _format_utc(end_utc)),
            ).fetchall()

        ranges = [
            DateRange(
                start_utc=max(_parse_utc(row["from_utc"]), _ensure_utc(start_utc)),
                end_utc=min(_parse_utc(row["to_utc"]), _ensure_utc(end_utc)),
            )
            for row in rows
        ]
        return _merge_ranges(ranges)

    def missing_ranges(
        self,
        provider: str,
        instrument: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[DateRange]:
        start_utc = _ensure_utc(start_utc)
        end_utc = _ensure_utc(end_utc)
        covered = self.covered_ranges(provider, instrument, timeframe, start_utc, end_utc)
        missing: list[DateRange] = []
        cursor = start_utc
        for current in covered:
            if current.start_utc > cursor:
                missing.append(DateRange(cursor, current.start_utc))
            if current.end_utc > cursor:
                cursor = current.end_utc
        if cursor < end_utc:
            missing.append(DateRange(cursor, end_utc))
        return missing

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _merge_ranges(ranges: list[DateRange]) -> list[DateRange]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: item.start_utc)
    merged = [ordered[0]]
    for current in ordered[1:]:
        previous = merged[-1]
        if current.start_utc <= previous.end_utc:
            merged[-1] = DateRange(previous.start_utc, max(previous.end_utc, current.end_utc))
        else:
            merged.append(current)
    return merged


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return _ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

