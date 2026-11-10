-- What the book said a company was worth, on the day it said it.
--
-- The snapshot history records the sources: prices, revenue, trials, filings. It has
-- never recorded the call those sources add up to, so there is no way to ask whether the
-- book's upside led the price. Every other claim here is tested against something; the
-- valuation is the one that is not, and it cannot be tested retrospectively because the
-- figure was never kept. This is where it starts being kept.
--
-- One row per company per price date, so a refresh run twice in a day replaces rather
-- than doubles. A company the book refuses to value is recorded too, with the reason:
-- a refusal is a call as much as a number is, and a book that only remembered its
-- answers would flatter itself.
CREATE TABLE IF NOT EXISTS valuation_snapshots (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(id),
    as_of               TEXT NOT NULL,
    captured_at         TEXT NOT NULL,
    close               REAL,
    equity_per_share    REAL,
    upside              REAL,
    coverage_share      REAL,
    marketed_per_share  REAL,
    pipeline_per_share  REAL,
    future_per_share    REAL,
    refused             TEXT,
    refresh_run_id      INTEGER REFERENCES refresh_runs(id),
    UNIQUE (company_id, as_of)
);
CREATE INDEX IF NOT EXISTS idx_valuation_snapshots_as_of
    ON valuation_snapshots (as_of);
