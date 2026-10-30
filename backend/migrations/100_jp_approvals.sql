-- Japanese new drug approvals, from the PMDA's English "List of Approved Products".
--
-- A substance's first Japanese approval as a new active ingredient starts its
-- re-examination period, eight years (ten for an orphan drug) in which no generic can
-- be filed (Act on Pharmaceuticals and Medical Devices, Art. 14-4). That is the floor
-- under a product's Japanese exclusivity, as the EMA's first authorisation is under
-- Europe's. The list runs from April 2004 and is one PDF, replaced as months are added.
CREATE TABLE IF NOT EXISTS jp_approvals (
    id                 INTEGER PRIMARY KEY,
    approved_on        TEXT NOT NULL,      -- ISO date
    entry              TEXT NOT NULL,      -- the list's row, whitespace collapsed
    is_new_ingredient  INTEGER NOT NULL,   -- the row's note says "new active ingredient"
    is_orphan          INTEGER NOT NULL,   -- the row's note says "[Orphan drug]"
    release            TEXT,               -- the PDF it was read from
    fetched_at         TEXT DEFAULT (datetime('now')),
    UNIQUE (approved_on, entry)
);

-- One row per PDF read, so a release already read is never downloaded again.
CREATE TABLE IF NOT EXISTS jp_approval_releases (
    url         TEXT PRIMARY KEY,
    label       TEXT,                      -- "April 2004 to February 2026"
    entries     INTEGER,
    fetched_at  TEXT DEFAULT (datetime('now'))
);
