-- The Medicare prices CMS has negotiated under the Inflation Reduction Act, one row per
-- selected drug, national drug code and price period (fetchers/negotiated_prices_cms.py).
-- A row carrying an end date has been superseded, by the annual inflation adjustment or
-- by CMS deselecting the drug when a generic or biosimilar arrived.
CREATE TABLE negotiated_prices (
    id             INTEGER PRIMARY KEY,
    drug           TEXT NOT NULL,          -- every brand the one price covers
    ingredient     TEXT,
    ipay           INTEGER NOT NULL,       -- initial price applicability year
    ndc9           TEXT,
    hcpcs          TEXT,
    mfp_30des      REAL,                   -- maximum fair price per 30-day equivalent supply
    unit_price     REAL,
    effective_from TEXT NOT NULL,
    effective_to   TEXT,
    as_of          TEXT,
    update_kind    TEXT,
    remarks        TEXT,
    source         TEXT,
    fetched_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(drug, ndc9, effective_from)
);
CREATE INDEX idx_negotiated_prices_drug ON negotiated_prices(drug, ipay);
