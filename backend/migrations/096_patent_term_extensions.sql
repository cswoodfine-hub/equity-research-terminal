-- Patent term extensions under 35 USC 156, from the USPTO's two published lists.
--
-- One patent per product can be extended, and the holder extends the one claiming the
-- molecule, so a certificate identifies the compound patent the Orange Book's "drug
-- substance" flag leaves ambiguous (pte.py). Applications are kept beside them for
-- display: a holder may apply on several patents and elect one, so a pending
-- application does not identify the patent on its own.
--
-- Universe-wide and keyed by patent, matched to an asset through exclusivities.identifier
-- at read time. Current state, replaced on each live read; the snapshot keeps the counts.

CREATE TABLE IF NOT EXISTS patent_term_extensions (
    id               INTEGER PRIMARY KEY,
    patent           TEXT NOT NULL,      -- Orange Book shape: digits, or RE and digits
    kind             TEXT NOT NULL,      -- certificate | application
    trade_name       TEXT,
    original_expiry  TEXT,               -- certificates: the term before extension
    extension        TEXT,               -- certificates: as granted, "5 years", "1509 days"
    extended_expiry  TEXT,               -- certificates: original plus extension, a cross-check
    filed            TEXT,               -- applications: PTE application filing date
    application_number TEXT,             -- applications: the patent's US application number
    fetched_at       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pte_patent ON patent_term_extensions(patent, kind);
