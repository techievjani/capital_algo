from __future__ import annotations

from dataclasses import dataclass

from capital_algo.models import AccountSnapshot, OrderRequest, OrderType, Signal


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    order: OrderRequest | None = None


class RiskManager:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.trades_today = 0
        self.current_day: str | None = None

    def evaluate(
        self,
        signal: Signal,
        account: AccountSnapshot,
        entry_price: float,
        trading_day: str | None = None,
    ) -> RiskDecision:
        if trading_day is not None and trading_day != self.current_day:
            self.current_day = trading_day
            self.trades_today = 0
        if signal.stop_loss is None:
            return RiskDecision(False, "missing_stop_loss")
        if self.trades_today >= int(self.config["max_trades_per_day"]):
            return RiskDecision(False, "max_trades_per_day_reached")

        stop_distance = abs(entry_price - signal.stop_loss)
        if stop_distance <= 0:
            return RiskDecision(False, "invalid_stop_distance")

        if self.config.get("position_sizing_mode") == "fixed":
            fixed_sizes = self.config.get("fixed_position_sizes", {})
            fixed_size = fixed_sizes.get(signal.instrument, self.config.get("fixed_position_size"))
            if fixed_size is None:
                return RiskDecision(False, "missing_fixed_position_size")
            size = float(fixed_size)
        else:
            risk_amount = account.equity * (float(self.config["account_risk_per_trade_pct"]) / 100.0)
            size = risk_amount / stop_distance
        if size <= 0:
            return RiskDecision(False, "invalid_position_size")

        return RiskDecision(
            True,
            "approved",
            OrderRequest(
                instrument=signal.instrument,
                action=signal.action,
                order_type=OrderType.MARKET,
                size=size,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                metadata={"signal_reason": signal.reason, **signal.metadata},
            ),
        )

    def record_trade(self) -> None:
        self.trades_today += 1
