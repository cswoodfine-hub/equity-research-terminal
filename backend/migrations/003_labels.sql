-- FDA structured product labels from DailyMed, tracked by set id so a version
-- increment is a detectable event. Additive only.
--
-- The population is stored as fields, not a text blob, so a change reads as a number:
-- an age floor moving 12 to 2 is a population expansion the diff engine can rank. The
-- raw indications section is kept alongside for traceability, and the SPL version id
-- ties every extracted field back to the exact label it came from.

CREATE TABLE labels (
    id               INTEGER PRIMARY KEY,
    asset_id         INTEGER REFERENCES assets(id),
    setid            TEXT NOT NULL UNIQUE,   -- DailyMed set id, stable across versions
    drug_name        TEXT,
    spl_version      INTEGER,                -- increments on every label revision
    effective_time   TEXT,                   -- published date of the current version
    indications_text TEXT,                   -- LOINC 34067-9 section, plain text
    indication_count INTEGER,                -- extracted; null when not resolved
    age_floor_years  REAL,                   -- youngest population, extracted; nullable
    age_ceiling_years REAL,                  -- oldest population, extracted; nullable
    population_text  TEXT,                    -- extracted phrase; nullable
    source           TEXT DEFAULT 'dailymed',
    fetched_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_labels_asset ON labels(asset_id);
