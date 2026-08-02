-- Pharma equity research terminal: database schema
-- Target: SQLite (portable to DuckDB; see notes on JSON columns below).
-- Design principle: the unit of analysis is the asset-indication pair,
-- not the company. Snapshots capture tracked fields on every refresh so the
-- diff between snapshots produces a proprietary time series of changes.
--
-- Notes for DuckDB: referenced tables must exist before referencing tables,
-- so the order below matters. JSON is stored as TEXT here for portability;
-- swap to the JSON type on DuckDB if you prefer.

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------
-- Reference tables
-- ------------------------------------------------------------------

CREATE TABLE companies (
    id                        INTEGER PRIMARY KEY,
    ticker                    TEXT NOT NULL UNIQUE,   -- ticker you recognise / use
    name                      TEXT NOT NULL,
    primary_exchange          TEXT,
    country                   TEXT,
    reporting_currency        TEXT,                   -- currency the accounts are in
    us_adr_ticker             TEXT,                   -- US ADR symbol if different
    cik                       TEXT,                   -- SEC CIK, 10-digit zero-padded; resolve on setup
    is_foreign_private_issuer INTEGER DEFAULT 0,      -- files 20-F / 6-K, not 10-K / 8-K
    is_sec_filer              INTEGER DEFAULT 1,       -- 0 for names with no SEC registration (Roche, Bayer)
    ir_rss_url                TEXT,                   -- investor-relations news feed
    created_at                TEXT DEFAULT (datetime('now')),
    updated_at                TEXT DEFAULT (datetime('now'))
);

CREATE TABLE assets (
    id               INTEGER PRIMARY KEY,
    owner_company_id INTEGER NOT NULL REFERENCES companies(id),
    generic_name     TEXT,
    brand_name       TEXT,
    internal_code    TEXT,          -- development code, e.g. LY3502970
    modality         TEXT,          -- small molecule, mAb, ADC, gene therapy, siRNA, bispecific
    mechanism        TEXT,          -- mechanism of action, free text
    target           TEXT,          -- molecular target
    is_marketed      INTEGER DEFAULT 0,
    notes            TEXT,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_assets_owner ON assets(owner_company_id);

CREATE TABLE indications (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL UNIQUE,
    therapeutic_area TEXT,          -- oncology, immunology, cardiometabolic, CNS, rare disease
    icd10            TEXT
);

-- The core object: one row per asset in one indication in one region.
CREATE TABLE asset_indications (
    id               INTEGER PRIMARY KEY,
    asset_id         INTEGER NOT NULL REFERENCES assets(id),
    indication_id    INTEGER NOT NULL REFERENCES indications(id),
    phase            TEXT,          -- Preclinical, Phase 1, Phase 1/2, Phase 2, Phase 3, Filed, Approved
    development_status TEXT,        -- active, on hold, discontinued, approved
    is_lead          INTEGER DEFAULT 0,
    region           TEXT,          -- US, EU, global
    first_seen_phase TEXT,          -- phase when first ingested, for advance detection
    updated_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id, indication_id, region)
);
CREATE INDEX idx_ai_asset ON asset_indications(asset_id);
-- "Next catalyst" is derived, not stored: MIN(expected_date) from catalysts
-- where status = 'pending' for the pair. Keeps the FK graph acyclic.

CREATE TABLE asset_economics (
    id                 INTEGER PRIMARY KEY,
    asset_id           INTEGER NOT NULL REFERENCES assets(id),
    partner_company_id INTEGER REFERENCES companies(id),
    deal_type          TEXT,        -- licence, collaboration, acquisition
    economics          TEXT,        -- royalty %, milestone value, profit split, free text
    region             TEXT,
    effective_date     TEXT,
    source_url         TEXT
);

-- ------------------------------------------------------------------
-- Market data
-- ------------------------------------------------------------------

CREATE TABLE prices (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    as_of      TEXT NOT NULL,       -- timestamp of the quote
    close      REAL,
    open       REAL,
    high       REAL,
    low        REAL,
    volume     INTEGER,
    market_cap REAL,
    source     TEXT,                -- yfinance, fmp
    -- Bar size: 1d for the five-year daily series, 15m for the intraday window.
    -- Every query says which it wants, so intraday bars can never interleave into
    -- the daily chart. A 15m as_of carries a time, so the key below still separates
    -- them without needing to be widened.
    interval   TEXT NOT NULL DEFAULT '1d',
    UNIQUE(company_id, as_of)
);
CREATE INDEX idx_prices_company ON prices(company_id, as_of);

