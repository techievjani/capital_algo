from __future__ import annotations

from dataclasses import dataclass

from capital_algo.strategies.forex_pullback import indicators
from capital_algo.strategies.forex_pullback.models import ForexPullbackContext, RejectionReason, TradeDirection


@dataclass(frozen=True)
class RegimeResult:
    direction: TradeDirection | None
    rejection_reason: RejectionReason | None
    details: str
    metadata: dict


def evaluate_regime(context: ForexPullbackContext, config: dict) -> RegimeResult:
    periods = config["indicators"]
    ema_15 = indicators.ema(context.candles_15m, int(periods["ema_15m"]))
    ema_15_slope = indicators.ema_slope(context.candles_15m, int(periods["ema_15m"]))
    ema_5 = indicators.ema(context.candles_5m, int(periods["ema_5m"]))
    ema_5_slope = indicators.ema_slope(context.candles_5m, int(periods["ema_5m"]))
    vwap_5 = indicators.vwap(context.candles_5m)
    adx_5 = indicators.adx(context.candles_5m, int(periods["adx_period"]))
    latest_15 = context.candles_15m[-1]
    latest_5 = context.candles_5m[-1]
    metadata = {
        "ema_15m_50": ema_15,
        "ema_15m_50_slope": ema_15_slope,
        "ema_5m_20": ema_5,
        "ema_5m_20_slope": ema_5_slope,
        "vwap_5m": vwap_5,
        "adx": adx_5.adx if adx_5 else None,
    }

    if None in (ema_15, ema_15_slope, ema_5, ema_5_slope, vwap_5) or adx_5 is None:
        return RegimeResult(None, RejectionReason.INSUFFICIENT_DATA, "Indicators could not be calculated", metadata)

    adx_min = float(periods.get("adx_min", 20))
    if adx_5.adx < adx_min:
        return RegimeResult(None, RejectionReason.LOW_ADX, f"5m ADX {adx_5.adx:.2f} is below required {adx_min}", metadata)

    slope_epsilon = float(periods.get("slope_epsilon", 1e-12))
    if abs(ema_15_slope) <= slope_epsilon or abs(ema_5_slope) <= slope_epsilon:
        return RegimeResult(None, RejectionReason.FLAT_OR_WRONG_EMA_SLOPE, "EMA slope is flat", metadata)

    ema_15_up = ema_15_slope > slope_epsilon
    ema_15_down = ema_15_slope < -slope_epsilon
    ema_5_up = ema_5_slope > slope_epsilon
    ema_5_down = ema_5_slope < -slope_epsilon
    price_15_above = latest_15.close > ema_15
    price_15_below = latest_15.close < ema_15
    price_5_above = latest_5.close > vwap_5 and latest_5.close > ema_5
    price_5_below = latest_5.close < vwap_5 and latest_5.close < ema_5

    if price_15_above and ema_15_up and price_5_below and ema_5_down:
        return RegimeResult(None, RejectionReason.NO_TREND_BIAS, "15m and 5m states conflict", metadata)
    if price_15_below and ema_15_down and price_5_above and ema_5_up:
        return RegimeResult(None, RejectionReason.NO_TREND_BIAS, "15m and 5m states conflict", metadata)

    long_price = price_15_above and price_5_above
    short_price = price_15_below and price_5_below
    long_slope = ema_15_up and ema_5_up
    short_slope = ema_15_down and ema_5_down

    if long_price and short_price:
        return RegimeResult(None, RejectionReason.NO_TREND_BIAS, "Conflicting long and short price state", metadata)
    if long_price and not long_slope:
        return RegimeResult(None, RejectionReason.FLAT_OR_WRONG_EMA_SLOPE, "Long price state but EMA slope is not upward", metadata)
    if short_price and not short_slope:
        return RegimeResult(None, RejectionReason.FLAT_OR_WRONG_EMA_SLOPE, "Short price state but EMA slope is not downward", metadata)
    if long_price and long_slope:
        return RegimeResult(TradeDirection.LONG, None, "Long trend bias active", metadata)
    if short_price and short_slope:
        return RegimeResult(TradeDirection.SHORT, None, "Short trend bias active", metadata)
    if latest_5.close <= vwap_5 and latest_15.close > ema_15:
        return RegimeResult(None, RejectionReason.PRICE_NOT_ABOVE_VWAP, "5m close is not above VWAP", metadata)
    if latest_5.close >= vwap_5 and latest_15.close < ema_15:
        return RegimeResult(None, RejectionReason.PRICE_NOT_BELOW_VWAP, "5m close is not below VWAP", metadata)
    return RegimeResult(None, RejectionReason.NO_TREND_BIAS, "No valid trend bias", metadata)
