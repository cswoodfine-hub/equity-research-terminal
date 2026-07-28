-- Who runs the company, and when that changed.
--
-- Item 5.02 filings are already in `filings`, titled "Director or officer change" and
-- treated as housekeeping. Most of them are. This table holds the ones that are not:
-- a named senior role, and whether someone arrived in it or left it.
--
-- The sentence that produced the row is stored, because the parse is a judgement made
-- from prose and "why does it say the CFO left" has to be answerable from the row.
-- Keyed on the accession plus role plus kind, so re-reading a filing cannot duplicate
-- an event, and one filing can report a departure and the appointment that follows it.

CREATE TABLE leadership_changes (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    accession   TEXT NOT NULL,
    filed_date  TEXT,
    role        TEXT NOT NULL,        -- "Chief executive", "Chief financial", ...
    kind        TEXT NOT NULL,        -- departure | appointment
    evidence    TEXT,                 -- the sentence it was read from
    url         TEXT,
    detected_at TEXT DEFAULT (datetime('now')),
    UNIQUE (accession, role, kind)
);
CREATE INDEX idx_leadership_company ON leadership_changes(company_id, filed_date);
