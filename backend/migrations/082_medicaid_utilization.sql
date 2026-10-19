-- Medicaid prescriptions by product code and quarter, from the State Drug Utilization
-- Data (fetchers/utilization_medicaid.py). Medicaid fee-for-service and managed care
-- only, and gross: the dictionary says the amounts are "not reduced or affected by
-- Medicaid rebates", so they are volume, never revenue.
--
-- Only the national rows (state 'XX') of the two newest full years are read. Package
-- NDCs are summed to the product code 'LLLLL-PPPP' (drug_codes.code where code_type is
-- 'ndc9'). The rows are keyed by product code, not by asset: one code can belong to two
-- assets (co-marketed Eliquis sits on Bristol-Myers Squibb's asset and Pfizer's), so an
-- asset's figures are a join to drug_codes at read time, and a corrected code map moves
-- them without a refetch. drug_codes.brand_specific says whether a code is the brand
-- (1) or an unbranded product under the brand's own application (0, an authorised
-- generic), and the two are kept apart when read.
--
-- A row is kept when its product code is in drug_codes or its labeler is one of the
-- book's own labelers (drug_codes.is_owner_labeler = 1), so a code the map misses today
-- is already held when it is added. Every other row is counted and dropped.
--
-- CMS suppresses small package rows (suppression_used 'true', every figure blank; the
-- dictionary gives no threshold, and no unsuppressed national row read on 2026-10-05
-- had fewer than 11 prescriptions). A suppressed row adds to packages_suppressed and to
-- no sum, so a sum with packages_suppressed > 0 is a lower bound, and a product code
-- whose every package is suppressed has null sums, never 0.

CREATE TABLE medicaid_utilization (
    id                      INTEGER PRIMARY KEY,
    ndc9                    TEXT NOT NULL,      -- 'LLLLL-PPPP'
    labeler_code            TEXT NOT NULL,
    year                    INTEGER NOT NULL,
    quarter                 INTEGER NOT NULL,
    utilization_type        TEXT NOT NULL,      -- FFSU fee-for-service | MCOU managed care
    prescriptions           INTEGER,
    units_reimbursed        REAL,
    total_reimbursed        REAL,               -- before rebates
    medicaid_reimbursed     REAL,
    non_medicaid_reimbursed REAL,
    packages                INTEGER,            -- package NDCs CMS reported for the code
    packages_suppressed     INTEGER,            -- of which suppressed, in no sum
    product_name            TEXT,               -- CMS's 10-character listing name
    source                  TEXT DEFAULT 'medicaid_sdud',
    fetched_at              TEXT DEFAULT (datetime('now')),
    UNIQUE (ndc9, year, quarter, utilization_type)
);
CREATE INDEX idx_medicaid_utilization_year ON medicaid_utilization(year, quarter);

-- What has been read from each year's dataset. The daily refresh runs forced, so this,
-- not a snapshot, is the release guard. A year's rows are read again only when its
-- dataset id or modified date moves from the ones they were read under (dataset_id,
-- modified). Whether a year is full, that is whether it has national fourth-quarter
-- rows, is asked once per dataset id and modified date (the checked_* columns), so a
-- part year is not asked about every day.
CREATE TABLE medicaid_sdud_releases (
    year                 INTEGER PRIMARY KEY,
    dataset_id           TEXT,               -- the dataset the stored rows came from
    modified             TEXT,               -- its metastore modified date when read
    national_rows        INTEGER,            -- 'XX' rows read
    kept_rows            INTEGER,            -- of which kept: book codes or book labelers
    matched_rows         INTEGER,            -- of which on a drug_codes product code
    unmatched_owner_rows INTEGER,            -- a book labeler's rows on no mapped code
    fetched_at           TEXT,               -- null until national rows are stored
    full_year            INTEGER,            -- 1 when national Q4 rows exist
    checked_dataset_id   TEXT,
    checked_modified     TEXT,
    checked_at           TEXT
);
