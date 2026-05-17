---
name: strategy-development
description: Use when adding, modifying, or reviewing trading strategies in CapitalAlgo. Ensures each strategy plugs into the common strategy interface, emits signals instead of orders, and remains independent from broker, risk, execution, and backtest internals.
---

# Strategy Development

## Workflow

1. Read `planning/02-strategy-interface.md`.
2. Confirm the strategy can be expressed as signals.
3. Keep all broker calls out of the strategy.
4. Keep final position sizing out of the strategy.
5. Add strategy-specific config under `config/strategies/`.
6. Add tests for signal generation and edge cases before using live/demo execution.

## Required Boundaries

- Strategy emits signals only.
- Strategy reads context but does not mutate broker/order/account state.
- Strategy-specific logic stays in the strategy module and config file.
- Shared risk, sizing, execution, and reporting behavior stays outside strategies.

## Strategy Checklist

- Defines required config fields.
- Handles missing/invalid market data.
- Handles session start and session end.
- Emits deterministic signals in backtests.
- Records signal reasons in metadata.
- Has tests for no-trade conditions.

