-- What a readout row was read from, and whether it has been read again.
--
-- 1,287 of the 1,359 rows in trial_readouts say "none": the filing was read and no
-- Phase 2 or 3 result was found. 251 of them were read from a cover under 6,000
-- characters with no result language, and for 52 of those the exhibit on file carries
-- one. The reader fetched the EX-99 exhibit only for an 8-K whose cover lacked the
-- cheap hint; a 6-K was never followed to its exhibit at all, and an 8-K whose cover
-- said "Phase 3" in its item description was read as if that cover were the release.
-- Those rows are not "no result"; they are "did not look".
--
-- read_from says which it was, so a row read from the envelope can be told from one
-- read from the release. reread_at is stamped when the row has been read again with
-- the exhibit, whatever was found, so the second reading happens once.
ALTER TABLE trial_readouts ADD COLUMN read_from TEXT;
ALTER TABLE trial_readouts ADD COLUMN reread_at TEXT;
