-- Curated per-product analyst inputs for the product fact profile. Market size, peak
-- sales and the competitive set are not in any free source, so they are the analyst's
-- own, typed in the UI and stored here rather than fetched or estimated. Kept as free
-- text on purpose: a research analyst writes "~$25bn US by 2030, growing high-single
-- digit", not a single number, and forcing a numeric column would invent a precision the
-- input does not have. Everything else in the profile is sourced and lives in its own
-- table; this holds only the hand-entered fields. Additive only.
--
-- One row per asset. Every field is nullable, so a product with no note is simply blank,
-- never a placeholder value. updated_at stamps the last edit, so the profile can show how
-- fresh the analyst's own view is next to the sourced data.

CREATE TABLE product_notes (
    id           INTEGER PRIMARY KEY,
    asset_id     INTEGER REFERENCES assets(id),
    market_size  TEXT,        -- addressable market, the analyst's own sizing
    peak_sales   TEXT,        -- peak revenue view, with the year and basis in the text
    competitors  TEXT,        -- the competing drugs or programmes, free text
    thesis       TEXT,        -- the one-paragraph why-it-matters, the analyst's words
    updated_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id)
);
CREATE INDEX idx_product_notes_asset ON product_notes(asset_id);
