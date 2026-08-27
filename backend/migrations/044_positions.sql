-- The book: what was believed, when, and whether it turned out to be right.
--
-- Everything else in this database is what happened. This is the only table that records
-- what the analyst thought would happen, which is the one thing no source can supply and
-- the only thing a track record is made of. Three tables were stubbed for this and never
-- filled: annotations, asset_economics and valuation_assumptions all still hold zero
-- rows. This one is narrower on purpose, because a position is a claim with a date on it
-- rather than a note attached to something else.
--
-- The two verdicts are the reason the table exists. A position can be right about the
-- biology and lose money, or wrong about the biology and make it, and a book that records
-- only the second cannot tell the difference between judgement and luck. Scoring them
-- apart is what turns a P&L into feedback: science_call answers "did the drug do what I
-- said it would", trade_call answers "did the position pay". Free text over a constrained
-- vocabulary, following scenario in assumptions and status in catalysts, with the
-- intended words written here rather than enforced: right, wrong, or open.
--
-- market_implied is what makes a thesis a disagreement rather than an opinion. It records
-- what the price was saying at entry, so the position can later be read as "the market
-- had X, I had Y" instead of "I liked it". Without that column a thesis is unfalsifiable
-- after the fact, because the counterfactual is gone.
--
-- disconfirming is written at entry, which is the only moment it can be written honestly.
-- Asked afterwards, an analyst reconstructs a reason the position failed; asked before,
-- they have to name the evidence that would change their mind while they still believe.
CREATE TABLE positions (
    id             INTEGER PRIMARY KEY,
    -- Free text, not a companies FK, the same choice annotations made. A position can be
    -- taken in something this universe does not cover yet, and refusing to record it
    -- because the coverage list is short would lose the entry that matters most.
    ticker         TEXT NOT NULL,
    -- The vocabulary asset_themes already uses, e.g. 'Incretin'. Free text there, free
    -- text here, so the two can be read together without a lookup that does not exist.
    theme          TEXT,

    entry_date     TEXT,                  -- ISO, the day the view was taken
    entry_price    REAL,
    exit_date      TEXT,                  -- NULL while the position is open
    exit_price     REAL,
    -- Not in the brief, added because a bare price is ambiguous in this universe: Novo is
    -- quoted in kroner, Roche in francs, and the FX work elsewhere in this repo exists
    -- precisely because a number without its unit cannot be compared. Defaulted rather
    -- than required, since most of the book will be dollars.
    currency       TEXT DEFAULT 'USD',

    thesis         TEXT,                  -- what I think happens, and why
    market_implied TEXT,                  -- what the price says instead
    disconfirming  TEXT,                  -- what would prove me wrong, named at entry

    science_call   TEXT,                  -- right | wrong | open
    trade_call     TEXT,                  -- right | wrong | open

    created_at     TEXT DEFAULT (datetime('now')),
    updated_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_positions_ticker ON positions(ticker);
CREATE INDEX idx_positions_theme ON positions(theme);
-- Open positions first, then most recent, which is the order the book is read in.
CREATE INDEX idx_positions_open ON positions(exit_date, entry_date);
