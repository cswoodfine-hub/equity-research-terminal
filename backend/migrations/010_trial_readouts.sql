-- Phase 2 and Phase 3 trial readouts, classified from the filings that announce them. A
-- readout, the topline result of a pivotal trial, is the largest catalyst in drug
-- development, and it carries a sign: the trial met its primary endpoint or it did not.
-- No free source labels these, so they are read out of the 8-K and 6-K press releases
-- that announce them, over the model seam, with the same guard as the PDUFA extractor:
-- the drug and a result sentence must appear in the filing. Additive only.
--
-- One row per processed filing, keyed on the accession so a filing is read once. outcome
-- is positive or negative for a real readout, or 'none' for a filing that was read and
-- carried no Phase 2 or 3 result, which marks it done so it is not fetched again. The
-- backtest reads the signed rows; feeds the signal by phase and outcome.

CREATE TABLE trial_readouts (
    id         INTEGER PRIMARY KEY,
    accession  TEXT UNIQUE,
    company_id INTEGER REFERENCES companies(id),
    drug       TEXT,
    phase      INTEGER,          -- 2 or 3
    outcome    TEXT,             -- positive, negative, or none (read, no readout)
    event_date TEXT,             -- the filing date, the day the market saw it
    quote      TEXT,             -- the result sentence, verbatim
    source_url TEXT,
    is_curated INTEGER DEFAULT 0,
    fetched_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_readouts_company ON trial_readouts(company_id, event_date);
CREATE INDEX idx_readouts_signed ON trial_readouts(outcome, phase);
