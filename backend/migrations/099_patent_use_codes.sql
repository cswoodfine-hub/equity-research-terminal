-- What each Orange Book patent use code says, from FDA's Orange Book patent pages.
--
-- The Orange Book data files carry a method-of-use patent's codes (U-2139) but not their
-- wording, so a page could show that a later patent covers one indication without
-- saying which. The wording is FDA's own, the same for every product that lists the
-- code, and a code once defined does not change, so a code is read once.
CREATE TABLE IF NOT EXISTS patent_use_codes (
    code        TEXT PRIMARY KEY,     -- U-2139
    definition  TEXT NOT NULL,        -- as FDA writes it, upper case
    appl_code   TEXT,                 -- the application page it was read from
    fetched_at  TEXT DEFAULT (datetime('now'))
);
