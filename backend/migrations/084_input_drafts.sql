-- New revenue the model does not hold yet, drafted from filed sources for an analyst to
-- approve (backend/input_drafts.py). Phase 1 is acquisitions: a closing read from what the
-- acquirer filed, and forecast rows drafted from what the target filed. Nothing here
-- reaches a valuation until a row is accepted, which writes it to assumptions (or
-- other_claims) and to the matching seed file under data/.

-- Every filing read for a closing, once, whatever it said, so a filing is never read or
-- drafted twice. A refresh reads only filings dated on or after the company's newest
-- read, so filed_date is kept; the one-off catch-up reads every unread filing.
CREATE TABLE closing_reads (
    accession  TEXT PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    form_type  TEXT,
    filed_date TEXT,
    verdict    TEXT,               -- acquisition, disposition, none, unreadable
    read_at    TEXT DEFAULT (datetime('now'))
);

-- One closed acquisition per company and target, from the first filing that states it.
CREATE TABLE deal_closings (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id),
    target            TEXT NOT NULL,          -- as the filing names it
    target_key        TEXT NOT NULL,          -- lower case, legal suffix dropped
    closing_date      TEXT,                   -- YYYY-MM-DD, or YYYY-MM where the filing gives a month
    trigger_accession TEXT NOT NULL,
    trigger_kind      TEXT NOT NULL,          -- 8-K item 2.01, 8-K press release, 6-K, 10-Q, 10-K, 20-F
    trigger_url       TEXT,
    quote             TEXT,                   -- the sentence that states the completion
    target_cik        TEXT,
    target_status     TEXT,                   -- public, private
    context           TEXT,                   -- JSON: linked assets, LOE, projections, revenue history
    note              TEXT,
    drafted_at        TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    UNIQUE(company_id, target_key)
);

-- One proposed row per key. destination says where an accepted row is written.
CREATE TABLE input_drafts (
    id                INTEGER PRIMARY KEY,
    company_id        INTEGER NOT NULL REFERENCES companies(id),
    closing_id        INTEGER REFERENCES deal_closings(id),
    trigger_accession TEXT NOT NULL,
    trigger_kind      TEXT NOT NULL,
    destination       TEXT NOT NULL,          -- assumptions, other_claims
    asset_id          INTEGER REFERENCES assets(id),
    proposed_asset    TEXT,                   -- a product the book does not hold yet
    key               TEXT NOT NULL,          -- assumption key, or the other_claims item
    value             REAL,
    text_value        TEXT,
    unit              TEXT,
    year              INTEGER,
    indication        TEXT,
    region            TEXT NOT NULL DEFAULT 'US',
    scenario          TEXT NOT NULL DEFAULT 'base',
    source            TEXT,                   -- the filing: form, accession, section
    source_url        TEXT,
    quote             TEXT,                   -- the sentence or table cells the value came from
    evidence          TEXT,                   -- filed, measured, published, analogue, convention, judgement
    note              TEXT,
    existing_value    REAL,                   -- the book's row for the same key, side by side
    existing_text     TEXT,
    existing_source   TEXT,
    status            TEXT NOT NULL DEFAULT 'draft',  -- draft, incomplete, accepted, edited, rejected
    created_at        TEXT DEFAULT (datetime('now')),
    decided_at        TEXT
);
CREATE UNIQUE INDEX idx_input_drafts_key ON input_drafts(
    trigger_accession, destination, IFNULL(asset_id, 0), IFNULL(proposed_asset, ''), key,
    IFNULL(year, 0), region, scenario);
CREATE INDEX idx_input_drafts_company ON input_drafts(company_id, status);
