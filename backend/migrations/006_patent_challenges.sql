-- Paragraph IV patent challenges from the FDA certifications list. A Paragraph IV
-- certification is a generic filer asserting a branded drug's patent is invalid or not
-- infringed: the first move in the litigation that ends a small molecule's exclusivity,
-- and it often lands years before the patent expires. The LOE cliff reads latest
-- expiry; a challenge is the signal that the expiry may not hold, so it gives the view
-- a "challenged" state between protected and expired. Additive only.
--
-- Keyed on the asset. The list is by reference drug (RLD) NDA number, matched to an
-- asset's internal_code; the first submission date is the earliest certification
-- against that drug, or null for a pre-1984 (Pre-MMA) reference with no cert date.

CREATE TABLE patent_challenges (
    id                 INTEGER PRIMARY KEY,
    asset_id           INTEGER REFERENCES assets(id),
    application_number TEXT,            -- RLD, internal_code shape, e.g. NDA21780
    first_submission   TEXT,            -- date of first Paragraph IV certification, or null
    source             TEXT DEFAULT 'fda_paragraph_iv',
    fetched_at         TEXT DEFAULT (datetime('now')),
    UNIQUE(asset_id)
);
CREATE INDEX idx_challenges_asset ON patent_challenges(asset_id);
