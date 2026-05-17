---
name: broker-integration
description: Use when implementing or changing broker or data-provider integrations in CapitalAlgo, including Capital.com and future brokers like Interactive Brokers. Keeps broker-specific authentication, symbols, account data, market data, order placement, and response models inside adapters with sanitized logging and environment safety gates.
---

# Broker Integration

## Workflow

1. Read `planning/09-broker-abstraction.md`.
2. For Capital.com work, also read `planning/05-capital-api-integration.md`.
3. Keep credentials in environment variables only.
4. Authenticate against demo or paper first.
5. Normalize broker responses into internal models.
6. Do not expose broker response shapes outside adapter boundaries unless explicitly mapped.
7. Sanitize all logs and errors.

## Safety Rules

- Never print API keys, passwords, `CST`, or `X-SECURITY-TOKEN`.
- Default to demo or paper.
- Require explicit config permission for live.
- Keep session tokens in memory only.
- Return sanitized errors to the caller.

## Adapter Checklist

- Handles auth success and failure.
- Handles retries where appropriate.
- Handles rate limits.
- Maps logical instruments to broker-specific identifiers clearly.
- Validates order requests before sending.
- Records broker response ids without recording secrets.
- Implements the generic broker/data-provider interface.
