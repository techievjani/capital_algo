from __future__ import annotations

from capital_algo.strategies.forex_pullback import indicators
from capital_algo.strategies.forex_pullback.config import symbol_value
from capital_algo.strategies.forex_pullback.models import ForexPullbackContext, RejectionReason


def spread_ok(context: ForexPullbackContext, config: dict) -> tuple[bool, RejectionReason | None, str]:
    if context.current_spread is None:
        if config["filters"].get("allow_missing_spread", False):
            return True, None, ""
        return False, RejectionReason.SPREAD_TOO_HIGH, "Spread is missing"
    max_spread = symbol_value(config, "max_spread", context.symbol)
    if context.current_spread > max_spread:
        return False, RejectionReason.SPREAD_TOO_HIGH, f"Spread {context.current_spread} exceeds max {max_spread}"
    return True, None, ""


def vwap_chop_ok(context: ForexPullbackContext, config: dict) -> tuple[bool, RejectionReason | None, str]:
    lookback = int(config["filters"].get("vwap_chop_lookback_minutes", 15))
    max_crosses = int(config["filters"].get("max_vwap_crosses", 3))
    crosses = indicators.vwap_cross_count(context.candles_1m, lookback)
    if crosses is None:
        return False, RejectionReason.INSUFFICIENT_DATA, f"Need {lookback} 1m candles for VWAP chop filter"
    if crosses >= max_crosses:
        return False, RejectionReason.VWAP_CHOP, f"1m close crossed VWAP {crosses} times in last {lookback} candles"
    return True, None, ""

