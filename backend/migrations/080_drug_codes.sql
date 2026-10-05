-- The codes the payer files key a drug on, per marketed asset, from RxNav (NLM).
--
-- The Part D formulary lists a drug by RxCUI and Medicaid's State Drug Utilization Data
-- by NDC, and the book held neither: ndc_products stores a brand and an application
-- number, negotiated_prices covers only the drugs CMS negotiated. fetchers/codes_rxnav.py
-- sends each marketed asset's FDA application number to RxNav and stores what comes
-- back: the RxCUIs filed under it, and the NDC product codes RxNorm has ever attached to
-- them, repackagers included, with the first and last month each was listed.
--
-- One row per asset and code. A code two assets claim stays with each one its RxNorm name
-- names: a co-marketed product keeps it on both, a kit component on neither. An unbranded
-- concept (an authorised generic's clinical drug) carries only the NDCs marketed under the
-- asset's own application, never every manufacturer's. Rows marked curated come from
-- data/drug_code_overrides.csv and are never replaced by a fetch.

CREATE TABLE drug_codes (
    id                 INTEGER PRIMARY KEY,
    asset_id           INTEGER NOT NULL REFERENCES assets(id),
    code_type          TEXT NOT NULL,      -- rxcui | ndc9
    code               TEXT NOT NULL,      -- an RxCUI, or a product code 'LLLLL-PPPP'
    tty                TEXT,               -- RxNorm term type: SBD, BPCK, SCD, GPCK; for ndc9, its RxCUI's
    name               TEXT,               -- RxNorm name of the RxCUI, or of the one an ndc9 sits under
    rxcui              TEXT,               -- ndc9 rows: the RxCUI the product code sits under
    brand_specific     INTEGER,            -- 1 for SBD and BPCK and the product codes under them
    labeler_code       TEXT,               -- ndc9 rows: the five-digit labeler
    labeler_name       TEXT,               -- ndc9 rows: as RxNav names it on an active NDC, else null
    first_ym           TEXT,               -- YYYYMM, first month RxNorm listed the code
    last_ym            TEXT,               -- YYYYMM, last month RxNorm listed it
    is_owner_labeler   INTEGER,            -- 1 the company's own label, 0 another labeler, null unknown
    basis              TEXT NOT NULL,      -- rxnav_application | rxnav_brand_name | curated
    application_number TEXT,               -- the number RxNav returned the code for
    source_note        TEXT,               -- curated rows: where the code was read
    fetched_at         TEXT DEFAULT (datetime('now')),
    UNIQUE (asset_id, code_type, code)
);
CREATE INDEX idx_drug_codes_code ON drug_codes(code_type, code);

-- When each asset was last looked up, and with which numbers, including the lookups that
-- found nothing. The daily refresh runs forced, so this, not a snapshot, is what keeps a
-- month-old lookup from being repeated every day.
CREATE TABLE drug_code_lookups (
    asset_id            INTEGER PRIMARY KEY REFERENCES assets(id),
    application_numbers TEXT,              -- the numbers asked about, sorted and comma-joined
    basis               TEXT,              -- the route that found codes, or null when none did
    rxcuis              INTEGER,
    ndc9s               INTEGER,
    rxnorm_version      TEXT,              -- RxNav's /version at lookup time
    note                TEXT,
    looked_up_at        TEXT DEFAULT (datetime('now'))
);
