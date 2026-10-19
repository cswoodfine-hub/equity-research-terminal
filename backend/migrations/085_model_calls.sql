-- What the model said each day, kept exactly as it was said: the point-in-time record
-- every call is later scored against (backend/call_log.py). A row is written once a day
-- and never updated, so the record cannot be improved with hindsight.

-- One row per company per day: the fair value, its range, the 12-month view and rating,
-- and the other lenses the same day, all against the close the call was made on.
CREATE TABLE IF NOT EXISTS model_calls (
    id              INTEGER PRIMARY KEY,
    as_of           TEXT NOT NULL,     -- the day the call was made
    ticker          TEXT NOT NULL,
    cohort          TEXT,              -- the engine it is valued on: pharma, biotech, cellgene
    price           REAL,              -- the close the call was made against
    price_date      TEXT,
    fair_value      REAL,              -- equity per share, the sum of the parts
    value_today     REAL,
    low_today       REAL,
    high_today      REAL,
    forward_12m     REAL,
    upside_12m      REAL,
    rating          TEXT,
    cost_of_equity  REAL,
    target_low      REAL,              -- analyst price targets the same day
    target_mid      REAL,
    target_high     REAL,
    pe_mid          REAL,              -- the other lenses' midpoints
    ev_sales_mid    REAL,
    precedents_mid  REAL,
    code_version    TEXT,              -- the commit that computed the call
    refresh_run_id  INTEGER,
    recorded_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(as_of, ticker)
);
CREATE INDEX IF NOT EXISTS idx_model_calls_ticker ON model_calls(ticker, as_of);

-- One row per priced gate per day: the odds the model put on it and what each leg is worth
-- a share, so the odds can be scored against the readouts as they land.
CREATE TABLE IF NOT EXISTS gate_calls (
    id                 INTEGER PRIMARY KEY,
    as_of              TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    catalyst_id        INTEGER,
    asset_id           INTEGER,
    asset_name         TEXT,
    gate               TEXT,           -- p3_to_nda and the like
    gate_label         TEXT,
    trial              TEXT,           -- the NCT number that decides it
    expected_date      TEXT,
    date_confidence    TEXT,
    p_gate             REAL,           -- the odds the gate passes
    pos_now            REAL,
    pos_success        REAL,
    pos_failure        REAL,
    per_share_now      REAL,
    per_share_success  REAL,
    per_share_failure  REAL,
    price              REAL,
    code_version       TEXT,
    refresh_run_id     INTEGER,
    recorded_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(as_of, ticker, catalyst_id)
);
CREATE INDEX IF NOT EXISTS idx_gate_calls_asset ON gate_calls(asset_id, as_of);
