-- The assumption layer: every number a forecast rests on, held as an analyst input.
--
-- The reference is the CASGEVY DCF workbook, where each assumption is a row of label,
-- value and source note ("Source: CDC / FDA" against prevalence, "Damodaran US ERP
-- estimate" against the equity risk premium). That is the no-fabrication rule satisfied
-- by curation with provenance, and this table is that sheet made queryable: the engine
-- computes from these rows and never invents one.
--
-- Keyed to the asset, and to the indication where the number is indication-scoped
-- (prevalence is; tax rate is not). Region is a dimension from day one with only the US
-- populated in v1. Scenario carries the workbook's bear, base and bull columns. A year
-- makes the row one point of a series, which is how a hand-typed patient curve is held:
-- one row per year under the key new_patients.
--
-- Saved forecast runs go to the existing snapshots table (source 'forecast'), so history
-- is never overwritten and a later build can diff pre-event against post-event.
CREATE TABLE assumptions (
    id            INTEGER PRIMARY KEY,
    asset_id      INTEGER NOT NULL REFERENCES assets(id),
    indication_id INTEGER REFERENCES indications(id),   -- NULL = asset-level
    region        TEXT NOT NULL DEFAULT 'US',
    scenario      TEXT NOT NULL DEFAULT 'base',         -- base, bear, bull
    key           TEXT NOT NULL,                        -- canonical vocabulary in forecast.py
    year          INTEGER,                              -- NULL = scalar, else one year of a series
    value         REAL,
    text_value    TEXT,                                 -- for non-numeric keys, e.g. therapy_mode
    unit          TEXT,
    source        TEXT,                                 -- unsourced rows are flagged in the UI
    note          TEXT,
    as_of         TEXT,
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX idx_assumptions_key ON assumptions(
    asset_id, IFNULL(indication_id, 0), region, scenario, key, IFNULL(year, 0));
CREATE INDEX idx_assumptions_asset ON assumptions(asset_id);
