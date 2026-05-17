# Capital.com Broker Adapter

## Objective

Implement Capital.com as the first broker/data adapter while keeping the core system broker-agnostic.

Capital.com is not the platform architecture. It is one adapter behind the common broker and data-provider interfaces.

## Validated Environment

The local `.env` has been validated against the Capital.com demo API:

- `POST /session` returned success
- `CST` header was returned
- `X-SECURITY-TOKEN` header was returned

Do not print or persist session tokens.

## Environment Variables

Required:

- `CAPITAL_API_KEY`
- `CAPITAL_IDENTIFIER`
- `CAPITAL_PASSWORD`
- `CAPITAL_ENV`

## Adapter Responsibilities

Capital data provider:

- authenticate safely
- fetch market/instrument metadata
- fetch historical candles
- fetch latest prices
- normalize Capital.com data into internal candle/tick models

Capital broker:

- authenticate safely
- keep session headers in memory only
- fetch account details
- fetch open positions
- place orders
- close positions
- attach or modify stop loss/take profit where supported
- handle API errors and retries

Capital instrument mapper:

- map logical symbols to Capital.com epics
- validate that configured epics exist
- keep Capital.com naming out of strategy code

## Internal Boundary

Capital.com models should be translated immediately into internal models.

The rest of the system should use internal objects such as:

- `Candle`
- `Tick`
- `OrderRequest`
- `OrderUpdate`
- `Position`
- `AccountSnapshot`

Broker adapters may add broker-specific metadata inside explicit metadata fields, but core logic should not depend on Capital.com response shapes.

## Safety Rules

- Default to demo environment.
- Live environment must require explicit config permission.
- Never store credentials in JSON.
- Never log full tokens, passwords, API keys, or auth headers.
- On authentication failure, report sanitized error codes only.
- On order failure, log enough context to debug without exposing secrets.

## Future Broker Compatibility

Design Capital.com integration as one implementation of the generic broker contract. Future adapters, such as Interactive Brokers, should implement the same internal methods and models without forcing changes in strategies, risk, backtest, or reporting.
