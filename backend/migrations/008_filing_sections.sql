-- Filing text, the words behind the numbers. A 10-K's risk factors and MD&A are prose
-- with no structured field, and a new or rewritten risk factor is a real signal the
-- numeric diff cannot see. This table holds the two sections extracted from each annual
-- and quarterly filing so the diff engine can compare a filing to the last of its form.
-- Additive only.
--
-- One row per filing and section, keyed on the accession, which never changes once a
-- filing is public, so a section is written once and read as history. The text is kept
-- whole; the diff is computed at read time. Foreign filers (20-F) lay their sections out
-- under different item numbers and are left for a later pass.

CREATE TABLE filing_sections (
    id         INTEGER PRIMARY KEY,
    company_id INTEGER REFERENCES companies(id),
    accession  TEXT,
    form_type  TEXT,
    filed_date TEXT,
    section    TEXT,               -- risk_factors, mdna
    char_count INTEGER,
    text       TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    UNIQUE(accession, section)
);
CREATE INDEX idx_filing_sections ON filing_sections(company_id, section, filed_date);
