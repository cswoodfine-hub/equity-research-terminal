-- A posted readout is tied to a study, and what was reported is kept on file.
--
-- The block that offered "readouts that may have landed" matched a headline to a gate by
-- the asset's name. On 2026-11-22 it held 17 proposals from four headlines and none of
-- them decided the gate it was shown against: Merck's TroFuse-015 result (a
-- gastroesophageal study) stood against sacituzumab tirumotecan's lung study, an Imfinzi
-- approval in bladder cancer against two other Imfinzi studies, the Hibsago approval nine
-- times against a Phase 2, and a VK2735 maintenance study five times against the Phase 3.
-- A company runs several studies of one drug, so a name decides nothing.
--
-- trials.acronym is the registry's own name for a study (TroFuse-015, VOLGA, TOPAZ-1),
-- which is what a release uses. The pipeline fetch asks for it from here on, and a row
-- fetched before this column existed holds null until the registry is next read.
--
-- readout_reports is the record of every posted result or approval the refresh read
-- and what became of it: landed on a study with its outcome, the sentence and the page;
-- reported with the study certain and the outcome not stated in words a rule reads;
-- reported and tied to no study the book holds; an approval the book already carries;
-- or set aside by a person, with the reason. One row a report and study, kept, so a
-- report settled today is not offered again tomorrow.
ALTER TABLE trials ADD COLUMN acronym TEXT;

CREATE TABLE IF NOT EXISTS readout_reports (
    id            INTEGER PRIMARY KEY,
    source_key    TEXT NOT NULL,      -- the release's URL, a filing accession, registry:<nct>
    company_id    INTEGER REFERENCES companies(id),
    source        TEXT NOT NULL,      -- press, filing, registry
    kind          TEXT NOT NULL,      -- readout, approval
    url           TEXT,
    published_at  TEXT,               -- the day the source carries
    sentence      TEXT,               -- verbatim: the headline, or the result sentence
    asset_id      INTEGER REFERENCES assets(id),
    nct_id        TEXT,               -- the study, where one is certain
    tied_by       TEXT,               -- registry number, study name, or null
    outcome       TEXT,               -- met, missed, or null where no rule reads one
    matched_words TEXT,               -- the words that stated the outcome
    state         TEXT NOT NULL,      -- landed, outcome_not_read, not_tied, on_file,
                                      -- awaiting_register, set_aside
    reason        TEXT,               -- why it is in that state, in words
    catalyst_id   INTEGER,
    effect        TEXT,               -- what landing did to the gate, in words
    first_seen    TEXT NOT NULL DEFAULT (date('now')),
    updated_at    TEXT,
    -- SQLite allows no expression in a UNIQUE constraint: source_key and the study, or
    -- '' where the report is tied to none.
    dedupe        TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_readout_reports_company ON readout_reports (company_id, state);
