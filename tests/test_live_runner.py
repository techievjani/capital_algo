from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from capital_algo.live.runner import _aggregate, _latest_closed_minute, _risk_config_for_symbol
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


if __name__ == "__main__":
    unittest.main()
