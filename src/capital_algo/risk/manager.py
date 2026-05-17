from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from capital_algo.models import AccountSnapshot, OrderRequest, OrderType, Signal


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    order: OrderRequest | None = None
    metadata: dict[str, Any] | None = None


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
        metadata = {
            "account_balance": account.balance,
            "account_equity": account.equity,
            "account_available_funds": account.available_funds,
            "entry_price": entry_price,
            "trading_day": trading_day,
            "trades_today": self.trades_today,
            "max_trades_per_day": int(self.config["max_trades_per_day"]),
            "position_sizing_mode": self.config.get("position_sizing_mode", "dynamic"),
        }
        if signal.stop_loss is None:
            return RiskDecision(False, "missing_stop_loss", metadata=metadata)
        if self.trades_today >= int(self.config["max_trades_per_day"]):
            return RiskDecision(False, "max_trades_per_day_reached", metadata=metadata)

        stop_distance = abs(entry_price - signal.stop_loss)
        metadata["stop_distance"] = stop_distance
        if stop_distance <= 0:
            return RiskDecision(False, "invalid_stop_distance", metadata=metadata)

        if self.config.get("position_sizing_mode") == "fixed":
            fixed_sizes = self.config.get("fixed_position_sizes", {})
            fixed_size = fixed_sizes.get(signal.instrument, self.config.get("fixed_position_size"))
            if fixed_size is None:
                return RiskDecision(False, "missing_fixed_position_size", metadata=metadata)
            size = float(fixed_size)
            metadata["fixed_position_size"] = size
        else:
            risk_amount = account.equity * (float(self.config["account_risk_per_trade_pct"]) / 100.0)
            metadata["risk_amount"] = risk_amount
            metadata["account_risk_per_trade_pct"] = float(self.config["account_risk_per_trade_pct"])
            size = risk_amount / stop_distance
        initial_size = size
        max_notional_pct = self.config.get("max_position_notional_pct")
        if max_notional_pct is not None and entry_price > 0:
            funds_base = account.available_funds if account.available_funds is not None else account.equity
            max_notional = funds_base * (float(max_notional_pct) / 100.0)
            max_size = max_notional / entry_price
            if max_size > 0 and size > max_size:
                size = max_size
                metadata["position_size_capped"] = True
            metadata["max_position_notional_pct"] = float(max_notional_pct)
            metadata["max_position_notional"] = max_notional
            metadata["max_position_size"] = max_size
        metadata["initial_position_size"] = initial_size
        metadata["final_position_size"] = size
        if size <= 0:
            return RiskDecision(False, "invalid_position_size", metadata=metadata)

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
            metadata=metadata,
        )

    def record_trade(self) -> None:
        self.trades_today += 1
