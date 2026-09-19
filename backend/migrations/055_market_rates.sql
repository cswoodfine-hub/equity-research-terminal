-- The market rates every discount rate is built on, one row per series per day.
--
-- The risk-free rate, the cost of debt and expected inflation were read by hand on one
-- day and written into every seed, so they aged where nobody could see it: the 10-year
-- Treasury was 4.66% when the book was built and 5.00% seven weeks later, which is 1.2%
-- of the book's value. fetchers/rates_fred.py keeps them current.
CREATE TABLE IF NOT EXISTS market_rates (
    id      INTEGER PRIMARY KEY,
    series  TEXT NOT NULL,          -- DGS10, DFII10, T10YIE, BAMLC0A3CAEY
    as_of   TEXT NOT NULL,          -- observation date, ISO
    value   REAL NOT NULL,          -- a rate, not a percentage: 0.0500 is 5.00%
    source  TEXT,
    UNIQUE(series, as_of)
);
CREATE INDEX IF NOT EXISTS idx_market_rates_series ON market_rates(series, as_of);
