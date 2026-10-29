-- BioNTech's ADS is one ordinary share.
--
-- The company record now says what BioNTech's 20-F does: a German foreign private issuer
-- reporting in euros. A foreign issuer with no ratio here loses its market cap, so the
-- correction needs its ratio. The cover of the 20-F for 2025 (accession
-- 0001776985-26-000017) registers "American Depositary Shares, each Representing one
-- ordinary share".
--
-- INSERT OR IGNORE, as in 015, so a ratio corrected by hand later is never overwritten.

INSERT OR IGNORE INTO adr_ratios (ticker, ordinary_per_adr, note) VALUES
    ('BNTX', 1.0, '1 ADS = 1 ordinary share: "American Depositary Shares, each Representing one ordinary share" (20-F for 2025, 0001776985-26-000017, cover page)');
