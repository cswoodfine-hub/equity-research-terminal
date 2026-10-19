-- What a drug is and what its trials showed, for comparing every candidate on one
-- indication regardless of modality or mechanism.
--
-- assets.mechanism and assets.target were never filled: 0 of 2,764 rows on 2026-09-29.
-- asset_pharmacology holds what the free sources say instead, one row per fact, so a
-- dual agonist carries two mechanism rows and a label carries its boxed warning, each
-- with the source it came from. Written by fetchers/pharmacology.py.
--
-- The trial_result_* tables hold the results a sponsor posted to ClinicalTrials.gov, per
-- arm: the outcome measures, the analyses the sponsor ran on them, the adverse event
-- totals and the most frequent events. Written by fetchers/trial_results.py. Nothing
-- here is computed across trials; comparing two of them is the landscape's job and it
-- says what it compared.

CREATE TABLE asset_pharmacology (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id),
    kind        TEXT NOT NULL,   -- mechanism | target | moa_class | epc_class | molecule_type | boxed_warning | route
    value       TEXT NOT NULL,   -- the fact as the source states it
    detail      TEXT,            -- action type, organism, or the like
    ref         TEXT,            -- the source's own id: ChEMBL molecule or target id, label set id
    source      TEXT NOT NULL,   -- chembl | openfda_label
    source_url  TEXT,
    fetched_at  TEXT DEFAULT (datetime('now')),
    UNIQUE (asset_id, kind, value, source)
);
CREATE INDEX idx_asset_pharmacology_asset ON asset_pharmacology(asset_id);

-- One posted outcome measure, one row per arm.
CREATE TABLE trial_result_outcomes (
    id               INTEGER PRIMARY KEY,
    nct_id           TEXT NOT NULL,
    outcome_index    INTEGER NOT NULL,  -- position in the registry's list, so arms of one measure group
    outcome_type     TEXT,              -- PRIMARY | SECONDARY | OTHER_PRE_SPECIFIED
    title            TEXT,
    time_frame       TEXT,
    unit             TEXT,
    param_type       TEXT,              -- MEAN | LEAST_SQUARES_MEAN | COUNT_OF_PARTICIPANTS | ...
    dispersion_type  TEXT,
    group_id         TEXT NOT NULL,
    group_title      TEXT,
    group_description TEXT,
    category         TEXT,              -- the class or category a value sits under, where the measure splits
    value            REAL,              -- null where the registry posted NA
    value_text       TEXT,              -- the value as posted, kept where it did not parse
    spread           REAL,
    lower            REAL,
    upper            REAL,
    n_analysed       INTEGER,
    fetched_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_tro_nct ON trial_result_outcomes(nct_id);

-- A statistical comparison the sponsor posted for one outcome.
CREATE TABLE trial_result_analyses (
    id             INTEGER PRIMARY KEY,
    nct_id         TEXT NOT NULL,
    outcome_index  INTEGER NOT NULL,
    group_ids      TEXT,               -- JSON list of the arms compared
    method         TEXT,
    param_type     TEXT,
    param_value    REAL,
    ci_pct         REAL,
    ci_lower       REAL,
    ci_upper       REAL,
    p_value        TEXT,               -- as posted: "<0.001" is a value, not a number
    fetched_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_tra_nct ON trial_result_analyses(nct_id);

-- Adverse event totals per arm, and the withdrawals the participant flow puts down to an
-- adverse event.
CREATE TABLE trial_result_safety (
    id                INTEGER PRIMARY KEY,
    nct_id            TEXT NOT NULL,
    group_id          TEXT NOT NULL,
    group_title       TEXT,
    deaths_affected   INTEGER,
    deaths_at_risk    INTEGER,
    serious_affected  INTEGER,
    serious_at_risk   INTEGER,
    other_affected    INTEGER,
    other_at_risk     INTEGER,
    withdrawn_ae      INTEGER,          -- from the participant flow, matched to this arm by title
    time_frame        TEXT,
    fetched_at        TEXT DEFAULT (datetime('now')),
    UNIQUE (nct_id, group_id)
);

-- The most frequent adverse events per study, each with its rate in every arm. Capped per
-- study at write time: the full tables run to hundreds of terms per arm.
CREATE TABLE trial_result_events (
    id            INTEGER PRIMARY KEY,
    nct_id        TEXT NOT NULL,
    term          TEXT NOT NULL,
    organ_system  TEXT,
    serious       INTEGER NOT NULL,     -- 1 for the serious table, 0 for the other
    group_id      TEXT NOT NULL,
    affected      INTEGER,
    at_risk       INTEGER,
    fetched_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_tre_nct ON trial_result_events(nct_id);

-- Which studies have been asked for, so a study with nothing posted is not asked again
-- on every run, and a study whose results changed is.
CREATE TABLE trial_result_fetches (
    nct_id        TEXT PRIMARY KEY,
    has_results   INTEGER NOT NULL,
    results_date  TEXT,                 -- the registry's resultsFirstPostDate or last update
    fetched_at    TEXT DEFAULT (datetime('now'))
);
