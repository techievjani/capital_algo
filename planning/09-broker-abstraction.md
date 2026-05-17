# Broker Abstraction

## Objective

Make brokers swappable in the same way strategies are swappable.

Capital.com is the first broker adapter. Interactive Brokers or another broker should be addable later without changing strategy, risk, backtest, or reporting architecture.

## Core Principle

The core system speaks internal models. Broker adapters translate broker-specific APIs, symbols, order rules, and account details into those models.

```text
Strategy
  -> Signal
  -> Risk Manager
  -> Position Sizer
  -> Order Manager
  -> Broker Interface
      -> CapitalBroker
      -> InteractiveBrokersBroker
      -> PaperBroker
      -> SimulatedBroker
```

## Broker Interface Responsibilities

Every broker adapter should support the same high-level responsibilities:

- connect/authenticate
- get account snapshot
- get open positions
- submit order
- modify order where supported
- cancel order where supported
- close position
- receive or poll order updates
- normalize broker errors

## Data Provider Interface Responsibilities

Data is separate from execution because a backtest may use SQLite while live trading uses a broker feed.

Every data provider should support:

- get historical candles
- get latest quote or price
- get instrument metadata
- normalize candles/ticks into internal models

## Internal Models

The shared system should depend on internal models only:

- `Instrument`
- `Candle`
- `Tick`
- `OrderRequest`
- `OrderResult`
- `OrderUpdate`
- `Position`
- `AccountSnapshot`
- `ExecutionReport`

Broker-specific fields should live in metadata rather than replacing common fields.

## Instrument Mapping

Strategies use logical symbols:

```text
US100
EURUSD
GOLD
```

Instrument config maps those symbols to broker identifiers:

```json
{
  "symbol": "US100",
  "brokers": {
    "capital": {
      "epic": "US100"
    },
    "interactive_brokers": {
      "symbol": "NQ",
      "sec_type": "FUT",
      "exchange": "CME",
      "currency": "USD"
    }
  }
}
```

The strategy never sees the Capital.com epic or Interactive Brokers contract details.

## Broker Differences To Isolate

Adapters must hide or normalize differences in:

- symbol identifiers
- order types
- stop loss and take profit behavior
- margin and leverage rules
- lot size or contract size
- minimum order size
- trading sessions
- commissions, spread, and financing
- account currency
- rate limits
- historical data limits

If a broker cannot support a requested capability, the adapter should return a clear normalized rejection.

## Config Switching

Capital.com:

```json
{
  "broker": "capital",
  "broker_config": "config/brokers/capital.json",
  "data_provider": "cached",
  "data_config": "config/data/cache.json"
}
```

Future Interactive Brokers:

```json
{
  "broker": "interactive_brokers",
  "broker_config": "config/brokers/interactive_brokers.json",
  "data_provider": "interactive_brokers",
  "data_config": "config/data/interactive_brokers.json"
}
```

## Backtest Broker

Backtesting should always use a simulated broker unless explicitly testing broker-specific execution assumptions.

The simulated broker should use the same `OrderRequest` and `OrderResult` models as live brokers.
