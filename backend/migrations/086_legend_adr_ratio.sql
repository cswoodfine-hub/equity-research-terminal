-- Legend Biotech's ADS is two ordinary shares.
--
-- LEGN trades on Nasdaq as an American depositary share, and its 20-F counts ordinary
-- shares: the cover of the 20-F for 2025 (accession 0001801198-26-000008) registers
-- "American depositary shares, each representing two ordinary shares", and Item 12 says
-- "Each ADS represents two ordinary shares." With no row here the per-share divisor was
-- 369.9mm ordinary shares, so every per-share figure read at half of what the ADS price
-- is compared with.
--
-- INSERT OR IGNORE, as in 015, so a ratio corrected by hand later is never overwritten.

INSERT OR IGNORE INTO adr_ratios (ticker, ordinary_per_adr, note) VALUES
    ('LEGN', 2.0, '1 ADS = 2 ordinary shares: "American depositary shares, each representing two ordinary shares" (20-F for 2025, 0001801198-26-000008, cover page)');
