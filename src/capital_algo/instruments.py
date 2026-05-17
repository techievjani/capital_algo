from __future__ import annotations

from typing import Any

from capital_algo.models import Instrument


def load_instruments(config: dict[str, Any]) -> dict[str, Instrument]:
    instruments: dict[str, Instrument] = {}
    for raw in config.get("instruments", []):
        instrument = Instrument(
            symbol=raw["symbol"],
            enabled=bool(raw.get("enabled", True)),
            session=raw["session"],
            broker_mappings=raw.get("brokers", {}),
        )
        instruments[instrument.symbol] = instrument
    return instruments


def broker_mapping(instrument: Instrument, broker: str) -> dict[str, Any]:
    mapping = instrument.broker_mappings.get(broker)
    if not mapping:
        raise ValueError(f"No broker mapping for {instrument.symbol} on {broker}")
    return mapping

