-- Intraday OHLC bars for the trading chart, at more than one bar size at once.
--
-- The prices table is keyed UNIQUE(company_id, as_of), so it cannot hold 5m, 15m and
-- 60m bars together: a 5-minute and a 60-minute bar share the 09:30 timestamp and would
-- overwrite each other. This table adds the bar size to the key so the sizes coexist.
--
-- Additive only; the prices table (daily plus the legacy 15m sparkline series) is
-- untouched. Yahoo caps intraday history, so this is a rolling window, not a record:
-- 5m runs back about two months, 60m about two years, and old bars fall out of range.

CREATE TABLE intraday_bars (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    as_of       TEXT NOT NULL,          -- 'YYYY-MM-DD HH:MM' in the exchange's local time
    interval    TEXT NOT NULL,          -- '5m' or '60m'
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      INTEGER,
    source      TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, as_of, interval)
);
CREATE INDEX idx_intraday_bars_lookup ON intraday_bars(company_id, interval, as_of);