CREATE TABLE financials (
    id            INTEGER PRIMARY KEY,
    company_id    INTEGER NOT NULL REFERENCES companies(id),
    period_end    TEXT NOT NULL,    -- reporting period end date
    period_type   TEXT,             -- Q, FY
    metric        TEXT NOT NULL,    -- Revenues, NetIncomeLoss, ResearchAndDevelopmentExpense
    value         REAL,
    unit          TEXT,             -- USD, EUR
    fiscal_year   INTEGER,
    fiscal_period TEXT,             -- Q1..Q4, FY
    source        TEXT,             -- edgar_companyfacts, ir
    accession     TEXT,
    UNIQUE(company_id, metric, period_end, period_type)
);
CREATE INDEX idx_fin_company ON financials(company_id, metric, period_end);

CREATE TABLE consensus_estimates (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    metric     TEXT NOT NULL,       -- EPS, Revenue
    period     TEXT NOT NULL,       -- FY2026, FY2027
    value      REAL,
    currency   TEXT,
    source     TEXT,                -- fmp
    as_of      TEXT NOT NULL,       -- estimate date, so revisions are visible
    UNIQUE(company_id, metric, period, as_of)
);

-- ------------------------------------------------------------------
-- Clinical and regulatory
-- ------------------------------------------------------------------

CREATE TABLE trials (
    id                      INTEGER PRIMARY KEY,
    nct_id                  TEXT NOT NULL UNIQUE,
    asset_id                INTEGER REFERENCES assets(id),         -- mapped; null until matched
    sponsor_company_id      INTEGER REFERENCES companies(id),
    title                   TEXT,
    phase                   TEXT,
    overall_status          TEXT,   -- Recruiting, Active not recruiting, Completed, Terminated
    primary_completion_date TEXT,   -- slips here are a real signal
    -- ACTUAL or ESTIMATED. Without it a past date is unreadable: an actual one means
    -- the primary endpoint was reached and the trial runs on for survival follow-up,
    -- which is normal and can last a decade. An estimated one in the past means the
    -- forecast was missed, which is a signal.
    primary_completion_type TEXT,
    completion_date         TEXT,
    enrollment              INTEGER,
    conditions              TEXT,   -- JSON array of condition strings
    last_update_posted      TEXT,
    source                  TEXT DEFAULT 'clinicaltrials_v2',
    fetched_at              TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_trials_asset ON trials(asset_id);

-- Manual override for trial-to-asset mapping, since name matching is imperfect.
CREATE TABLE trial_asset_map (
    nct_id   TEXT PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id),
    note     TEXT
);

CREATE TABLE approvals (
    id                 INTEGER PRIMARY KEY,
    asset_id           INTEGER REFERENCES assets(id),
    region             TEXT,        -- US, EU
    agency             TEXT,        -- FDA, EMA
    approval_date      TEXT,
    indication_text    TEXT,
    application_number TEXT,
    source             TEXT DEFAULT 'openfda',
    fetched_at         TEXT DEFAULT (datetime('now'))
);

CREATE TABLE exclusivities (
    id              INTEGER PRIMARY KEY,
    asset_id        INTEGER REFERENCES assets(id),
    region          TEXT,
    protection_type TEXT,           -- patent, regulatory exclusivity
    identifier      TEXT,           -- patent number or exclusivity code
    expiry_date     TEXT,           -- powers the LOE cliff chart
    source          TEXT,           -- orange_book, purple_book
    fetched_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_excl_asset ON exclusivities(asset_id, expiry_date);

-- ------------------------------------------------------------------
-- Catalysts, filings, news
-- ------------------------------------------------------------------

CREATE TABLE catalysts (
    id                  INTEGER PRIMARY KEY,
    company_id          INTEGER REFERENCES companies(id),
    asset_id            INTEGER REFERENCES assets(id),
    asset_indication_id INTEGER REFERENCES asset_indications(id),
    catalyst_type       TEXT,       -- PDUFA, data readout, EMA decision, AdCom, conference
    expected_date       TEXT,
    date_confidence     TEXT,       -- confirmed, estimated, quarter, half
    title               TEXT,
    description         TEXT,
    is_curated          INTEGER DEFAULT 1,  -- 1 hand entered, 0 auto extracted, review before trusting
    source_url          TEXT,
    status              TEXT DEFAULT 'pending',  -- pending, passed, met, missed
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_catalysts_date ON catalysts(expected_date, status);

-- Product revenue, hand entered, for the same reason catalysts are: no free source
-- carries it. Companies do publish it, in the product table of the 10-K, and they tag
-- it against a product axis in XBRL, but the companyfacts API collapses those
-- dimensions and returns the consolidated Revenues line alone. Splitting that total
-- across products by any rule would be an estimate wearing the clothes of a fact, so
-- the number is typed in from the filing or it is absent.
--
-- Absent is a first-class state here. Revenue at risk is reported against the share of
-- products it covers, never as though the uncovered ones were worth nothing.
CREATE TABLE asset_revenue (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id),
    fiscal_year INTEGER NOT NULL,
    -- What stretch the figure covers. A quarter stored as if it were the year
    -- understates a product fourfold, so the period is part of the key.
    period      TEXT NOT NULL DEFAULT 'FY',  -- FY, Q1..Q4, H1
    period_end  TEXT,                        -- ISO date the period closes on
    value       REAL,               -- as reported, not scaled
    unit        TEXT,               -- reporting currency, e.g. USD
    source      TEXT,               -- where it was read from, e.g. "FY2025 10-K"
    note        TEXT,
    is_curated  INTEGER DEFAULT 1,  -- 1 hand entered; 0 fetched
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id, fiscal_year, period)
);
CREATE INDEX idx_asset_revenue ON asset_revenue(asset_id, fiscal_year);
-- The period index is created by migration 034, not here. schema.sql runs against an
-- existing database before the migrations do, and on one that has not been migrated yet
-- there is no period column for this index to name.


