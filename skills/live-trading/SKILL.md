---
name: live-trading
description: Use when preparing CapitalAlgo for demo or live trading loops. Emphasizes environment gates, broker reconciliation, duplicate-order protection, safe shutdown behavior, and logging without secrets.
---

# Live Trading

## Workflow

1. Confirm backtest behavior is already implemented and tested.
2. Run in the selected broker's demo or paper mode before live mode.
3. Validate config gates before connecting to broker execution.
4. Reconcile account and open positions on startup.
5. Route all signals through risk and order management.
6. Log lifecycle events without secrets.

## Live Gates

- `mode` must be `live`.
- broker environment must be `live`.
- risk config must include `allow_live_trading: true`.
- account and instrument metadata must be fetched successfully.
- max daily loss and max order size must be configured.

## Shutdown Behavior

The system should define whether shutdown:

- leaves positions open
- closes strategy-owned positions
- cancels pending orders
- only stops new entries

This behavior must be explicit in config before live use.
