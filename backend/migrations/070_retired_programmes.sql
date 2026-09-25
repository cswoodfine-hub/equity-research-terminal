-- Programmes a company has stopped, retired from the pipeline without being deleted.
--
-- Written by backend/discontinued.py from data/discontinued_programmes.csv on every
-- refresh, and rebuilt from the file each time, so a row here never outlives its line in
-- the file. The asset, its trials and its snapshots all stay; this table is what the
-- pipeline views, the late-stage coverage count and the valuation read to skip it.
--
-- asset_id is NOT NULL UNIQUE rather than the primary key. trial_mapping.prune_arms nulls
-- any asset_id column it reads as nullable, and SQLite reads an INTEGER PRIMARY KEY as
-- nullable, where setting it to NULL assigns a fresh row id: a retirement would have
-- landed on whichever asset held that id.

CREATE TABLE retired_programmes (
    id         INTEGER PRIMARY KEY,
    asset_id   INTEGER NOT NULL UNIQUE REFERENCES assets(id),
    stopped_on TEXT,              -- as the source dates the stop, day or month; null where it gives neither
    basis      TEXT NOT NULL,     -- the statement, filing or registry record, cited
    applied_at TEXT DEFAULT (datetime('now'))
);
