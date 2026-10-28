-- Every change to an analyst assumption, kept as it was made: who moved a number, what it
-- was before, why it moved, and what the valuation did about it.
--
-- The assumptions table is upsert-in-place (042), so a write destroys the value it
-- replaces and a delete leaves nothing at all. The only record of a prior number was the
-- git diff of the seed file it started in, which covers a value edited in the file and
-- misses every value edited in the terminal. A licensed book has to answer "what did you
-- say in September, and what has changed since", and no rebuild of today's numbers can
-- answer that honestly: a value recomputed now carries everything learnt since.
--
-- A row is written once and never updated, the rule model_calls already follows (085).
-- The ledger and the seed files together reconstruct any past state, by reading the last
-- edit at or before the date rather than by inverting the present.
CREATE TABLE IF NOT EXISTS assumption_edits (
    id                    INTEGER PRIMARY KEY,
    asset_id              INTEGER NOT NULL,
    indication_id         INTEGER,
    region                TEXT NOT NULL DEFAULT 'US',
    scenario              TEXT NOT NULL DEFAULT 'base',
    key                   TEXT NOT NULL,
    year                  INTEGER,
    op                    TEXT NOT NULL,   -- create, update, delete
    old_value             REAL,            -- the row as it stood, null on a create
    old_text              TEXT,
    old_unit              TEXT,
    old_source            TEXT,
    old_note              TEXT,
    old_evidence          TEXT,
    old_evidence_reviewed INTEGER,
    new_value             REAL,            -- the row as written, null on a delete
    new_text              TEXT,
    new_unit              TEXT,
    new_source            TEXT,
    new_note              TEXT,
    new_evidence          TEXT,
    new_evidence_reviewed INTEGER,
    changed_by            TEXT,            -- the analyst, from the setting or the checkout
    reason                TEXT,            -- the vocabulary in backend/assumption_log.py
    rationale             TEXT,            -- the analyst's own words, beside the code
    trigger_ref           TEXT,            -- the catalyst, trial or filing that forced it
    batch_id              TEXT,            -- one save, one id, so a change set reads whole
    rnpv_before           REAL,            -- the batch's effect, repeated on each of its rows
    rnpv_after            REAL,
    code_version          TEXT,            -- the commit that wrote it
    refresh_run_id        INTEGER,
    changed_at            TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assumption_edits_asset
    ON assumption_edits(asset_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_assumption_edits_when
    ON assumption_edits(changed_at);
CREATE INDEX IF NOT EXISTS idx_assumption_edits_batch
    ON assumption_edits(batch_id);

-- The ledger opens with the book as it stands, so a replay reaches a whole state rather
-- than the subset edited from today on. Dated to each row's own updated_at, which is the
-- one timestamp the old table kept. Checked on 2026-10-24: every one of the 12,310 rows
-- traced to a seed CSV, none carried a source only the terminal writes, so 'initial_seed'
-- is accurate for all of them. On a database built from nothing this inserts no rows and
-- the seed loader writes its own creates instead.
INSERT INTO assumption_edits
    (asset_id, indication_id, region, scenario, key, year, op,
     new_value, new_text, new_unit, new_source, new_note,
     new_evidence, new_evidence_reviewed, reason, changed_at)
SELECT asset_id, indication_id, region, scenario, key, year, 'create',
       value, text_value, unit, source, note,
       evidence, evidence_reviewed, 'initial_seed',
       COALESCE(updated_at, datetime('now'))
  FROM assumptions;
