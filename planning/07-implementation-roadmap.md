# Implementation Roadmap

## Phase 1: Documentation And Contracts

- Create architecture plan
- Define strategy interface
- Define config schema
- Define backtest expectations
- Define Capital.com adapter boundaries
- Define risk rules

Status: complete

## Phase 2: Project Skeleton

- Create source package structure
- Add config examples
- Add typed internal models
- Add config loading and validation
- Add test structure
- Add SQLite market data cache schema
- Add generic broker and data-provider interfaces
- Add broker-specific instrument mapping schema

No trading logic yet.

Status: complete

## Phase 3: Capital.com Data Access

- Implement sanitized authentication
- Fetch account metadata
- Fetch market metadata
- Fetch historical candles
- Normalize candles into internal models
- Resolve logical symbols to Capital.com epics inside the adapter
- Save historical candles into SQLite cache
- Add CSV import/export around the same candle model

Status: complete for read-only data access; live order placement intentionally not enabled.

## Phase 4: Backtest Engine

- Implement historical event loop
- Resolve historical data from cache before running
- Fetch only missing ranges when policy allows
- Implement simulated broker
- Implement portfolio accounting
- Implement trade log
- Implement first metrics report

Status: complete for the first ORB/simulated-broker version.

## Phase 5: ORB Strategy Plugin

- Implement ORB as a strategy module
- Add ORB config validation
- Add unit tests for range construction and breakout signals
- Run historical backtests

Status: complete for the first ORB implementation.

## Phase 6: Demo/Paper Trading

- Add live/demo engine loop
- Add selected broker demo/paper execution, starting with Capital.com
- Add order state reconciliation
- Add protective logging

Status: scaffolded only. Execution against Capital.com is intentionally rejected until live/demo order safety is reviewed.

## Phase 7: Live Trading Readiness

- Add live permission gates
- Add runbook
- Add failure recovery rules
- Add monitoring checklist
- Run demo forward test before any live enablement

Status: not started. Live trading remains disabled.

## Phase 8: Future Broker Support

- Add Interactive Brokers adapter only after Capital.com path is stable
- Reuse generic broker/data-provider interfaces
- Add IBKR instrument mappings
- Add paper trading validation
- Compare execution behavior against simulated broker assumptions
