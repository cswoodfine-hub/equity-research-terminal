-- Foreign-exchange rates, so the universe revenue-at-risk view can show absolutes
-- across companies that report in different currencies. Additive only.
--
-- One row per (base, quote, as_of): rate converts one unit of base into quote, e.g.
-- base='DKK' quote='USD' rate=0.146 means 1 DKK = 0.146 USD. Rates are real, from the
-- ECB daily reference set (free, no key); a currency with no row is never converted,
-- the same discipline the rest of the app keeps.

CREATE TABLE fx_rates (
    id         INTEGER PRIMARY KEY,
    base       TEXT NOT NULL,       -- reporting currency, e.g. DKK, EUR, GBP, CHF, USD
    quote      TEXT NOT NULL,       -- display currency, always USD in this build
    rate       REAL NOT NULL,       -- quote units per one base unit
    as_of      TEXT NOT NULL,       -- ECB reference date the rate is for
    source     TEXT DEFAULT 'ecb',
    fetched_at TEXT DEFAULT (datetime('now')),
    UNIQUE(base, quote, as_of)
);
CREATE INDEX idx_fx_latest ON fx_rates(base, quote, as_of);
