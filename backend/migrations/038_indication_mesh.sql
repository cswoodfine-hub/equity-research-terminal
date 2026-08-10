-- The asset-indication pair, which CLAUDE.md calls the unit of analysis, has never had a
-- row in it. The data was always there: 3,159 of 3,184 trials carry both an asset and a
-- condition list. What was missing is a vocabulary. The sponsor's free text gives 2,061
-- distinct strings for 3,184 trials, so "Non-Small Cell Lung Cancer", "Carcinoma,
-- Non-Small-Cell Lung" and "Non-small Cell Lung Cancer" are one indication counted three
-- times, and "Healthy Volunteers" is counted as an indication at all.
--
-- ClinicalTrials.gov already derives the controlled vocabulary and the fetcher was simply
-- not asking for it. derivedSection.conditionBrowseModule.meshes returns the specific MeSH
-- descriptors with stable ids, so D006689 collapses "Hodgkin Lymphoma" and "Hodgkin
-- Disease" onto one indication. The ancestors alongside them are deliberately not stored:
-- they carry Neoplasms and Lymphatic Diseases for every oncology study, and filing assets
-- under those would make the table useless.

ALTER TABLE trials ADD COLUMN mesh_terms TEXT;            -- JSON [{id, term}, ...]
ALTER TABLE completed_trials ADD COLUMN mesh_terms TEXT;

-- The MeSH descriptor is the identity of an indication. Name stays human-readable and
-- editable; mesh_id is what joins.
ALTER TABLE indications ADD COLUMN mesh_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_indications_mesh
    ON indications(mesh_id) WHERE mesh_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_asset_indications_asset
    ON asset_indications(asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_indications_pair
    ON asset_indications(asset_id, indication_id, COALESCE(region, ''));

-- Overrides, following the trial_asset_map pattern already used for the harder problem of
-- binding a study to an asset. A registry entry that names the wrong condition, or an
-- indication the derivation cannot see, is corrected here and never overwritten by a run.
CREATE TABLE IF NOT EXISTS asset_indication_overrides (
    asset_id     INTEGER NOT NULL REFERENCES assets(id),
    indication_id INTEGER NOT NULL REFERENCES indications(id),
    phase        TEXT,          -- forces the phase where the registry understates it
    exclude      INTEGER DEFAULT 0,  -- 1 removes a pair the derivation gets wrong
    note         TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (asset_id, indication_id)
);
