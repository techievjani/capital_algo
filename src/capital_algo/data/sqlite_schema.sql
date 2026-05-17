PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candles (
    provider TEXT NOT NULL,
    instrument TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    source_fetched_at TEXT NOT NULL,
    metadata_json TEXT,
    PRIMARY KEY (provider, instrument, timeframe, timestamp_utc)
);

CREATE INDEX IF NOT EXISTS idx_candles_range
ON candles (provider, instrument, timeframe, timestamp_utc);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    instrument TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    from_utc TEXT NOT NULL,
    to_utc TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    candle_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_fetch_log_lookup
ON fetch_log (provider, instrument, timeframe, from_utc, to_utc);

