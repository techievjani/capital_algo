from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path


class SqliteSchemaTests(unittest.TestCase):
    def test_market_data_schema_executes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schema = root / "src" / "capital_algo" / "data" / "sqlite_schema.sql"

        connection = sqlite3.connect(":memory:")
        connection.executescript(schema.read_text(encoding="utf-8"))

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        self.assertIn("candles", tables)
        self.assertIn("fetch_log", tables)


if __name__ == "__main__":
    unittest.main()

