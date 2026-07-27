-- The drug and biological interventions of each trial, one row per study drug.
--
-- ClinicalTrials.gov already returns these and the parser already reads them, but they
-- were dropped on the way to storage, which is why no trial is mapped to an asset: the
-- name that identifies the drug never reached the database. A trial can name several
-- drugs (a combination arm, a comparator), so this is its own table rather than a column
-- on trials, which also keeps the migration a plain CREATE and so idempotent on re-init.
--
-- ``norm`` is the name reduced for matching: lowercase, punctuation stripped, whitespace
-- collapsed. It is stored rather than computed per query so the match is a plain indexed
-- join, and so the normalisation rule lives in one place.
--
-- Identity is (nct_id, name): a re-fetch replaces a trial's rows rather than adding to
-- them. No foreign key to trials, because the interventions are written in the same pass
-- as the trial rows and a partial page must not fail the whole upsert.

CREATE TABLE trial_interventions (
    id          INTEGER PRIMARY KEY,
    nct_id      TEXT NOT NULL,
    name        TEXT NOT NULL,      -- as the registry writes it
    norm        TEXT,               -- normalised for matching
    kind        TEXT,               -- DRUG or BIOLOGICAL
    fetched_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(nct_id, name)
);
CREATE INDEX idx_trial_interventions_nct ON trial_interventions(nct_id);
CREATE INDEX idx_trial_interventions_norm ON trial_interventions(norm);
