from __future__ import annotations

from abc import ABC, abstractmethod

from capital_algo.models import AccountSnapshot, OrderRequest, OrderResult, Position


class Broker(ABC):
    """Common interface implemented by all execution brokers."""

    @abstractmethod
    def connect(self) -> None:
        """Connect or authenticate with the broker."""

    @abstractmethod
    def get_account_snapshot(self) -> AccountSnapshot:
        """Return the current account state."""

    @abstractmethod
    def get_open_positions(self) -> list[Position]:
        """Return currently open positions."""

    @abstractmethod
    def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order request to the broker."""

    @abstractmethod
    def close_position(self, position_id: str) -> OrderResult:
        """Close an existing broker position."""

