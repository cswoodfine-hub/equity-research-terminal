-- The consensus table finally gets its first writers, and two gaps show at once.
--
-- Guidance is stated as a range ("DKK 63.0-64.5 billion", "growth of 8-14%"), so a
-- single value column cannot hold what the company said: value keeps the midpoint the
-- delta arithmetic wants, low and high keep the statement. And every extracted figure
-- carries its receipt: note holds the verbatim sentence it came from, the same bargain
-- the deals lane made with headlines.
ALTER TABLE consensus_estimates ADD COLUMN low  REAL;
ALTER TABLE consensus_estimates ADD COLUMN high REAL;
ALTER TABLE consensus_estimates ADD COLUMN note TEXT;

-- Which filing sections the guidance extractor has already read, so a daily refresh
-- spends the model on new filings only. The pdufa extractor gets this for free from
-- catalysts.source_url; guidance has no catalyst row to lean on, so it keeps its own
-- ledger.
CREATE TABLE IF NOT EXISTS guidance_scans (
    accession  TEXT NOT NULL,
    section    TEXT NOT NULL,
    scanned_at TEXT DEFAULT (datetime('now')),
    found      INTEGER DEFAULT 0,
    PRIMARY KEY (accession, section)
);
