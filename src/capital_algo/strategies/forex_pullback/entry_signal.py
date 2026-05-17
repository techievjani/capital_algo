from __future__ import annotations

from capital_algo.models import Candle
from capital_algo.strategies.forex_pullback.config import symbol_value
from capital_algo.strategies.forex_pullback.models import ForexPullbackContext, RejectionReason, StrategyEvaluation, TradeDirection
from capital_algo.strategies.forex_pullback.pullback_detector import PullbackResult


def build_entry(
    context: ForexPullbackContext,
    config: dict,
    direction: TradeDirection,
    pullback: PullbackResult,
    metadata: dict,
) -> StrategyEvaluation:
    latest = context.candles_1m[-1]
    quality_ok, quality_details = candle_quality_ok(latest, direction, config)
    if not quality_ok:
        return StrategyEvaluation.reject(context.symbol, RejectionReason.POOR_CANDLE_QUALITY, quality_details, metadata)

    if direction == TradeDirection.LONG:
        if latest.close <= latest.open or pullback.pullback_high is None or latest.close <= pullback.pullback_high:
            return StrategyEvaluation.reject(
                context.symbol,
                RejectionReason.ENTRY_TRIGGER_NOT_CONFIRMED,
                "Long entry candle did not close above pullback high",
                metadata,
            )
    else:
        if latest.close >= latest.open or pullback.pullback_low is None or latest.close >= pullback.pullback_low:
            return StrategyEvaluation.reject(
                context.symbol,
                RejectionReason.ENTRY_TRIGGER_NOT_CONFIRMED,
                "Short entry candle did not close below pullback low",
                metadata,
            )

    return _make_signal(context, config, direction, pullback, metadata)


def candle_quality_ok(candle: Candle, direction: TradeDirection, config: dict) -> tuple[bool, str]:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return False, "Entry candle has no range"
    body = abs(candle.close - candle.open)
    body_percent = (body / candle_range) * 100
    min_body = float(config["candle_quality"]["min_body_percent"])
    if body_percent < min_body:
        return False, f"Body percent {body_percent:.1f} below required {min_body}"

    close_position = ((candle.close - candle.low) / candle_range) * 100
    close_threshold = float(config["candle_quality"]["close_position_percent"])
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    max_wick = float(config["candle_quality"]["max_dominant_wick_percent"])
    if direction == TradeDirection.LONG:
        if close_position < 100 - close_threshold:
            return False, "Long candle did not close in upper part of range"
        if (upper_wick / candle_range) * 100 > max_wick:
            return False, "Upper wick dominates long entry candle"
    else:
        if close_position > close_threshold:
            return False, "Short candle did not close in lower part of range"
        if (lower_wick / candle_range) * 100 > max_wick:
            return False, "Lower wick dominates short entry candle"
    return True, ""


def _make_signal(
    context: ForexPullbackContext,
    config: dict,
    direction: TradeDirection,
    pullback: PullbackResult,
    metadata: dict,
) -> StrategyEvaluation:
    latest = context.candles_1m[-1]
    pip_size = symbol_value(config, "pip_size", context.symbol)
    stop_buffer = symbol_value(config, "stop_buffer_pips", context.symbol) * pip_size
    target_r = float(config.get("target_r", 1.0))
    if direction == TradeDirection.LONG:
        stop_loss = float(pullback.swing_low) - stop_buffer
        risk = latest.close - stop_loss
        target = latest.close + (risk * target_r)
        reason = "LONG_TREND_PULLBACK_CONFIRMED"
    else:
        stop_loss = float(pullback.swing_high) + stop_buffer
        risk = stop_loss - latest.close
        target = latest.close - (risk * target_r)
        reason = "SHORT_TREND_PULLBACK_CONFIRMED"

    if risk <= 0 or target_r <= 0:
        return StrategyEvaluation.reject(context.symbol, RejectionReason.RISK_REWARD_INVALID, "Invalid risk or target", metadata)

    return StrategyEvaluation(
        should_trade=True,
        symbol=context.symbol,
        direction=direction,
        entry_price=latest.close,
        stop_loss=stop_loss,
        target_price=target,
        risk_pips=risk / pip_size,
        target_r=target_r,
        reason=reason,
        metadata=metadata,
    )

