-- Which filings the decision-date reader has already read, and what came of each.
--
-- The reader used to remember a filing only when it produced a catalyst, because the
-- catalyst's source_url was the only record that it had been looked at. That is fine
-- while the window is 400 days and most of what it covers has been read once. It stops
-- being fine the moment the window is the whole history: 1,532 filings would be fetched
-- from EDGAR on every refresh for ever, to re-derive the same nothing, which is both
-- wasteful and rude to a free service that asks for under ten requests a second.
--
-- So the ledger records every read rather than every hit. A filing is fetched once in
-- its life, the window can safely be "everything on file", and a daily refresh reads
-- only what arrived that day.
--
-- outcome says what happened, so the ledger also answers the question the window was
-- widened to settle:
--   skipped    the document carried no regulatory language, so no model call was made
--   none       the model was asked and found no decision date stated
--   dropped    a date was found and refused; detail says which check refused it, and
--              "date has passed" is the interesting one, because it is a real
--              acceptance whose review has already concluded
--   found      a date was found, survived every check, and a catalyst was written
--
-- accession is the key rather than the URL, because one accession is one filing however
-- many documents it contains, and the reader may have followed an exhibit to get at the
-- text. The URL it actually read is kept beside it for tracing.

CREATE TABLE IF NOT EXISTS pdufa_reads (
    accession  TEXT PRIMARY KEY,
    url        TEXT,
    form_type  TEXT,
    filed_date TEXT,
    outcome    TEXT NOT NULL,
    detail     TEXT,
    read_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pdufa_reads_outcome ON pdufa_reads(outcome, filed_date);
