-- What a ledger row is about, in terms a rebuild cannot break.
--
-- assumption_edits identified its subject by asset_id and indication_id alone. Those are
-- surrogate keys this database hands out, and history.py rebuild restores the ledger
-- before seed.py repopulates assets, so the ids a restored row carries were issued by an
-- earlier build and need not mean the same thing. Measured on the cloud book after one
-- rebuild on 2026-10-26: 1,135 of 17,119 ledger rows pointed at no asset at all, and
-- 545 of 1,815 gate_calls rows with them. The alpha dataset was losing its joins a
-- little every day.
--
-- gate_calls already carries ticker, asset_name and the NCT, so it can be re-resolved as
-- it stands. This one could not, so the names come with it.
--
-- Repairing a surrogate id is not rewriting the record. What an analyst said, when, why
-- and what it was worth is untouched; the id is an index into whichever rows this
-- database currently holds, and backend/relink.py re-points it from the names after a
-- rebuild. The names are the record. The id is a convenience.
ALTER TABLE assumption_edits ADD COLUMN ticker TEXT;
ALTER TABLE assumption_edits ADD COLUMN asset_name TEXT;
ALTER TABLE assumption_edits ADD COLUMN indication_name TEXT;

UPDATE assumption_edits SET
    ticker = (SELECT c.ticker FROM assets a
                JOIN companies c ON c.id = a.owner_company_id
               WHERE a.id = assumption_edits.asset_id),
    asset_name = (SELECT COALESCE(NULLIF(TRIM(a.brand_name), ''), a.generic_name)
                    FROM assets a WHERE a.id = assumption_edits.asset_id),
    indication_name = (SELECT i.name FROM indications i
                        WHERE i.id = assumption_edits.indication_id);

CREATE INDEX IF NOT EXISTS idx_assumption_edits_natural
    ON assumption_edits(ticker, asset_name, key);
