---
name: risk-management
description: Use when implementing or reviewing CapitalAlgo risk controls, position sizing, order validation, kill switches, and live/demo safety gates. Keeps risk independent from individual strategies.
---

# Risk Management

## Workflow

1. Read `planning/06-risk-management.md`.
2. Validate every signal before sizing.
3. Calculate size from account risk and stop distance.
4. Validate final order before broker submission.
5. Record rejected signals with reasons.

## Required Controls

- max risk per trade
- max daily loss
- max open positions
- max trades per day
- instrument enable/disable
- duplicate order protection
- explicit live trading permission

## Principle

Strategies suggest trades. Risk decides whether the system may take them.

