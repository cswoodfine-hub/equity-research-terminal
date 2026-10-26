-- A row's first write is one event, however many times a database is rebuilt.
--
-- history.py rebuild restores assumption_edits but not assumptions, which is deliberate:
-- the ledger is history and the table reseeds from data/assumptions/*.csv. The effect
-- nobody checked is that load_seeds then finds an empty table, recreates all 11,575 rows
-- and logs every one of them again. The cloud book went from 11,575 ledger rows to
-- 23,150 in a single run on 2026-10-26, 6,025 natural keys carrying a duplicate create,
-- and it compounds every day the refresh runs.
--
-- A create for a natural key that already has one is the same event being recorded
-- twice, not a new one, so the key is made unique for seed rows and the writer ignores a
-- second. Only seed rows: an analyst can legitimately create, delete and create a row
-- again, and that is three events.
--
-- The earliest row per key is kept, because the first write is the one that happened.
DELETE FROM assumption_edits
 WHERE reason = 'initial_seed' AND id NOT IN (
   SELECT MIN(id) FROM assumption_edits WHERE reason = 'initial_seed'
    GROUP BY asset_id, IFNULL(indication_id, 0), region, scenario, key, IFNULL(year, 0));

CREATE UNIQUE INDEX IF NOT EXISTS idx_assumption_edits_seed_once
    ON assumption_edits(asset_id, IFNULL(indication_id, 0), region, scenario, key,
                        IFNULL(year, 0))
 WHERE reason = 'initial_seed';
