-- Medicare Part D prescribing per marketed brand and data year, from the two CMS Part D
-- Prescribers datasets (fetchers/prescribers_cms.py). Medicare Part D only.
--
-- The national_* columns come from Prescribers by Geography and Drug, one national row
-- per brand: all prescribers, claims, standardised 30-day fills, drug cost and distinct
-- beneficiaries. Every year from 2020 is held. Where CMS lists a brand by container
-- (Repatha Sureclick, Syringe and Pushtronex) the containers are summed, which is exact
-- for claims, fills and cost, and an upper bound for prescribers and beneficiaries, since
-- one person can appear under two containers; cms_brands and presentations say so.
--
-- days_covered_share is national 30-day fills x 30 / (beneficiaries x 365). It is a
-- proxy, not a proportion of days covered: CMS counts a fill under 30 days as one 30-day
-- fill and caps one claim at twelve, and a patient who starts or stops mid-year lowers
-- it as surely as one who misses doses.
--
-- The file_* columns come from Prescribers by Provider and Drug, read for the newest year
-- only and reduced in memory: the per-prescriber rows, names and NPIs are never stored.
-- That file leaves out any prescriber with fewer than 11 claims for the drug, so every
-- file_* figure, the NPI deciles among them, describes that population and not all
-- prescribers. prescribers_by_volume_decile is held null until CMS's definition of its
-- national prescriber count says how the unseen prescribers would rank.

CREATE TABLE partd_prescribing (
    id                           INTEGER PRIMARY KEY,
    asset_id                     INTEGER NOT NULL REFERENCES assets(id),
    data_year                    INTEGER NOT NULL,
    cms_brands                   TEXT,     -- JSON list of the [brand, ingredient] rows summed
    presentations                INTEGER,
    national_prescribers         INTEGER,
    national_claims              INTEGER,
    national_fills_30d           REAL,
    national_drug_cost           REAL,     -- gross: plan, patient, subsidy and third party
    national_beneficiaries       INTEGER,
    national_benes_ge65          INTEGER,
    national_note                TEXT,     -- upper bounds and suppressed counts, in words
    days_covered_share           REAL,     -- the national proxy above
    file_status                  TEXT,     -- null not read | pending | complete | incomplete
    file_prescribers             INTEGER,  -- distinct NPIs in the file, presentations unioned
    file_claims                  INTEGER,
    file_fills_30d               REAL,
    file_day_supply              INTEGER,
    file_drug_cost               REAL,
    file_claims_share            REAL,     -- file_claims / national_claims
    top1pct_claims_share         REAL,     -- file population; null under 100 prescribers
    top10pct_claims_share        REAL,     -- file population; null under 10 prescribers
    prescribers_for_50pct        INTEGER,
    prescribers_for_80pct        INTEGER,
    hhi                          REAL,     -- prescriber concentration, 0 to 10,000
    claims_share_by_npi_decile   TEXT,     -- JSON[10], heaviest tenth of file NPIs first
    median_claims_per_prescriber REAL,
    prescribers_by_volume_decile TEXT,     -- held null, see above
    volume_decile_note           TEXT,
    days_supply_per_claim        REAL,
    days_covered_share_file      REAL,     -- file day supply / (beneficiaries x 365), a
                                           -- lower bound, only at 95% claims coverage
    file_note                    TEXT,
    source                       TEXT DEFAULT 'cms_partd_prescribers',
    fetched_at                   TEXT DEFAULT (datetime('now')),
    file_fetched_at              TEXT,
    UNIQUE (asset_id, data_year)
);
CREATE INDEX idx_partd_prescribing_year ON partd_prescribing(data_year);

-- The prescriber specialties of a brand's file population: every specialty with at least
-- 1% of the brand's file claims, and one 'Other' row for the rest.
CREATE TABLE partd_prescriber_specialties (
    id           INTEGER PRIMARY KEY,
    asset_id     INTEGER NOT NULL REFERENCES assets(id),
    data_year    INTEGER NOT NULL,
    specialty    TEXT NOT NULL,
    prescribers  INTEGER,
    claims       INTEGER,
    claims_share REAL,
    UNIQUE (asset_id, data_year, specialty)
);

-- What has been read from each CMS dataset and year. The daily refresh runs forced, so
-- this, not a snapshot, is the release guard: a year is read again only when CMS changes
-- it, and a new year is noticed when the series' row count changes.
CREATE TABLE partd_prescriber_releases (
    dataset            TEXT NOT NULL,      -- geography | provider
    data_year          INTEGER NOT NULL,
    uuid               TEXT,               -- the API id pinned to the year
    series_uuid        TEXT,               -- the 'latest' id, newest year only
    total_rows         INTEGER,            -- /data/stats total_rows when read
    catalogue_modified TEXT,               -- data.json's modified date when read
    rows_read          INTEGER,
    fetched_at         TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (dataset, data_year)
);
