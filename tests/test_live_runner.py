from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from capital_algo.live.runner import (
    _aggregate,
    _ensure_csv_header,
    _latest_closed_minute,
    _realized_close_fields,
    _risk_config_for_symbol,
)
from capital_algo.live.state import LiveState
from capital_algo.models import Candle


class LiveRunnerTests(unittest.TestCase):
    def test_latest_closed_minute_steps_back_from_current_minute(self) -> None:
        value = datetime(2026, 5, 17, 7, 10, 42, tzinfo=timezone.utc)
        self.assertEqual(datetime(2026, 5, 17, 7, 9, tzinfo=timezone.utc), _latest_closed_minute(value))

    def test_aggregate_builds_complete_five_minute_candle_only(self) -> None:
        base = datetime(2026, 5, 17, 7, 0, tzinfo=timezone.utc)
        candles = [
            Candle("test", "EURUSD", "MINUTE", base + timedelta(minutes=index), 1.0, 1.2 + index, 0.9, 1.1 + index, 1)
            for index in range(7)
        ]
        aggregated = _aggregate(candles, 5, "MINUTE_5")
        self.assertEqual(1, len(aggregated))
        self.assertEqual(base, aggregated[0].timestamp_utc)
        self.assertEqual(1.0, aggregated[0].open)
        self.assertEqual(5.1, aggregated[0].close)

    def test_live_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            state = LiveState(
                last_processed_candle={"EURUSD": "2026-05-17T07:00:00+00:00"},
                open_positions={"D1": {"symbol": "EURUSD", "size": 1}},
                pending_orders={"EURUSD:1": {"symbol": "EURUSD"}},
            )
            state.append_order_event({"event": "filled", "symbol": "EURUSD"})
            state.save(path)
            loaded = LiveState.load(path)
            self.assertEqual(state.last_processed_candle, loaded.last_processed_candle)
            self.assertEqual(state.open_positions, loaded.open_positions)
            self.assertEqual(state.pending_orders, loaded.pending_orders)
            self.assertEqual(state.order_events, loaded.order_events)

    def test_risk_config_for_symbol_applies_fixed_sizes(self) -> None:
        risk = {"account_risk_per_trade_pct": 0.5, "max_trades_per_day": 3}
        group = {
            "strategy_config": {
                "fixed_position_sizes": {"EURUSD": 35000},
                "symbols": {"BTCUSD": {"fixed_position_size": 0.5, "max_trades_per_day": 2}},
            }
        }
        fx_config = _risk_config_for_symbol(risk, group, "EURUSD")
        self.assertEqual("fixed", fx_config["position_sizing_mode"])
        self.assertEqual(35000, fx_config["fixed_position_size"])
        btc_config = _risk_config_for_symbol(risk, group, "BTCUSD")
        self.assertEqual(0.5, btc_config["fixed_position_size"])
        self.assertEqual(2, btc_config["max_trades_per_day"])

    def test_risk_config_for_symbol_applies_notional_cap(self) -> None:
        risk = {"account_risk_per_trade_pct": 0.5, "max_trades_per_day": 3, "max_position_notional_pct": 45.0}
        group = {"strategy_config": {"symbols": {"BTCUSD": {"max_position_notional_pct": 35.0}}}}
        btc_config = _risk_config_for_symbol(risk, group, "BTCUSD")
        self.assertEqual(35.0, btc_config["max_position_notional_pct"])

    def test_ensure_csv_header_adds_new_columns_to_existing_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live.csv"
            with path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["timestamp_utc", "symbol", "event"])
                writer.writerow(["2026-05-17T10:00:00+00:00", "BTCUSD", "submitted"])

            _ensure_csv_header(path, ["timestamp_utc", "symbol", "event", "broker_order_id", "broker_deal_reference"])

            with path.open(newline="", encoding="utf-8") as file:
                rows = list(csv.reader(file))
            self.assertEqual(["timestamp_utc", "symbol", "event", "broker_order_id", "broker_deal_reference"], rows[0])
            self.assertEqual(["2026-05-17T10:00:00+00:00", "BTCUSD", "submitted", "", ""], rows[1])

    def test_realized_close_fields_uses_broker_transaction(self) -> None:
        class Broker:
            def get_recent_close_transaction(self, deal_id):
                self.deal_id = deal_id
                return {
                    "size": "-337.35",
                    "currency": "USDd",
                    "reference": "128014165968950",
                    "dateUtc": "2026-05-17T14:23:52.276",
                }

        broker = Broker()
        fields = _realized_close_fields(broker, {"broker_position_id": "D1"})
        self.assertEqual("D1", broker.deal_id)
        self.assertEqual(-337.35, fields["realized_pnl"])
        self.assertEqual("USDd", fields["realized_currency"])
        self.assertEqual("128014165968950", fields["close_transaction_reference"])


if __name__ == "__main__":
    unittest.main()
