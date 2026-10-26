-- Where a call in this database came from.
--
-- model_calls is the point-in-time record of what the model said, and the whole claim it
-- makes is that a row was written on the day, before the outcome was known. A row loaded
-- in from another book is a different kind of thing, and until now the two were
-- indistinguishable: 248 rows were brought across from the published history on
-- 2026-10-26 to continue a local record that had stopped, and nothing in the table said
-- so. A record whose provenance cannot be read is not a record.
--
-- 'scheduled' is a call this database computed at the end of its own refresh.
-- 'backfill'  is a call brought in from an exported history to continue a stopped record.
-- NULL is a row written before this column existed, which is the honest value for one
-- whose origin nobody wrote down: it is not backfilled to 'scheduled', because that
-- would assert something no one checked.
--
-- The column travels through export and rebuild, since history.py exports SELECT *, so
-- provenance survives transport rather than being lost at the first hop.
ALTER TABLE model_calls ADD COLUMN source TEXT;
ALTER TABLE gate_calls ADD COLUMN source TEXT;
