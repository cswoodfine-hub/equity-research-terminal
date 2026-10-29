-- Every row of the FDA Paragraph IV list, not only the earliest date per drug.
--
-- patent_challenges keeps one row per tracked asset, the challenged state the LOE view
-- reads. The list carries more than that, and since FDA moved it from a PDF to a
-- spreadsheet (the 2026-09-28 issue) every column reads cleanly: how many ANDAs were
-- filed, the 180-day status, when the first applicant was approved, when the first filer
-- began commercial marketing, and when the last qualifying patent expires. The marketing
-- date is a generic launch that happened, which is what a backtest of the LOE date and a
-- measured erosion curve both need, and it is wanted for every drug on the list, not only
-- the ones in the universe. So this table is keyed by the list's own row, not by asset.
--
-- Current state, replaced on each live read of the list; the snapshot keeps the history.

CREATE TABLE IF NOT EXISTS paragraph_iv_list (
    id                   INTEGER PRIMARY KEY,
    list_date            TEXT,      -- the issue date in the sheet's title, ISO
    drug_name            TEXT,
    dosage_form          TEXT,
    strength             TEXT,
    rld_name             TEXT,      -- the reference drug as the list names it
    application_number   TEXT,      -- internal_code shape, e.g. NDA202155; null if the list gives none
    submission_date      TEXT,      -- first Paragraph IV certification; null for Pre-MMA
    pre_mma              INTEGER NOT NULL DEFAULT 0,
    anda_count           INTEGER,
    status_180           TEXT,      -- Eligible, Extinguished, Deferred, Non-Forfeiture, as listed
    status_180_posted    TEXT,
    first_approval       TEXT,      -- first applicant approval
    first_marketing      TEXT,      -- first commercial marketing by the first filer
    last_patent_expiry   TEXT,      -- expiration of the last qualifying patent
    fetched_at           TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_piv_list_appno ON paragraph_iv_list(application_number);
