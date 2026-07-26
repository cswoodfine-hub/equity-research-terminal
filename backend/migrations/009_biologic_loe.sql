-- Biologic loss of exclusivity for the valuation. The Orange Book gives a small
-- molecule's patent cliff; no free source gives a biologic's, so a biologic whose only
-- Purple Book date is orphan exclusivity has no cliff to discount to and goes unvalued.
-- This derives one: the later of the 12-year BPCIA reference-product exclusivity counted
-- from the approval already on file, and the patent or biosimilar-entry year the company
-- discloses in its own 10-K risk factors. Additive only.
--
-- One row per asset. floor_year is always available; disclosed_year needs a model and is
-- null without one, so a biologic values conservatively on the floor alone and precisely
-- when a disclosure refines it. The two are combined by taking the later, since a
-- biologic can be protected past its 12-year exclusivity by patents but never before it.
-- basis records which source set the date, and evidence is the disclosing sentence. Feeds
-- the valuation only; the LOE cliff view stays on the published Orange and Purple dates.

CREATE TABLE biologic_loe (
    id             INTEGER PRIMARY KEY,
    asset_id       INTEGER REFERENCES assets(id),
    loe_year       INTEGER,
    loe_date       TEXT,
    basis          TEXT,        -- '10-K and statutory floor', '10-K disclosure', 'statutory floor'
    floor_year     INTEGER,     -- approval year plus 12, the BPCIA exclusivity floor
    disclosed_year INTEGER,     -- the year read from the 10-K, or null
    evidence       TEXT,        -- the disclosing sentence, verbatim
    source_url     TEXT,        -- the 10-K it was read from
    is_curated     INTEGER DEFAULT 0,
    fetched_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id)
);
CREATE INDEX idx_biologic_loe_asset ON biologic_loe(asset_id);
