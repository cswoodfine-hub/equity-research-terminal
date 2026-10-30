-- The daily biopharma pulse: an AI-written morning briefing, read from the files its
-- scheduled run commits to the claude/pulse-feed branch (data/pulse/YYYY-MM-DD.json).
--
-- It is a summary of web search results, not a registry, so it is held apart from the
-- sources the book is built on: its items reach news and the change feed, labelled as
-- the pulse, and never a value, a deal term or a catalyst. Each item keeps the article it
-- cites, which is its evidence. Companies outside the universe (private rounds, other
-- biotechs) are kept, with no company attached.
CREATE TABLE IF NOT EXISTS pulse_items (
    id            INTEGER PRIMARY KEY,
    pulse_date    TEXT NOT NULL,          -- the briefing's date
    tier          INTEGER,                -- 1 sector-moving, 2 notable, 3 worth knowing
    kind          TEXT,                   -- deal, readout, approval, financing, ...
    headline      TEXT NOT NULL,          -- the pulse's words, not the source's
    detail        TEXT,                   -- its one or two lines on the numbers
    url           TEXT NOT NULL,          -- the article it cites
    published_at  TEXT,                   -- the article's date where the pulse gives one
    companies     TEXT,                   -- every company named, as the pulse names them
    tickers       TEXT,                   -- the universe tickers among them, comma joined
    fetched_at    TEXT DEFAULT (datetime('now')),
    UNIQUE (pulse_date, url)
);

-- Which universe companies an item names, so a deal between two of them shows on both.
CREATE TABLE IF NOT EXISTS pulse_item_companies (
    item_id     INTEGER NOT NULL REFERENCES pulse_items(id),
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    PRIMARY KEY (item_id, company_id)
);

-- One row per briefing read: its opening read of the sector and how many items it held.
CREATE TABLE IF NOT EXISTS pulse_reads (
    pulse_date  TEXT PRIMARY KEY,
    read        TEXT,
    items       INTEGER,
    file_sha    TEXT,                     -- a file changed since is read again
    fetched_at  TEXT DEFAULT (datetime('now'))
);
