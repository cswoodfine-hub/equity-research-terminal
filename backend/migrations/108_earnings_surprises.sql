-- What each quarter's EPS was against what the street expected going in.
--
-- The book held annual estimates and no quarterly ones, so it could say what a quarter
-- reported and not how it landed: 7.22 a share says nothing until it stands beside the
-- number the price already held. Nasdaq's earnings surprise table carries the last four
-- quarters for a symbol: the EPS as the street counts it, the consensus before the
-- report, and the day it was reported.
--
-- The EPS here is the street's, which is usually the company's adjusted figure. It is
-- not the filed diluted EPS and is never shown as one: Lilly's September 2026 quarter is
-- 7.48 here and 7.22 in its 10-Q. Per share of the US listing, in dollars.
--
-- One row per company and fiscal quarter end. A later read replaces the row, since
-- Nasdaq restates a figure in place and keeps no history of its own.
CREATE TABLE IF NOT EXISTS earnings_surprises (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    quarter_end   TEXT NOT NULL,   -- YYYY-MM, the month the fiscal quarter closes in
    reported_on   TEXT,            -- ISO date the results were announced
    eps           REAL,            -- as the street counts it; adjusted, not filed
    consensus_eps REAL,
    surprise_pct  REAL,            -- Nasdaq's own figure where it prints one
    source        TEXT NOT NULL DEFAULT 'nasdaq',
    fetched_at    TEXT DEFAULT (datetime('now')),
    UNIQUE (company_id, quarter_end)
);
CREATE INDEX IF NOT EXISTS earnings_surprises_company
    ON earnings_surprises (company_id, quarter_end);
