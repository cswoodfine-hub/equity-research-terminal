-- The market series a beta is measured against.
--
-- Every seeded beta in this repository says "computed from 261 weekly returns vs S&P 500,
-- Blume-adjusted", and none of them could be recomputed: the index series was never
-- stored, so the number was a memory of a calculation rather than a calculation. Four
-- companies then had to be left unforecastable, or given a beta from nowhere, because
-- they had no such memory attached to them.
--
-- Kept out of the prices table on purpose. That table is keyed on company_id and every
-- row in it is a company this universe covers; an index is not a company, and putting one
-- in there would have it appear in the map, the comps and the coverage counts.
CREATE TABLE benchmark_prices (
    id         INTEGER PRIMARY KEY,
    symbol     TEXT NOT NULL,             -- ^GSPC
    as_of      TEXT NOT NULL,
    close      REAL NOT NULL,
    source     TEXT DEFAULT 'yahoo_chart',
    fetched_at TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, as_of)
);
CREATE INDEX idx_benchmark_prices ON benchmark_prices(symbol, as_of);
