-- What a company actually markets, from openFDA's NDC directory.
--
-- drugsfda is CDER's register and carries no CBER biologics, so Shingrix, Comirnaty,
-- Spikevax, Elevidys and every vaccine in the universe have no approval row and nothing
-- they earn can be dated. The NDC directory does list them, with the date the package
-- began marketing and the BLA it was licensed under.
--
-- first_marketed is a marketing date, not an approval date, and the difference matters:
-- a product cannot be marketed before it is approved, so this is never earlier than the
-- approval and is sometimes much later. Comirnaty's earliest surviving record is the
-- 2025 seasonal formulation, four years after licensure, because the original packages
-- have been delisted. The bias runs one way only, toward looking newer, which is why
-- anything dated from here is labelled as a marketing date wherever it is used.

CREATE TABLE ndc_products (
    id             INTEGER PRIMARY KEY,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    brand_name     TEXT NOT NULL,
    application_number TEXT,
    first_marketed TEXT,
    labeler_name   TEXT,
    fetched_at     TEXT DEFAULT (datetime('now')),
    UNIQUE (company_id, brand_name)
);
CREATE INDEX idx_ndc_products_company ON ndc_products(company_id);
