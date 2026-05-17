---
name: backtesting
description: Use when building or reviewing CapitalAlgo backtest functionality. Ensures historical runs use the same strategy interface as live/demo mode, include realistic execution assumptions, and produce repeatable reports.
---

# Backtesting

## Workflow

1. Read `planning/04-backtest-engine.md`.
2. Read `planning/08-market-data-cache.md` when historical data loading is involved.
3. Load a frozen config snapshot for each run.
4. Resolve historical data from SQLite before calling any external API.
5. Use internal candle models.
6. Run the same strategy interface used by demo/live mode.
7. Route signals through risk and sizing before simulated execution.
8. Produce trade logs and metrics after each run.

## Backtest Integrity

- Do not let strategy inspect future bars.
- Make spread/slippage assumptions explicit.
- Record rejected signals.
- Keep data timezone handling explicit.
- Use deterministic ordering when multiple instruments share timestamps.
- Store historical candle timestamps in UTC.
- Do not fetch from Capital.com when the requested range already exists in SQLite.

## Minimum Outputs

- trade log
- equity curve
- daily PnL
- max drawdown
- win rate
- profit factor
- config snapshot
- data coverage summary
