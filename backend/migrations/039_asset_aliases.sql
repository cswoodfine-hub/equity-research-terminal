-- An application number that has been folded into another product, so it keeps resolving.
--
-- Marketed assets are keyed on the FDA application number, and one product routinely holds
-- several: Zithromax is seven NDAs for azithromycin, Neoral six for cyclosporine, because
-- each formulation and strength is filed separately. Each became its own asset row, so the
-- universe counted one product as seven and every revenue, exclusivity and indication
-- lookup saw a fraction of the drug.
--
-- Merging them is only half the fix. upsert_asset resolves a product by internal_code
-- alone, so a deleted row is recreated by the next openFDA or Orange Book refresh, and the
-- merge would undo itself daily while data bounced between the copies. The absorbed
-- application number is recorded here instead and resolves to the survivor, which both
-- stops the churn and keeps a fact worth having: which applications make up a product.
CREATE TABLE IF NOT EXISTS asset_aliases (
    internal_code TEXT PRIMARY KEY,
    asset_id      INTEGER NOT NULL REFERENCES assets(id),
    note          TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_asset_aliases_asset ON asset_aliases(asset_id);
