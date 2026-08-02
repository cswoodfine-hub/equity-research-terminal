-- A product revenue figure needs to say what stretch of time it covers.
--
-- The table was keyed (asset_id, fiscal_year), which is only sound while every figure is
-- an annual one from the SEC data sets. It is not: the quarterly product revenue table
-- printed in an 8-K earnings exhibit is the only place several products appear at all.
-- Biogen acquired Empaveli and Syfovre with Apellis in May 2026, so neither is in the
-- FY2025 data sets and neither will be tagged until the FY2026 10-K lands in early 2027,
-- while the 8-K filed 2026-07-29 states 30.4m and 97.4m for the June quarter.
--
-- Without a period column those figures could only be stored as if they were the year,
-- which would understate both products by about a factor of four. A quarter filed as a
-- year is worse than no figure, so the period is part of the key.
--
-- period is 'FY' or 'Q1'..'Q4' or 'H1'. period_end is the last day the figure covers,
-- which is what makes two Q2s from filers on different fiscal calendars comparable.
--
-- SQLite cannot alter a UNIQUE constraint, so the table is rebuilt. Every existing row is
-- an annual figure and takes period 'FY', which is what the old key meant implicitly.

ALTER TABLE asset_revenue RENAME TO asset_revenue_old;

CREATE TABLE asset_revenue (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id),
    fiscal_year INTEGER NOT NULL,
    period      TEXT NOT NULL DEFAULT 'FY',  -- FY, Q1..Q4, H1
    period_end  TEXT,                        -- ISO date the period closes on
    value       REAL,               -- as reported, not scaled
    unit        TEXT,               -- reporting currency, e.g. USD
    source      TEXT,               -- where it was read from, e.g. "FY2025 10-K"
    note        TEXT,
    is_curated  INTEGER DEFAULT 1,  -- 1 hand entered; 0 fetched
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id, fiscal_year, period)
);

INSERT INTO asset_revenue
    (id, asset_id, fiscal_year, period, period_end, value, unit, source, note,
     is_curated, updated_at)
SELECT id, asset_id, fiscal_year, 'FY', NULL, value, unit, source, note,
       is_curated, updated_at
  FROM asset_revenue_old;

DROP TABLE asset_revenue_old;

CREATE INDEX idx_asset_revenue ON asset_revenue(asset_id, fiscal_year);
CREATE INDEX idx_asset_revenue_period ON asset_revenue(asset_id, period, period_end);
