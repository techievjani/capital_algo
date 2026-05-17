from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from capital_algo.models import Candle, Instrument, Tick


class DataProvider(ABC):
    """Common interface implemented by live and historical data providers."""

    @abstractmethod
    def get_instrument(self, symbol: str) -> Instrument:
        """Return metadata for a logical instrument symbol."""

    @abstractmethod
    def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        """Return historical candles using UTC bounds."""

    @abstractmethod
    def get_latest_tick(self, symbol: str) -> Tick:
        """Return the latest available tick."""

