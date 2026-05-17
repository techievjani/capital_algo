from __future__ import annotations

from dataclasses import dataclass

from capital_algo.models import Candle


@dataclass(frozen=True)
class ADXResult:
    adx: float
    plus_di: float
    minus_di: float


def ema_values(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    alpha = 2 / (period + 1)
    ema = sum(values[:period]) / period
    result = [ema]
    for value in values[period:]:
        ema = (value * alpha) + (ema * (1 - alpha))
        result.append(ema)
    return result


def ema(candles: list[Candle], period: int) -> float | None:
    values = ema_values([candle.close for candle in candles], period)
    return values[-1] if values else None


def ema_slope(candles: list[Candle], period: int, lookback: int = 3) -> float | None:
    values = ema_values([candle.close for candle in candles], period)
    if len(values) <= lookback:
        return None
    return values[-1] - values[-1 - lookback]


def vwap(candles: list[Candle]) -> float | None:
    cumulative_pv = 0.0
    cumulative_volume = 0.0
    for candle in candles:
        volume = candle.volume or 1.0
        typical = (candle.high + candle.low + candle.close) / 3
        cumulative_pv += typical * volume
        cumulative_volume += volume
    if cumulative_volume <= 0:
        return None
    return cumulative_pv / cumulative_volume


def adx(candles: list[Candle], period: int = 14) -> ADXResult | None:
    if len(candles) < period + 2:
        return None

    trs: list[float] = []
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    for previous, current in zip(candles[:-1], candles[1:]):
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        trs.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    recent_tr = trs[-period:]
    tr_sum = sum(recent_tr)
    if tr_sum <= 0:
        return None
    plus_di = 100 * (sum(plus_dm[-period:]) / tr_sum)
    minus_di = 100 * (sum(minus_dm[-period:]) / tr_sum)
    denominator = plus_di + minus_di
    if denominator <= 0:
        return ADXResult(adx=0.0, plus_di=plus_di, minus_di=minus_di)
    dx = 100 * abs(plus_di - minus_di) / denominator
    return ADXResult(adx=dx, plus_di=plus_di, minus_di=minus_di)


def recent_swing_low(candles: list[Candle], lookback: int) -> float | None:
    if len(candles) < lookback:
        return None
    return min(candle.low for candle in candles[-lookback:])


def recent_swing_high(candles: list[Candle], lookback: int) -> float | None:
    if len(candles) < lookback:
        return None
    return max(candle.high for candle in candles[-lookback:])


def vwap_cross_count(candles: list[Candle], lookback: int) -> int | None:
    if len(candles) < lookback:
        return None
    recent = candles[-lookback:]
    crosses = 0
    previous_side: int | None = None
    for index in range(1, len(recent) + 1):
        current_vwap = vwap(recent[:index])
        if current_vwap is None:
            return None
        close = recent[index - 1].close
        side = 1 if close > current_vwap else -1 if close < current_vwap else 0
        if side and previous_side and side != previous_side:
            crosses += 1
        if side:
            previous_side = side
    return crosses