CREATE TABLE filings (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    form_type  TEXT,                -- 8-K, 6-K, 10-K, 10-Q, 20-F
    filed_date TEXT,
    accession  TEXT UNIQUE,
    title      TEXT,
    url        TEXT,
    source     TEXT DEFAULT 'edgar',
    fetched_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_filings_company ON filings(company_id, filed_date);

CREATE TABLE news (
    id           INTEGER PRIMARY KEY,
    company_id   INTEGER REFERENCES companies(id),
    source       TEXT,
    title        TEXT,
    url          TEXT UNIQUE,
    published_at TEXT,
    fetched_at   TEXT DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------------
-- Refresh, snapshots, diffs  (the core of the product)
-- ------------------------------------------------------------------

-- One row per refresh action, with per-source status for the UI.
CREATE TABLE refresh_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    status      TEXT,               -- running, complete, partial, failed
    detail      TEXT                -- JSON: per-source rows fetched, errors, timings
);

-- Point-in-time capture of tracked fields for any entity, written every refresh.
-- Never overwrite: this table is the change history.
CREATE TABLE snapshots (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,   -- prices, trials, financials, asset_indications, ...
    entity_type    TEXT NOT NULL,   -- company, trial, asset_indication
    entity_key     TEXT NOT NULL,   -- natural key: ticker, nct_id, etc.
    captured_at    TEXT NOT NULL DEFAULT (datetime('now')),
    payload        TEXT NOT NULL,   -- JSON of the tracked fields at capture time
    refresh_run_id INTEGER REFERENCES refresh_runs(id)
);
CREATE INDEX idx_snapshots_entity ON snapshots(entity_type, entity_key, captured_at);

-- Computed diffs between consecutive snapshots of the same entity.
CREATE TABLE changes (
    id             INTEGER PRIMARY KEY,
    entity_type    TEXT NOT NULL,
    entity_key     TEXT NOT NULL,
    field          TEXT NOT NULL,
    old_value      TEXT,
    new_value      TEXT,
    change_type    TEXT,            -- status_change, date_slip, phase_advance, new_filing
    significance   TEXT,            -- high, medium, low
    detected_at    TEXT NOT NULL DEFAULT (datetime('now')),
    refresh_run_id INTEGER REFERENCES refresh_runs(id),
    acknowledged   INTEGER DEFAULT 0
);
CREATE INDEX idx_changes_detected ON changes(detected_at, significance);

-- Generated morning notes, tied back to the changes that produced them.
CREATE TABLE insights (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER REFERENCES companies(id),
    generated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    horizon           TEXT,         -- daily, on_demand
    body              TEXT NOT NULL,
    source_change_ids TEXT,         -- JSON array of changes.id
    model             TEXT,
    refresh_run_id    INTEGER REFERENCES refresh_runs(id)
);

-- ------------------------------------------------------------------
-- Valuation  (phase 2 stub: rNPV assumptions, editable in the UI)
-- ------------------------------------------------------------------

CREATE TABLE valuation_assumptions (
    id                  INTEGER PRIMARY KEY,
    asset_indication_id INTEGER NOT NULL REFERENCES asset_indications(id),
    wacc                REAL,
    pos                 REAL,       -- composite probability of success
    peak_sales          REAL,
    launch_year         INTEGER,
    years_to_peak       INTEGER,
    patent_expiry       TEXT,
    updated_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_indication_id)
);
