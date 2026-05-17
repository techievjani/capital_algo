from __future__ import annotations

from datetime import datetime

from capital_algo.data.base import DataProvider
from capital_algo.data.sqlite_cache import DateRange, SQLiteMarketDataCache
from capital_algo.models import Candle
from capital_algo.timeframes import timeframe_delta


class HistoricalDataResolver:
    def __init__(
        self,
        cache: SQLiteMarketDataCache,
        fallback_provider: DataProvider | None,
        provider_name: str,
        fetch_policy: str,
        allow_api_fetch_for_missing_data: bool,
        max_points_per_request: int = 1000,
    ) -> None:
        self.cache = cache
        self.fallback_provider = fallback_provider
        self.provider_name = provider_name
        self.fetch_policy = fetch_policy
        self.allow_api_fetch_for_missing_data = allow_api_fetch_for_missing_data
        self.max_points_per_request = max_points_per_request

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        self.cache.initialize()
        if self.fetch_policy == "refresh":
            missing = [DateRange(start_utc, end_utc)]
        else:
            missing = self.cache.missing_ranges(self.provider_name, symbol, timeframe, start_utc, end_utc)

        if missing:
            if self.fetch_policy == "cache_only" or not self.allow_api_fetch_for_missing_data:
                ranges = ", ".join(f"{item.start_utc.isoformat()} -> {item.end_utc.isoformat()}" for item in missing)
                raise RuntimeError(f"Missing cached data for {symbol} {timeframe}: {ranges}")
            if self.fallback_provider is None:
                raise RuntimeError("Missing cached data and no fallback provider is configured")
            self._fetch_missing(symbol, timeframe, missing)

        candles = self.cache.get_candles(self.provider_name, symbol, timeframe, start_utc, end_utc)
        if not candles:
            raise RuntimeError(f"No candles available for {symbol} {timeframe}")
        return candles

    def _fetch_missing(self, symbol: str, timeframe: str, missing: list[DateRange]) -> None:
        step = timeframe_delta(timeframe) * self.max_points_per_request
        for date_range in missing:
            cursor = date_range.start_utc
            while cursor < date_range.end_utc:
                chunk_end = min(cursor + step, date_range.end_utc)
                print(
                    f"Fetching {symbol} {timeframe}: {cursor.isoformat()} -> {chunk_end.isoformat()}",
                    flush=True,
                )
                candles = self.fallback_provider.get_historical_candles(symbol, timeframe, cursor, chunk_end)
                self.cache.upsert_candles(candles)
                self.cache.record_fetch(
                    self.provider_name,
                    symbol,
                    timeframe,
                    cursor,
                    chunk_end,
                    "success",
                    len(candles),
                )
                cursor = chunk_end
