from __future__ import annotations

from dataclasses import dataclass

from capital_algo.models import AccountSnapshot, OrderRequest, OrderResult, OrderStatus, Position, TradeAction


@dataclass
class SimulatedTrade:
    instrument: str
    action: TradeAction
    size: float
    entry_price: float
    stop_loss: float | None
    take_profit: float | None
    entry_time: str
    initial_risk: float
    trailing_enabled: bool = False
    trailing_activation_r: float = 1.0
    trailing_distance_r: float = 1.0
    highest_price: float | None = None
    lowest_price: float | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    pnl: float = 0.0
    exit_reason: str | None = None


class SimulatedBroker:
    def __init__(self, starting_balance: float, currency: str = "USD", execution_config: dict | None = None) -> None:
        self.balance = starting_balance
        self.currency = currency
        self.execution_config = execution_config or {}
        self.open_trades: list[SimulatedTrade] = []
        self.closed_trades: list[SimulatedTrade] = []

    def connect(self) -> None:
        return None

    def get_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            account_id="SIM",
            currency=self.currency,
            balance=self.balance,
            equity=self.balance,
            available_funds=self.balance,
        )

    def get_open_positions(self) -> list[Position]:
        return [
            Position(
                instrument=trade.instrument,
                size=trade.size if trade.action == TradeAction.BUY else -trade.size,
                average_price=trade.entry_price,
            )
            for trade in self.open_trades
        ]

    def submit_order_at_price(self, order: OrderRequest, price: float, timestamp: str) -> OrderResult:
        initial_risk = abs(price - order.stop_loss) if order.stop_loss is not None else 0.0
        trailing_config = self.execution_config.get("trailing_stop", {})
        self.open_trades.append(
            SimulatedTrade(
                instrument=order.instrument,
                action=order.action,
                size=order.size,
                entry_price=price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                entry_time=timestamp,
                initial_risk=initial_risk,
                trailing_enabled=bool(trailing_config.get("enabled", False)),
                trailing_activation_r=float(trailing_config.get("activation_r", 1.0)),
                trailing_distance_r=float(trailing_config.get("distance_r", 1.0)),
                highest_price=price,
                lowest_price=price,
            )
        )
        return OrderResult(status=OrderStatus.FILLED, broker_order_id=f"SIM-{len(self.open_trades)}")

    def submit_order(self, order: OrderRequest) -> OrderResult:
        return OrderResult(status=OrderStatus.REJECTED, rejection_reason="submit_order_at_price is required")

    def close_position(self, position_id: str) -> OrderResult:
        return OrderResult(status=OrderStatus.REJECTED, rejection_reason="close_position by id is not implemented")

    def update_for_bar(self, instrument: str, high: float, low: float, close: float, timestamp: str) -> None:
        still_open: list[SimulatedTrade] = []
        for trade in self.open_trades:
            if trade.instrument != instrument:
                still_open.append(trade)
                continue
            self._update_trailing_stop(trade, high, low)
            exit_price = None
            exit_reason = None
            if trade.action == TradeAction.BUY:
                if trade.stop_loss is not None and low <= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = "trailing_stop" if trade.trailing_enabled else "stop_loss"
                elif trade.take_profit is not None and high >= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = "take_profit"
            else:
                if trade.stop_loss is not None and high >= trade.stop_loss:
                    exit_price = trade.stop_loss
                    exit_reason = "trailing_stop" if trade.trailing_enabled else "stop_loss"
                elif trade.take_profit is not None and low <= trade.take_profit:
                    exit_price = trade.take_profit
                    exit_reason = "take_profit"

            if exit_price is None:
                still_open.append(trade)
            else:
                self._close_trade(trade, exit_price, timestamp, exit_reason or "exit")
        self.open_trades = still_open

    def close_all(self, close_prices: dict[str, float], timestamp: str, reason: str) -> None:
        for trade in list(self.open_trades):
            self._close_trade(trade, close_prices[trade.instrument], timestamp, reason)
        self.open_trades.clear()

    def _close_trade(self, trade: SimulatedTrade, price: float, timestamp: str, reason: str) -> None:
        direction = 1 if trade.action == TradeAction.BUY else -1
        trade.exit_price = price
        trade.exit_time = timestamp
        trade.exit_reason = reason
        trade.pnl = (price - trade.entry_price) * direction * trade.size
        self.balance += trade.pnl
        self.closed_trades.append(trade)

    def _update_trailing_stop(self, trade: SimulatedTrade, high: float, low: float) -> None:
        if not trade.trailing_enabled or trade.initial_risk <= 0 or trade.stop_loss is None:
            return

        if trade.action == TradeAction.BUY:
            trade.highest_price = max(trade.highest_price or trade.entry_price, high)
            favorable_r = (trade.highest_price - trade.entry_price) / trade.initial_risk
            if favorable_r < trade.trailing_activation_r:
                return
            candidate = trade.highest_price - (trade.initial_risk * trade.trailing_distance_r)
            trade.stop_loss = max(trade.stop_loss, candidate)
        else:
            trade.lowest_price = min(trade.lowest_price or trade.entry_price, low)
            favorable_r = (trade.entry_price - trade.lowest_price) / trade.initial_risk
            if favorable_r < trade.trailing_activation_r:
                return
            candidate = trade.lowest_price + (trade.initial_risk * trade.trailing_distance_r)
            trade.stop_loss = min(trade.stop_loss, candidate)
