-- A marketed product the Orange Book lists with no live patent or exclusivity. The
-- book carries every unexpired patent an NDA holder has submitted, so its silence on a
-- marketed product is a finding: nothing protects it, and its loss of exclusivity is
-- in the past. Symbicort, Crestor and Zytiga were each read as having no LOE at all,
-- and their forecasts ran to a perpetuity, because a product with nothing to list was
-- dropped before it reached the table.
CREATE TABLE IF NOT EXISTS orange_book_listings (
    asset_id       INTEGER PRIMARY KEY REFERENCES assets(id),
    appl_code      TEXT,
    approval_date  TEXT,
    applicant      TEXT,
    live_rows      INTEGER NOT NULL DEFAULT 0,
    fetched_at     TEXT DEFAULT (datetime('now'))
);
