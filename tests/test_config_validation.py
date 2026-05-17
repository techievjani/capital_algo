from __future__ import annotations

import unittest
from pathlib import Path

from capital_algo.config.validation import validate_project_config
from capital_algo.models import OrderStatus, OrderType, TradeAction


class ConfigValidationTests(unittest.TestCase):
    def test_example_config_is_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]

        result = validate_project_config(root)

        self.assertEqual([], result.errors)

    def test_internal_enums_are_importable(self) -> None:
        self.assertEqual("BUY", TradeAction.BUY.value)
        self.assertEqual("MARKET", OrderType.MARKET.value)
        self.assertEqual("PENDING", OrderStatus.PENDING.value)


if __name__ == "__main__":
    unittest.main()
