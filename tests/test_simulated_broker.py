from __future__ import annotations

import unittest

from capital_algo.broker.simulated import SimulatedBroker
from capital_algo.models import OrderRequest, OrderType, TradeAction


class SimulatedBrokerTests(unittest.TestCase):
    def test_trailing_stop_can_be_enabled_by_symbol(self) -> None:
        broker = SimulatedBroker(
            10000,
            execution_config={
                "trailing_stop": {
                    "enabled": False,
                    "symbols": {
                        "BTCUSD": {"enabled": True, "activation_r": 0.5, "distance_r": 0.5},
                        "GOLD": {"enabled": False},
                    },
                }
            },
        )
        broker.submit_order_at_price(
            OrderRequest("BTCUSD", TradeAction.BUY, OrderType.MARKET, 1.0, stop_loss=99.0),
            100.0,
            "2026-05-17T10:00:00+00:00",
        )
        broker.submit_order_at_price(
            OrderRequest("GOLD", TradeAction.BUY, OrderType.MARKET, 1.0, stop_loss=99.0),
            100.0,
            "2026-05-17T10:00:00+00:00",
        )
        self.assertTrue(broker.open_trades[0].trailing_enabled)
        self.assertFalse(broker.open_trades[1].trailing_enabled)


if __name__ == "__main__":
    unittest.main()
