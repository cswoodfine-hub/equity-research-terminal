-- Medicare demand from the CMS Spending by Drug datasets. Company revenue is what a
-- drug earned; this is how many people took it. CMS publishes, per drug and year, the
-- total spending, the prescription claims, and the distinct beneficiaries under Part D
-- (retail pharmacy, mostly oral) and Part B (administered in a clinic, mostly infused
-- biologics). It is a real-world US demand proxy the company's own revenue line cannot
-- give: unit volume and the trend in it. Additive only.
--
-- One row per asset, part and year, so the five published years form a demand time
-- series. Matched on brand name to an asset; beneficiaries are null when CMS suppresses
-- a small count for privacy rather than zero, and none is invented.

CREATE TABLE drug_demand (
    id             INTEGER PRIMARY KEY,
    asset_id       INTEGER REFERENCES assets(id),
    part           TEXT,              -- 'D' retail pharmacy, 'B' clinic administered
    brand_name     TEXT,              -- as CMS names it
    year           INTEGER,
    total_spending REAL,
    total_claims   INTEGER,
    total_beneficiaries INTEGER,
    total_dosage_units  REAL,
    source         TEXT DEFAULT 'cms',
    fetched_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id, part, year)
);
CREATE INDEX idx_demand_asset ON drug_demand(asset_id, year);
