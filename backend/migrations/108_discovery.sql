-- Discovery: early research in cell and gene therapy, read each day from Europe PMC.
--
-- Two tables and one guard. ``discovery_labs`` is reference data: the lab heads ranked
-- offline (work/discovery/tools/export_models.py), loaded insert-only from
-- data/discovery/labs_seed.ndjson. A lab's standing is the seed's, as of ranked_as_of;
-- what it has done since lives in snapshots, written only when it changes.
--
-- ``discovery_papers`` is the current state of each paper the daily fetch has seen
-- (fetchers/papers_europepmc.py). No abstract is stored: the scores and what raised
-- them are, with a hash of the text they were read from and the model that read it. A
-- paper with no abstract yet is held with null scores and scored when one arrives.
CREATE TABLE IF NOT EXISTS discovery_labs (
    id               TEXT PRIMARY KEY,   -- OpenAlex author id
    name             TEXT NOT NULL,
    name_keys        TEXT NOT NULL,      -- JSON list of "first|last", for matching
    institutions     TEXT NOT NULL,      -- JSON list, most frequent first
    country          TEXT,
    rank             INTEGER NOT NULL,
    pct              REAL NOT NULL,      -- share of ranked lab heads this one outranks
    ranked_as_of     TEXT NOT NULL,      -- ISO date the ranking was run
    modalities       TEXT,               -- JSON list
    papers           INTEGER,            -- senior-author papers behind the ranking
    furthest_stage   TEXT,               -- latest model stage in those papers
    company_coauthor INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS discovery_papers (
    id             TEXT PRIMARY KEY,     -- Europe PMC source and id, "MED:12345"
    source         TEXT NOT NULL,        -- MED | PPR
    pmid           TEXT,
    doi            TEXT,
    title          TEXT NOT NULL,
    published      TEXT NOT NULL,        -- ISO, Europe PMC's first publication date
    indexed        TEXT,                 -- ISO, the day Europe PMC first carried it
    journal        TEXT,
    preprint       INTEGER NOT NULL DEFAULT 0,
    authors        INTEGER,              -- how many
    senior_author  TEXT,                 -- the last author, as printed
    institution    TEXT,                 -- read from the senior author's address
    lab_id         TEXT REFERENCES discovery_labs(id),
    lab_match      TEXT,                 -- how the lab was matched, in words
    areas          TEXT,                 -- JSON list
    modalities     TEXT,                 -- JSON list
    stage          TEXT,                 -- latest model stage the text names
    company_author INTEGER,              -- a company among the authors' addresses
    feas_score     REAL,
    feas_pct       REAL,                 -- share of the reference year it outranks
    comm_score     REAL,
    comm_pct       REAL,
    reasons        TEXT,                 -- JSON: what raised each score
    text_sha       TEXT,                 -- of the title and abstract the scores read
    model_version  TEXT,
    scored_at      TEXT,
    first_seen     TEXT NOT NULL DEFAULT (date('now')),
    fetched_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_discovery_papers_published ON discovery_papers (published);
CREATE INDEX IF NOT EXISTS idx_discovery_papers_lab ON discovery_papers (lab_id);

-- An alert about a paper or a lab is written once and can never be written twice,
-- whatever a re-fetch, a rebuild from history or a second run of the diff does.
CREATE UNIQUE INDEX IF NOT EXISTS idx_changes_discovery
    ON changes (entity_type, entity_key, change_type)
    WHERE entity_type IN ('paper', 'lab');
