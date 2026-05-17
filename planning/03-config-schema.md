# Config Schema

## Objective

Keep behavior configurable through JSON while keeping secrets out of files.

## Config Files

```text
config/
  app.json
  brokers/
    capital.json
    interactive_brokers.json
  data/
    cache.json
    capital.json
    interactive_brokers.json
  instruments.json
  risk.json
  strategies/
    orb.json
```

## app.json

Controls runtime mode and strategy selection.

```json
{
  "mode": "backtest",
  "active_strategy": "orb",
  "strategy_config": "config/strategies/orb.json",
  "broker": "capital",
  "broker_config": "config/brokers/capital.json",
  "data_provider": "cached",
  "data_config": "config/data/cache.json",
  "timezone": "Asia/Dubai"
}
```

Allowed modes:

- `backtest`
- `demo`
- `paper`
- `live`

## brokers/capital.json

Capital.com settings that are not secrets.

```json
{
  "environment": "demo",
  "base_currency": "USD",
  "request_timeout_seconds": 20,
  "max_retries": 3
}
```

Credentials come from environment variables:

- `CAPITAL_API_KEY`
- `CAPITAL_IDENTIFIER`
- `CAPITAL_PASSWORD`
- `CAPITAL_ENV`

## brokers/interactive_brokers.json

Interactive Brokers placeholder settings for future broker support.

```json
{
  "environment": "paper",
  "host": "127.0.0.1",
  "port": 7497,
  "client_id": 1,
  "base_currency": "USD",
  "request_timeout_seconds": 20
}
```

Credentials and local gateway/session details should stay outside strategy config.

## data/cache.json

Controls historical data storage and fetch behavior.

```json
{
  "historical_store": {
    "type": "sqlite",
    "path": "data/market.sqlite"
  },
  "csv": {
    "import_directory": "data/imports",
    "export_directory": "data/exports"
  },
  "fetch_policy": "cache_first",
  "allow_api_fetch_for_missing_data": true,
  "fallback_data_provider": "capital",
  "fallback_data_config": "config/data/capital.json",
  "timestamp_timezone": "UTC"
}
```

Recommended fetch policies:

- `cache_first`: use SQLite if present, fetch only missing ranges
- `cache_only`: fail if required data is missing locally
- `refresh`: fetch requested range again and upsert into cache

SQLite is the primary cache. CSV is for inspection, import, export, and portability.

## data/capital.json

Capital.com data-provider settings that are not secrets.

```json
{
  "environment": "demo",
  "default_timeframe": "MINUTE",
  "max_points_per_request": 1000
}
```

## data/interactive_brokers.json

Interactive Brokers data-provider placeholder for future support.

```json
{
  "environment": "paper",
  "default_bar_size": "1 min",
  "what_to_show": "TRADES",
  "use_rth": false
}
```

## instruments.json

Defines what can be traded.

```json
{
  "instruments": [
    {
      "symbol": "US100",
      "enabled": true,
      "session": "new_york_cash",
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
  ]
}
```

Strategies should use the logical `symbol`. Broker adapters translate that symbol to broker-specific identifiers.

## risk.json

Global risk controls independent of strategy.

```json
{
  "account_risk_per_trade_pct": 0.5,
  "max_daily_loss_pct": 2.0,
  "max_open_positions": 2,
  "max_trades_per_day": 3,
  "allow_live_trading": false
}
```

## strategies/orb.json

ORB-specific settings.

```json
{
  "strategy_id": "orb_v1",
  "session_name": "new_york_cash",
  "opening_range_minutes": 15,
  "trade_direction": "both",
  "entry_buffer_points": 0,
  "stop_loss_mode": "opposite_range",
  "take_profit_r_multiple": 2.0,
  "max_trades_per_session": 1,
  "close_at_session_end": true
}
```

## Validation Rules

- JSON must be validated before any backtest or live run starts.
- Live mode must fail unless `allow_live_trading` is explicitly true.
- Strategy config must match the active strategy.
- Instruments must resolve to valid identifiers for the selected broker before live/demo/paper trading.
- Selected broker and data provider must match configured runtime mode.
- Timezones and sessions must be explicit.
- Historical candle timestamps must be stored in UTC.
- Backtests should not fetch from the API when the requested range already exists in the local cache.
