-- How many ordinary shares one American depositary share represents.
--
-- A foreign issuer's price here is its US depositary quote, while its share count comes
-- from the 20-F and is in ordinary shares. Multiplying the two is wrong by exactly this
-- ratio: AstraZeneca's ADS is half an ordinary share, so its market cap came out at half
-- the company. Novartis was right only by luck, its ratio being one.
--
-- With the ratio the calculation needs no exchange rate at all, because the depositary
-- quote is already in dollars: market cap = ordinary shares * (ADS price / ratio).
--
-- These are hand entered from each depositary agreement, not fetched: no free API
-- publishes them. They change only when a company restructures its programme, which is
-- rare and announced. A company with no row here gets no market cap rather than a
-- guessed one, which is why the table is seeded rather than left empty.

CREATE TABLE adr_ratios (
    ticker            TEXT PRIMARY KEY,
    ordinary_per_adr  REAL NOT NULL,   -- ordinary shares represented by one ADS/ADR
    note              TEXT,
    is_curated        INTEGER DEFAULT 1,
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- INSERT OR IGNORE so re-running init never overwrites a corrected figure.
INSERT OR IGNORE INTO adr_ratios (ticker, ordinary_per_adr, note) VALUES
    ('AZN',  0.5,   '1 ADS = one half ordinary share'),
    ('GSK',  2.0,   '1 ADS = 2 ordinary shares'),
    ('SNY',  0.5,   '1 ADS = one half ordinary share'),
    ('NVO',  1.0,   '1 ADR = 1 class B share'),
    ('NVS',  1.0,   '1 ADR = 1 ordinary share'),
    ('BAYN', 1.0,   '1 ADR = 1 ordinary share, OTC programme'),
    ('ROG',  0.125, '1 ADR = one eighth ordinary share, OTC programme');
