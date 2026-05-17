# Market Data Cache

## Objective

Avoid repeated Capital.com API fetches for the same historical candles and make backtests faster, repeatable, and auditable.

SQLite is the primary cache. CSV is for import, export, inspection, and sharing.

## Storage Choice

| Option | Role | Reason |
| --- | --- | --- |
| SQLite | Primary historical cache | Fast range queries, uniqueness constraints, metadata, less duplication |
| CSV | Import/export format | Easy manual inspection and portability |

## Local Layout

```text
data/
  market.sqlite
  imports/
  exports/
```

The `.gitignore` should exclude local market data by default.

## Candle Table

Recommended `candles` table:

```text
provider
instrument
timeframe
timestamp_utc
open
high
low
close
volume
source_fetched_at
```

Recommended unique key:

```text
provider + instrument + timeframe + timestamp_utc
```

This allows overlapping API fetches to upsert without duplicate candles.

## Fetch Log Table

Recommended `fetch_log` table:

```text
provider
instrument
timeframe
from_utc
to_utc
fetched_at
status
candle_count
notes
```

The fetch log is useful for debugging gaps, rate-limit issues, and data provenance.

## Cache Policies

Supported policies:

- `cache_first`: use local data and fetch only missing ranges
- `cache_only`: fail if requested data is missing locally
- `refresh`: refetch requested range and upsert into SQLite

Default should be `cache_first`.

## Backtest Data Resolution

```text
Backtest asks for instrument + timeframe + date range
  -> query SQLite coverage
  -> detect missing ranges
  -> fetch missing ranges if policy allows
  -> save fetched candles
  -> load final candles from SQLite
  -> run backtest
```

The backtest should run from local stored candles after any fetch completes. That makes the data source for execution stable.

## CSV Rules

CSV import should normalize into the same internal candle model and then save to SQLite.

CSV export should include:

- provider
- instrument
- timeframe
- timestamp_utc
- open
- high
- low
- close
- volume

## Timezone Rules

- Store candle timestamps in UTC.
- Keep session definitions separate from stored candle timestamps.
- Convert to exchange/session timezone only when evaluating trading sessions.

## Validation

Before a backtest starts:

- verify requested range has complete candle coverage
- report any missing ranges
- fail in `cache_only` mode if data is incomplete
- record whether API fetching was needed
