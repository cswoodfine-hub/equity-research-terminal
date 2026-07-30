-- Programmes a company describes in its own filing but has not put in a registered trial.
--
-- Every other route into the asset table needs a study or an approval, so anything
-- preclinical or newly IND-cleared could not exist in the model at all. Dyne names eight
-- programmes in its 10-Q and the app held the two with trials; DYNE-302 had FDA clearance
-- to begin a Phase 1 in FSHD and was nowhere.
--
-- stage is what the filing says in its own words: IND cleared, IND-enabling, development
-- candidate, preclinical, discovery. Never a phase. A phase means a registered trial, and
-- a registered trial belongs to the trial mapper; "we plan to evaluate DYNE-302 in a Phase
-- 1" is a plan, and recording it as Phase 1 would be inventing a study.
--
-- evidence is the sentence the row was read from, and accession says which filing carried
-- it, because a reader who does not believe the row needs to be able to check it.

CREATE TABLE filing_programmes (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    asset_id    INTEGER REFERENCES assets(id),
    code        TEXT NOT NULL,      -- the development code, e.g. DYNE-302
    stage       TEXT,               -- what the filing states, or null when it states none
    indication  TEXT,               -- the disease, as the filing names it
    evidence    TEXT,               -- the sentence this was read from
    accession   TEXT,               -- the filing that carried it
    form_type   TEXT,
    filed_date  TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(company_id, code)
);

CREATE INDEX idx_filing_programmes_company ON filing_programmes(company_id);
CREATE INDEX idx_filing_programmes_asset ON filing_programmes(asset_id);
