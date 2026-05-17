from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from capital_algo.data.sqlite_cache import SQLiteMarketDataCache
from capital_algo.models import Candle


class SQLiteCacheTests(unittest.TestCase):
    def test_upsert_and_missing_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = SQLiteMarketDataCache(Path(tmp) / "market.sqlite")
            cache.initialize()
            start = datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc)
            end = datetime(2026, 1, 1, 13, 32, tzinfo=timezone.utc)
            candles = [
                Candle("capital", "US100", "MINUTE", start, 1, 2, 0.5, 1.5),
                Candle("capital", "US100", "MINUTE", end, 1.5, 2.5, 1, 2),
            ]

            self.assertEqual(2, cache.upsert_candles(candles))
            cache.record_fetch("capital", "US100", "MINUTE", start, end, "success", 2)

            loaded = cache.get_candles("capital", "US100", "MINUTE", start, end)
            missing = cache.missing_ranges("capital", "US100", "MINUTE", start, end)

            self.assertEqual(2, len(loaded))
            self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()

