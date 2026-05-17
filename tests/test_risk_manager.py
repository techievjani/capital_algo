from __future__ import annotations

import unittest

from capital_algo.models import AccountSnapshot, OrderType, Signal, TradeAction
from capital_algo.risk.manager import RiskManager


class RiskManagerTests(unittest.TestCase):
    def test_dynamic_position_size_is_capped_by_notional_percent(self) -> None:
        manager = RiskManager(
            {
                "account_risk_per_trade_pct": 10.0,
                "max_position_notional_pct": 45.0,
                "max_trades_per_day": 3,
            }
        )
        decision = manager.evaluate(
            Signal(
                strategy_id="test",
                instrument="BTCUSD",
                action=TradeAction.BUY,
                entry_type=OrderType.MARKET,
                reason="TEST",
                stop_loss=990.0,
            ),
            AccountSnapshot("A1", "USDd", balance=20000.0, equity=20000.0, available_funds=20000.0),
            entry_price=1000.0,
            trading_day="2026-05-17",
        )
        self.assertTrue(decision.approved)
        self.assertIsNotNone(decision.order)
        self.assertEqual(9.0, decision.order.size)
        self.assertTrue(decision.metadata["position_size_capped"])
        self.assertEqual(9000.0, decision.metadata["max_position_notional"])


if __name__ == "__main__":
    unittest.main()
