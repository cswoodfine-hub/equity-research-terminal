-- Centrally authorised medicines from the European Medicines Agency's public medicines
-- data. The date of a substance's first EU marketing authorisation starts its regulatory
-- data and market protection (Directive 2001/83/EC, Article 10(1)): eight years before a
-- generic may file and ten before one may be sold. That is the statutory floor under a
-- product's European exclusivity, as the twelve years of the BPCIA are under a US
-- biologic's.
CREATE TABLE IF NOT EXISTS eu_medicines (
    ema_product_number TEXT PRIMARY KEY,
    name               TEXT,
    active_substance   TEXT,
    inn                TEXT,
    status             TEXT,
    authorised_on      TEXT,          -- ISO date of the marketing authorisation
    holder             TEXT,
    is_generic         INTEGER DEFAULT 0,
    is_biosimilar      INTEGER DEFAULT 0,
    is_orphan          INTEGER DEFAULT 0,
    fetched_at         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_eu_medicines_substance ON eu_medicines(active_substance);
