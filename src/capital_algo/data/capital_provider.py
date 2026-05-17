from __future__ import annotations

from datetime import datetime

from capital_algo.broker.capital import CapitalClient
from capital_algo.data.base import DataProvider
from capital_algo.instruments import broker_mapping
from capital_algo.models import Candle, Instrument, Tick


class CapitalDataProvider(DataProvider):
    def __init__(
        self,
        client: CapitalClient,
        instruments: dict[str, Instrument],
        default_timeframe: str = "MINUTE",
        max_points_per_request: int = 1000,
    ) -> None:
        self.client = client
        self.instruments = instruments
        self.default_timeframe = default_timeframe
        self.max_points_per_request = max_points_per_request

    def connect(self) -> None:
        self.client.connect()

    def get_instrument(self, symbol: str) -> Instrument:
        return self.instruments[symbol]

    def get_historical_candles(
        self,
        symbol: str,
        timeframe: str,
        start_utc: datetime,
        end_utc: datetime,
    ) -> list[Candle]:
        instrument = self.get_instrument(symbol)
        epic = broker_mapping(instrument, "capital")["epic"]
        return self.client.get_prices(
            epic=epic,
            resolution=timeframe or self.default_timeframe,
            start_utc=start_utc,
            end_utc=end_utc,
            max_points=self.max_points_per_request,
            logical_symbol=symbol,
        )

    def get_latest_tick(self, symbol: str) -> Tick:
        candles = self.get_historical_candles(symbol, self.default_timeframe, datetime.utcnow(), datetime.utcnow())
        if not candles:
            raise ValueError(f"No latest price available for {symbol}")
        candle = candles[-1]
        return Tick(
            provider="capital",
            instrument=symbol,
            timestamp_utc=candle.timestamp_utc,
            bid=None,
            ask=None,
            last=candle.close,
            metadata=candle.metadata,
        )

