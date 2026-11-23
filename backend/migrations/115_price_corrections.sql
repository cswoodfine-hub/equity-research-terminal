-- The prices the record carries that were not the close of their day, and what the close
-- turned out to be.
--
-- Until 2026-11-23 the daily price fetcher filed Yahoo's bar for a session still trading,
-- so a refresh that ran mid-session wrote the last trade into the day's snapshot under
-- the name of a close, and the day's calls were priced off it. The schedule that was
-- meant to prevent it started late on every run from 2026-10-10. Measured on 2026-11-23,
-- 28 days of snapshots and 382 of 1,542 model calls carry such a price.
--
-- A snapshot and a call are never rewritten: what the book said on the day is the
-- record, wrong price and all. So the correction is kept beside them, one row for each
-- recorded price that differs from the close the daily series later settled at
-- (price_record.py). A reader that wants the price the market closed at takes it from
-- here or from the daily series; a reader that wants what the book saw reads the row
-- itself.
--
-- ref_key names the corrected row by what it is and not by its id, because the local
-- book and the committed record number their rows apart: a snapshot by ticker and the
-- moment it was captured, a call by ticker and its day, a gate call by ticker, day and
-- catalyst. Append-only, one row a corrected row, and exported with the history.
CREATE TABLE IF NOT EXISTS price_corrections (
    id         INTEGER PRIMARY KEY,
    kind       TEXT NOT NULL,          -- snapshot, model_call, gate_call
    ref_key    TEXT NOT NULL,          -- what the corrected row is, without its id
    ticker     TEXT NOT NULL,
    price_date TEXT NOT NULL,          -- the session the recorded price was filed under
    recorded   REAL NOT NULL,          -- the price the row carries
    settled    REAL NOT NULL,          -- the close the daily series holds for that session
    found_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (kind, ref_key)
);
CREATE INDEX IF NOT EXISTS idx_price_corrections_ticker
    ON price_corrections (ticker, price_date);
