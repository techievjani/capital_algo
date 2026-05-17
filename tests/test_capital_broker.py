from __future__ import annotations

import unittest

from capital_algo.broker.capital import CapitalBroker
from capital_algo.models import OrderRequest, OrderStatus, TradeAction


class FakeCapitalClient:
    def __init__(self) -> None:
        self.created = []

    def connect(self) -> None:
        return None

    def get_account_snapshot(self):
        raise NotImplementedError

    def get_positions(self):
        return {
            "positions": [
                {
                    "market": {"epic": "GBPJPY"},
                    "position": {
                        "dealId": "D1",
                        "direction": "BUY",
                        "size": 2,
                        "level": 190.0,
                        "upl": 12.5,
                    },
                }
            ]
        }

    def create_position(self, **kwargs):
        self.created.append(kwargs)
        return {"dealReference": "o_123"}

    def confirm(self, deal_reference):
        return {"dealId": "WORKING_ORDER_D123", "affectedDeals": [{"dealId": "D123"}]}

    def close_position(self, deal_id):
        return {"dealReference": "c_123"}


class CapitalBrokerTests(unittest.TestCase):
    def test_submit_order_is_blocked_when_disabled(self) -> None:
        broker = CapitalBroker(FakeCapitalClient(), {"GBPJPY": "GBPJPY"}, enable_order_placement=False)
        result = broker.submit_order(OrderRequest("GBPJPY", TradeAction.BUY, "MARKET", 1.0))
        self.assertEqual(OrderStatus.REJECTED, result.status)

    def test_submit_order_uses_capital_position_payload(self) -> None:
        client = FakeCapitalClient()
        broker = CapitalBroker(client, {"GBPJPY": "GBPJPY"}, enable_order_placement=True)
        result = broker.submit_order(
            OrderRequest(
                instrument="GBPJPY",
                action=TradeAction.BUY,
                order_type="MARKET",
                size=1.5,
                stop_loss=189.5,
                take_profit=191.0,
            )
        )
        self.assertEqual(OrderStatus.FILLED, result.status)
        self.assertEqual("D123", result.broker_order_id)
        self.assertEqual(
            {
                "epic": "GBPJPY",
                "direction": "BUY",
                "size": 1.5,
                "stop_level": 189.5,
                "profit_level": 191.0,
            },
            {key: client.created[0][key] for key in ["epic", "direction", "size", "stop_level", "profit_level"]},
        )

    def test_get_open_positions_maps_epic_to_symbol(self) -> None:
        broker = CapitalBroker(FakeCapitalClient(), {"GBPJPY": "GBPJPY"}, enable_order_placement=True)
        positions = broker.get_open_positions()
        self.assertEqual(1, len(positions))
        self.assertEqual("GBPJPY", positions[0].instrument)
        self.assertEqual(2, positions[0].size)

    def test_submit_order_can_request_trailing_stop_distance(self) -> None:
        client = FakeCapitalClient()
        broker = CapitalBroker(
            client,
            {"GBPJPY": "GBPJPY"},
            enable_order_placement=True,
            trailing_stop_config={"enabled": True},
        )
        broker.submit_order(
            OrderRequest(
                instrument="GBPJPY",
                action=TradeAction.SELL,
                order_type="MARKET",
                size=1.0,
                stop_loss=191.0,
                take_profit=189.0,
                metadata={"entry_price": 190.0},
            )
        )
        self.assertTrue(client.created[0]["trailing_stop"])
        self.assertEqual(1.0, client.created[0]["stop_distance"])
        self.assertIsNone(client.created[0]["stop_level"])


if __name__ == "__main__":
    unittest.main()
