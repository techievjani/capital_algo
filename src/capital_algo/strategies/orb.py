from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any

from capital_algo.models import Candle, OrderType, Signal, TradeAction
from capital_algo.sessions import TradingSession
from capital_algo.strategies.base import Strategy


@dataclass
class ORBSessionState:
    trading_day: str
    bars_seen: int = 0
    range_high: float | None = None
    range_low: float | None = None
    range_complete: bool = False
    range_too_wide: bool = False
    trades_emitted: int = 0
    ema: float | None = None
    previous_close: float | None = None
    true_ranges: list[float] = field(default_factory=list)
    cumulative_pv: float = 0.0
    cumulative_volume: float = 0.0

    @property
    def vwap(self) -> float | None:
        if self.cumulative_volume <= 0:
            return None
        return self.cumulative_pv / self.cumulative_volume

    @property
    def atr(self) -> float | None:
        if not self.true_ranges:
            return None
        return sum(self.true_ranges) / len(self.true_ranges)


class ORBStrategy(Strategy):
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.state_by_symbol: dict[str, ORBSessionState] = {}

    def initialize(self, strategy_config: dict[str, Any], context: dict[str, Any]) -> None:
        self.config = strategy_config

    def on_bar(self, bar: Candle, context: dict[str, Any]) -> list[Signal]:
        session: TradingSession = context["session"]
        if not session.contains(bar.timestamp_utc):
            return []

        trading_day = session.trading_day(bar.timestamp_utc)
        state = self.state_by_symbol.get(bar.instrument)
        if state is None or state.trading_day != trading_day:
            state = ORBSessionState(trading_day=trading_day)
            self.state_by_symbol[bar.instrument] = state

        self._update_indicators(state, bar)

        opening_range_minutes = int(self.config["opening_range_minutes"])
        timeframe_minutes = float(context.get("timeframe_minutes", 1.0))
        required_bars = max(1, ceil(opening_range_minutes / timeframe_minutes))
        max_trades = int(self.config.get("max_trades_per_session", 1))

        if not state.range_complete:
            state.bars_seen += 1
            state.range_high = bar.high if state.range_high is None else max(state.range_high, bar.high)
            state.range_low = bar.low if state.range_low is None else min(state.range_low, bar.low)
            state.range_complete = state.bars_seen >= required_bars
            if state.range_complete:
                state.range_too_wide = self._range_too_wide(bar.instrument, state)
            return []

        if state.range_too_wide or state.trades_emitted >= max_trades:
            return []

        direction = self.config.get("trade_direction", "both")
        buffer_points = float(self.config.get("entry_buffer_points", 0.0))
        signals: list[Signal] = []
        if (
            direction in {"long", "both"}
            and state.range_high is not None
            and bar.close > state.range_high + buffer_points
            and self._trend_filter_ok(bar, state, TradeAction.BUY)
            and self._spread_filter_ok(bar)
        ):
            signals.append(self._signal(bar, TradeAction.BUY, "breakout_above_opening_range", state))
        elif (
            direction in {"short", "both"}
            and state.range_low is not None
            and bar.close < state.range_low - buffer_points
            and self._trend_filter_ok(bar, state, TradeAction.SELL)
            and self._spread_filter_ok(bar)
        ):
            signals.append(self._signal(bar, TradeAction.SELL, "breakout_below_opening_range", state))

        state.trades_emitted += len(signals)
        return signals

    def _update_indicators(self, state: ORBSessionState, bar: Candle) -> None:
        ema_period = int(self.config.get("ema_period", 20))
        alpha = 2 / (ema_period + 1)
        state.ema = bar.close if state.ema is None else (bar.close * alpha) + (state.ema * (1 - alpha))

        volume = bar.volume or 0.0
        if volume > 0:
            typical_price = (bar.high + bar.low + bar.close) / 3
            state.cumulative_pv += typical_price * volume
            state.cumulative_volume += volume

        true_range = bar.high - bar.low
        if state.previous_close is not None:
            true_range = max(true_range, abs(bar.high - state.previous_close), abs(bar.low - state.previous_close))
        state.previous_close = bar.close
        state.true_ranges.append(true_range)
        atr_period = int(self.config.get("atr_period", 14))
        if len(state.true_ranges) > atr_period:
            state.true_ranges = state.true_ranges[-atr_period:]

    def _trend_filter_ok(self, bar: Candle, state: ORBSessionState, action: TradeAction) -> bool:
        use_vwap = bool(self.config.get("use_vwap_filter", True))
        use_ema = bool(self.config.get("use_ema_filter", True))
        comparisons: list[bool] = []
        if use_vwap and state.vwap is not None:
            comparisons.append(bar.close > state.vwap if action == TradeAction.BUY else bar.close < state.vwap)
        if use_ema and state.ema is not None:
            comparisons.append(bar.close > state.ema if action == TradeAction.BUY else bar.close < state.ema)
        if not comparisons:
            return bool(self.config.get("allow_missing_trend_filter", True))
        return any(comparisons)

    def _spread_filter_ok(self, bar: Candle) -> bool:
        max_spread = self._max_spread_for_symbol(bar.instrument)
        if max_spread is None:
            return True
        spread = bar.metadata.get("spread_points")
        if spread is None:
            return not bool(self.config.get("require_spread_data", False))
        return float(spread) <= max_spread

    def _range_too_wide(self, symbol: str, state: ORBSessionState) -> bool:
        max_range = self._max_range_for_symbol(symbol)
        if max_range is None or state.range_high is None or state.range_low is None:
            return False
        return (state.range_high - state.range_low) > max_range

    def _max_spread_for_symbol(self, symbol: str) -> float | None:
        by_symbol = self.config.get("max_spread_points_by_symbol", {})
        if isinstance(by_symbol, dict) and symbol in by_symbol:
            return float(by_symbol[symbol])
        value = self.config.get("max_spread_points")
        return float(value) if value is not None else None

    def _max_range_for_symbol(self, symbol: str) -> float | None:
        by_symbol = self.config.get("max_opening_range_points_by_symbol", {})
        if isinstance(by_symbol, dict) and symbol in by_symbol:
            return float(by_symbol[symbol])
        value = self.config.get("max_opening_range_points")
        return float(value) if value is not None else None

    def _signal(
        self,
        bar: Candle,
        action: TradeAction,
        reason: str,
        state: ORBSessionState,
    ) -> Signal:
        stop_loss = self._stop_loss(bar, action, state)
        if action == TradeAction.BUY:
            risk = bar.close - float(stop_loss)
            take_profit = bar.close + risk * float(self.config.get("take_profit_r_multiple", 2.0))
        else:
            risk = float(stop_loss) - bar.close
            take_profit = bar.close - risk * float(self.config.get("take_profit_r_multiple", 2.0))
        return Signal(
            strategy_id=self.config["strategy_id"],
            instrument=bar.instrument,
            action=action,
            entry_type=OrderType.MARKET,
            reason=reason,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata={
                "opening_range_high": state.range_high,
                "opening_range_low": state.range_low,
                "opening_range_width": (state.range_high - state.range_low)
                if state.range_high is not None and state.range_low is not None
                else None,
                "entry_reference": bar.close,
                "ema": state.ema,
                "vwap": state.vwap,
                "atr": state.atr,
                "spread_points": bar.metadata.get("spread_points"),
                "stop_loss_mode": self.config.get("stop_loss_mode", "opposite_range"),
                "take_profit_r_multiple": self.config.get("take_profit_r_multiple", 2.0),
            },
        )

    def _stop_loss(self, bar: Candle, action: TradeAction, state: ORBSessionState) -> float:
        mode = self.config.get("stop_loss_mode", "opposite_range")
        if mode == "atr" and state.atr is not None:
            multiplier = float(self.config.get("atr_stop_multiplier", 1.0))
            distance = state.atr * multiplier
            return bar.close - distance if action == TradeAction.BUY else bar.close + distance
        if action == TradeAction.BUY:
            return float(state.range_low)
        return float(state.range_high)
