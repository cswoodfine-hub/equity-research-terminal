-- Claims on the company outside cash and debt: a pension deficit, contingent
-- consideration still owed, a minority's slice of a consolidated subsidiary, a business
-- held at equity (backend/other_claims.py). ``sign`` is how the claim enters equity:
-- -1 deducts, +1 adds. ``value`` is in the millions the filer reports in, the same unit
-- as net cash. Written from the SEC Financial Statement Data Sets and the curated file,
-- so the valuation reads rows rather than parsing a hundred megabytes per company.
CREATE TABLE other_claims (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    item       TEXT NOT NULL,
    label      TEXT,
    value      REAL NOT NULL,
    sign       INTEGER NOT NULL,
    unit       TEXT,
    as_of      TEXT,
    basis      TEXT,
    source     TEXT,
    note       TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(company_id, item)
);
