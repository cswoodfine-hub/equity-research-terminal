-- A product's revenue split by the geography the filer reports it in.
--
-- asset_revenue holds one worldwide figure per product and year, and the product
-- revenue fetcher summed the geography rows into it and threw the split away. The split
-- is what loss of exclusivity needs: Ozempic's compound patent lapsed in China in 2026
-- and runs to 2031 in the US, so how much of it sells in China decides how much of it
-- erodes first. ``member`` is the filer's own name for the region (NonUs, EUCAN,
-- RestOfWorld), ``region`` a code the exclusivity dates are keyed on (US, INTL, EU, JP,
-- CN, EM, APAC, ROW).
CREATE TABLE IF NOT EXISTS asset_revenue_regions (
    id          INTEGER PRIMARY KEY,
    asset_id    INTEGER NOT NULL REFERENCES assets(id),
    fiscal_year INTEGER NOT NULL,
    member      TEXT NOT NULL,
    region      TEXT NOT NULL,
    value       REAL,
    unit        TEXT,
    source      TEXT,
    note        TEXT,
    is_curated  INTEGER DEFAULT 0,
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id, fiscal_year, member)
);
CREATE INDEX IF NOT EXISTS idx_asset_revenue_regions ON asset_revenue_regions(asset_id, fiscal_year);
