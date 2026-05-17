# System Architecture

## Objective

Build a strategy-swappable and broker-swappable algo trading system where the trading engine, broker integration, data feeds, risk controls, and reporting stay stable while strategies and brokers can be replaced through configuration.

The first broker will be Capital.com and the first strategy will be Opening Range Breakout (ORB), but neither Capital.com nor ORB must leak into the core architecture.

## Core Principle

The strategy produces intent. The platform decides whether, how, and where to execute it.

```text
Data Provider
  -> Market Data Cache
  -> Engine
  -> Strategy
  -> Signal
  -> Risk Manager
  -> Position Sizer
  -> Order Manager
  -> Broker Adapter
  -> Trade Store / Reports
```

## Major Components

| Component | Responsibility | Strategy-specific? |
| --- | --- | --- |
| Config Loader | Load and validate JSON settings | No |
| Data Provider | Fetch historical/live candles and prices | No |
| Market Data Cache | Store fetched historical data locally for repeatable backtests | No |
| Strategy Loader | Instantiate selected strategy by name | No |
| Strategy | Convert market data into trade signals | Yes |
| Risk Manager | Approve/reject signals based on account and limits | No |
| Position Sizer | Convert risk into trade size | No |
| Order Manager | Convert approved signals into orders | No |
| Broker Adapter | Talk to the selected broker through a common interface | No |
| Portfolio | Track cash, equity, positions, and PnL | No |
| Reporting | Metrics, trade logs, equity curves | No |

## Runtime Modes

| Mode | Data | Broker | Purpose |
| --- | --- | --- | --- |
| backtest | SQLite cache, CSV import, or broker fallback | Simulated broker | Strategy research |
| demo | Selected broker/data provider in demo or paper mode | Demo/paper broker adapter | Safe forward test |
| live | Selected live data provider | Selected live broker adapter | Real execution |

The same strategy interface should work in all modes.

## Project Shape

```text
capital_algo/
  config/
    app.json
    brokers/
      capital.json
      interactive_brokers.json
    data/
      cache.json
      capital.json
      interactive_brokers.json
    risk.json
    instruments.json
    strategies/
      orb.json

  src/
    broker/
    config/
    data/
    engine/
    execution/
    portfolio/
    reporting/
    risk/
    strategies/

  data/
    market.sqlite
    exports/

  planning/
  skills/
  tests/
```

## Non-Negotiable Boundaries

- Strategies do not call broker APIs.
- Strategies do not calculate final order size.
- Strategies do not bypass risk controls.
- Broker-specific details stay inside broker and data adapters.
- Capital.com is the first broker adapter, not a hard dependency.
- Instrument config maps logical symbols to broker-specific identifiers.
- Historical data should be cached locally before repeated backtests.
- Backtest and live trading use the same strategy contract.
- Credentials stay in environment variables, never JSON config.
