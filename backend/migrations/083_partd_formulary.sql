-- Medicare Part D plan coverage per brand, from CMS's monthly Prescription Drug Plan
-- Formulary and Pharmacy Network Information file (fetchers/formulary_cms.py).
--
-- Medicare Part D plans only. CMS's methodology leaves out non-Part D plans, national
-- PACE plans, employer-sponsored plans and demonstration plans (MMPs are included), and
-- a plan whose data CMS suppressed appears in the plan file only. Coverage is counted in
-- formularies and plans, not in people: the file carries no enrolment, and a stand-alone
-- PDP covers far more members than a typical MA-PD plan.
--
-- The release is a 2.3 GB ZIP, but only five small members are read, by HTTP Range
-- requests: the basic drugs formulary, plan information and beneficiary cost files are
-- parsed, and the excluded drugs and indication based coverage files are counted only.
-- A brand is matched on its brand-specific RxCUIs (drug_codes rows with code_type
-- 'rxcui' and brand_specific = 1: SBD and BPCK), never on a clinical drug, which is
-- every manufacturer's.

-- What has been read from each monthly release. The daily refresh runs forced, so this,
-- not a snapshot, is the release guard: a release already here is never read again.
CREATE TABLE partd_formulary_releases (
    release_date         TEXT PRIMARY KEY,   -- posted date, from the ZIP's YYYY_YYYYMMDD name
    contract_year        INTEGER,            -- the plan year the release describes
    catalogue_date       TEXT,               -- the date in the data.json title
    zip_url              TEXT NOT NULL,
    member_date          TEXT,               -- the date in the member names, YYYYMMDD
    formularies          INTEGER,            -- distinct formularies in the basic file
    plans                INTEGER,            -- contract-plan-segments, unsuppressed
    plans_suppressed     INTEGER,
    rows_read            INTEGER,            -- basic formulary rows
    rows_kept            INTEGER,            -- of which on a book brand's RxCUI
    assets_listed        INTEGER,            -- assets on at least one formulary
    excluded_rows        INTEGER,            -- excluded drugs file: counted, not stored
    excluded_plans       INTEGER,
    excluded_book_rows   INTEGER,
    indication_rows      INTEGER,            -- indication based coverage file: counted
    indication_plans     INTEGER,
    indication_book_rows INTEGER,
    range_requests       INTEGER,
    bytes_read           INTEGER,
    fetched_at           TEXT DEFAULT (datetime('now'))
);

-- The plans of the newest release read, one row per contract, plan and segment, the
-- county rows collapsed. Replaced with each release.
CREATE TABLE partd_plans (
    contract_id  TEXT NOT NULL,
    plan_id      TEXT NOT NULL,
    segment_id   TEXT NOT NULL,
    formulary_id TEXT,
    plan_type    TEXT,               -- MA-PD for H and R contracts, PDP for S
    snp          TEXT,               -- 0 not a SNP, 1 chronic, 2 dual-eligible, 3 institutional
    states       TEXT,               -- comma-joined, local MA plans only
    counties     INTEGER,
    suppressed   INTEGER,            -- 1: CMS suppressed the plan's data
    release_date TEXT NOT NULL,
    PRIMARY KEY (contract_id, plan_id, segment_id)
);

-- The basic formulary rows of the book's brand RxCUIs, newest release only. Keyed by
-- formulary and RxCUI, not by asset: a co-marketed brand's RxCUI belongs to every owner
-- through drug_codes. Replaced with each release.
CREATE TABLE partd_formulary_entries (
    formulary_id      TEXT NOT NULL,
    rxcui             TEXT NOT NULL,
    formulary_version TEXT,
    ndc11             TEXT,          -- CMS's proxy NDC for the RxCUI
    tier              INTEGER,
    quantity_limit    INTEGER,
    ql_amount         TEXT,
    ql_days           TEXT,
    prior_auth        INTEGER,
    step_therapy      INTEGER,
    selected_drug     INTEGER,       -- a drug selected for Medicare price negotiation
    release_date      TEXT NOT NULL,
    PRIMARY KEY (formulary_id, rxcui)
);

-- One row per asset and release, never overwritten, so plan coverage has a history.
-- On each formulary the brand's best-placed RxCUI sets its tier, and a prior
-- authorisation, step therapy or quantity limit on any of its RxCUIs counts the
-- formulary. Plan counts are of unsuppressed plans. specialty_plans_listing counts the
-- plans whose cost file marks the brand's tier as a specialty tier; CMS notes plans are
-- not required to designate one.
CREATE TABLE partd_formulary_access (
    id                      INTEGER PRIMARY KEY,
    asset_id                INTEGER NOT NULL REFERENCES assets(id),
    release_date            TEXT NOT NULL,
    contract_year           INTEGER,
    formularies_total       INTEGER,
    formularies_listing     INTEGER,
    plans_total             INTEGER,
    plans_listing           INTEGER,
    mapd_plans_total        INTEGER,
    mapd_plans_listing      INTEGER,
    pdp_plans_total         INTEGER,
    pdp_plans_listing       INTEGER,
    tier_counts             TEXT,    -- JSON {tier: formularies}
    pa_formularies          INTEGER,
    st_formularies          INTEGER,
    ql_formularies          INTEGER,
    pa_plans                INTEGER,
    st_plans                INTEGER,
    ql_plans                INTEGER,
    specialty_plans_listing INTEGER,
    selected_drug           INTEGER, -- 1 when CMS flags the brand as negotiated
    rxcuis_known            INTEGER, -- the asset's brand RxCUIs
    rxcuis_listed           INTEGER, -- of which on at least one formulary
    ndc_mismatches          INTEGER, -- distinct proxy NDCs not among the asset's codes
    note                    TEXT,
    fetched_at              TEXT DEFAULT (datetime('now')),
    UNIQUE (asset_id, release_date)
);
CREATE INDEX idx_partd_formulary_access_release ON partd_formulary_access(release_date);
