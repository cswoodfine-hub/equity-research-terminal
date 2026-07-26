-- M&A, licensing and collaboration deals, read from the filings that announce them. A
-- US 8-K names only the item category ("Material agreement signed"), not the party, so
-- the counterparty, the value and what the deal is for live in the EX-99 press release
-- it attaches; a foreign filer's 6-K carries the release in the body. Both are read over
-- the model seam, with the PDUFA guard: the counterparty and a quote must appear in the
-- filing, and a value is kept only when it appears verbatim, so no number is invented.
-- Additive only.
--
-- One or more rows per processed filing: a single 8-K announces one deal, but an
-- earnings release can list several, so the accession is not unique. A filing is read
-- once, guarded by the extractor skipping any accession already present. deal_type is
-- acquisition, licensing, collaboration or divestiture for a real deal, or 'none' for a
-- filing that was read and announced no deal, which marks it done so it is not fetched
-- again. The note reads the signed rows for a company.

CREATE TABLE deals (
    id           INTEGER PRIMARY KEY,
    accession    TEXT,
    company_id   INTEGER REFERENCES companies(id),
    deal_type    TEXT,            -- acquisition, licensing, collaboration, divestiture, none
    counterparty TEXT,            -- the other party, as the filing names it
    value        TEXT,            -- deal value as written, e.g. "$7 billion", or null
    area         TEXT,            -- therapeutic area, asset or modality, or null
    event_date   TEXT,            -- the filing date, the day the market saw it
    quote        TEXT,            -- the announcing sentence, verbatim
    source_url   TEXT,
    is_curated   INTEGER DEFAULT 0,
    fetched_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_deals_company ON deals(company_id, event_date);
CREATE INDEX idx_deals_signed ON deals(deal_type);
CREATE INDEX idx_deals_accession ON deals(accession);
