-- Completed studies that have reported, which the pipeline fetch deliberately excludes.
--
-- The trials table holds active work, because that is what a pipeline is. A product's
-- evidence is the other half: an analyst looking at Verzenio wants the studies that read
-- out and what they measured, not only the ones still running. Those are a different
-- query against the same registry and a different question, so they live apart and
-- nothing that counts the pipeline can pick them up by accident.
--
-- Only studies the registry marks as having results are stored: a completed study with
-- no results posted says nothing that can be read here.

CREATE TABLE completed_trials (
    nct_id              TEXT PRIMARY KEY,
    sponsor_company_id  INTEGER REFERENCES companies(id),
    asset_id            INTEGER REFERENCES assets(id),
    title               TEXT,
    phase               TEXT,
    conditions          TEXT,        -- JSON array, as the trials table stores them
    completion_date     TEXT,
    enrollment          INTEGER,
    primary_outcome     TEXT,        -- the measure, as the registry words it
    fetched_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_completed_asset ON completed_trials(asset_id, completion_date);
CREATE INDEX idx_completed_company ON completed_trials(sponsor_company_id);
