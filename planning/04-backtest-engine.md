# Backtest Engine

## Objective

Run the same strategy logic used in demo/live mode against historical data with realistic execution assumptions.

## Backtest Flow

```text
Load config
Resolve requested historical data from local cache
Fetch only missing historical data if policy allows
Store fetched data before running the test
Initialize broker simulation
Initialize portfolio
Initialize strategy
For each bar:
  update market state
  call strategy
  validate signals through risk manager
  size approved trades
  simulate execution
  update portfolio
  record events
Generate report
```

## Required Inputs

- instrument list
- historical candles
- data cache settings
- session calendar
- starting capital
- spread assumptions
- slippage assumptions
- commission/financing assumptions if applicable
- strategy config
- risk config

## Required Outputs

- trade log
- daily PnL
- equity curve
- drawdown curve
- strategy metrics
- rejected signal log
- config snapshot used for the run
- data coverage summary

## Metrics

Minimum first version:

- total return
- net profit
- win rate
- average win
- average loss
- profit factor
- max drawdown
- number of trades
- average R
- best/worst trade

Later:

- Sharpe ratio
- Sortino ratio
- monthly performance
- instrument-level attribution
- time-of-day performance
- walk-forward testing

## Execution Simulation

The simulated broker should support:

- market entries
- stop loss
- take profit
- end-of-session close
- spread
- slippage
- rejected orders when size is invalid

The simulation does not need to be perfect in version one, but all assumptions must be visible in the report.

## Historical Data Cache

SQLite should be the primary historical data store for repeated backtests. CSV should be supported as an import/export format, not the main backtest database.

Recommended local layout:

```text
data/
  market.sqlite
  imports/
  exports/
```

Recommended candle uniqueness:

```text
provider + instrument + timeframe + timestamp_utc
```

Backtest data resolution:

```text
Requested instrument/timeframe/date range
  -> check SQLite coverage
  -> if complete, load from SQLite
  -> if incomplete and API fetch is allowed, fetch missing ranges
  -> upsert fetched candles into SQLite
  -> run backtest from local stored candles
```

CSV support should include:

- import external historical data into SQLite
- export cached candles for inspection
- export exact backtest input data for reproducibility

The backtest report should state whether data came fully from cache or required an API fetch.
