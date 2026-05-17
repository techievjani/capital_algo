from __future__ import annotations

import logging

from capital_algo.strategies.forex_pullback.config import merge_config
from capital_algo.strategies.forex_pullback.entry_signal import build_entry
from capital_algo.strategies.forex_pullback.models import ForexPullbackContext, RejectionReason, StrategyEvaluation
from capital_algo.strategies.forex_pullback.news_filter import is_news_blackout
from capital_algo.strategies.forex_pullback.pullback_detector import detect_pullback
from capital_algo.strategies.forex_pullback.regime_filter import evaluate_regime
from capital_algo.strategies.forex_pullback.whipsaw_filter import spread_ok, vwap_chop_ok

logger = logging.getLogger(__name__)


class ForexTrendPullbackScalper:
    def __init__(self, config: dict | None = None) -> None:
        self.config = merge_config(config)
        self._last_signal_key: tuple[str, object] | None = None

    def evaluate(self, context: ForexPullbackContext) -> StrategyEvaluation:
        config = merge_config({**self.config, **(context.config or {})})
        if context.symbol not in config["symbols"]:
            return self._reject(context, RejectionReason.NO_TREND_BIAS, f"Unsupported symbol {context.symbol}")
        if not _has_enough_data(context, config):
            return self._reject(context, RejectionReason.INSUFFICIENT_DATA, "Missing required multi-timeframe candles")
        if not _inside_session(context, config):
            return self._reject(context, RejectionReason.OUTSIDE_SESSION, "Current time is outside configured session")
        if not _inside_entry_hours(context, config):
            return self._reject(context, RejectionReason.OUTSIDE_SESSION, "Current hour is outside configured entry hours")

        news_blocked, news_details = is_news_blackout(context, config)
        if news_blocked:
            return self._reject(context, RejectionReason.NEWS_BLACKOUT, news_details)

        ok, reason, details = spread_ok(context, config)
        if not ok:
            return self._reject(context, reason, details)

        ok, reason, details = vwap_chop_ok(context, config)
        if not ok:
            return self._reject(context, reason, details)

        regime = evaluate_regime(context, config)
        metadata = dict(regime.metadata)
        metadata["spread"] = context.current_spread
        if regime.rejection_reason is not None or regime.direction is None:
            return self._reject(context, regime.rejection_reason or RejectionReason.NO_TREND_BIAS, regime.details, metadata)

        pullback = detect_pullback(context, config, regime.direction)
        if not pullback.valid:
            return self._reject(context, pullback.rejection_reason or RejectionReason.NO_VALID_PULLBACK, pullback.details, metadata)
        metadata.update(pullback.metadata or {})

        signal_key = (context.symbol, context.candles_1m[-1].timestamp_utc)
        if signal_key == self._last_signal_key:
            return self._reject(context, RejectionReason.ENTRY_TRIGGER_NOT_CONFIRMED, "Duplicate signal on same candle", metadata)

        result = build_entry(context, config, regime.direction, pullback, metadata)
        if result.should_trade:
            self._last_signal_key = signal_key
            logger.info("Forex pullback signal generated: %s %s", result.symbol, result.direction)
        else:
            logger.info("Forex pullback rejected: %s %s", result.symbol, result.rejection_reason)
        return result

    def _reject(
        self,
        context: ForexPullbackContext,
        reason: RejectionReason,
        details: str,
        metadata: dict | None = None,
    ) -> StrategyEvaluation:
        logger.info("Forex pullback rejected: %s %s %s", context.symbol, reason.value, details)
        return StrategyEvaluation.reject(context.symbol, reason, details, metadata)


def _has_enough_data(context: ForexPullbackContext, config: dict) -> bool:
    return (
        len(context.candles_15m) >= int(config["indicators"]["ema_15m"]) + 4
        and len(context.candles_5m) >= int(config["indicators"]["adx_period"]) + int(config["indicators"]["ema_5m"]) + 4
        and len(context.candles_1m) >= max(
            int(config["indicators"]["ema_1m_slow"]) + 4,
            int(config["filters"]["vwap_chop_lookback_minutes"]),
            int(config["lookbacks"]["impulse"]) + int(config["lookbacks"]["pullback"]) + 3,
        )
    )


def _inside_session(context: ForexPullbackContext, config: dict) -> bool:
    session = config.get("session", {})
    if not session.get("enabled", False):
        return True
    start = _minutes(session["start"])
    end = _minutes(session["end"])
    current = context.current_time.hour * 60 + context.current_time.minute
    return start <= current <= end if start <= end else current >= start or current <= end


def _inside_entry_hours(context: ForexPullbackContext, config: dict) -> bool:
    hours = config.get("filters", {}).get("entry_hours_utc")
    if not hours:
        return True
    return context.current_time.hour in {int(hour) for hour in hours}


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)
