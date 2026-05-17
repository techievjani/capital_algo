from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from capital_algo.models import Candle, Signal


class Strategy(ABC):
    """Common interface implemented by all strategies."""

    @abstractmethod
    def initialize(self, strategy_config: dict[str, Any], context: dict[str, Any]) -> None:
        """Initialize strategy state from configuration."""

    @abstractmethod
    def on_bar(self, bar: Candle, context: dict[str, Any]) -> list[Signal]:
        """Handle a completed candle and return zero or more signals."""

    def on_session_start(self, context: dict[str, Any]) -> None:
        """Optional session-start hook."""

    def on_session_end(self, context: dict[str, Any]) -> None:
        """Optional session-end hook."""

