-- AstraZeneca's US quote is an ordinary share, not half of one.
--
-- AstraZeneca ended its ADR programme and listed its ordinary shares directly on the NYSE
-- on 2 February 2026: "AstraZeneca today begins trading its ordinary shares on the New
-- York Stock Exchange (NYSE) for the first time" (6-K 0001654954-26-000792), and "The
-- prior listing of American Depositary Shares ... on Nasdaq in the US ceased on 30
-- January 2026" (6-K 0001654954-26-001073). The price history the terminal reads is the
-- ordinary share throughout, so the ratio of one half, seeded in 015, divided the
-- company's value by twice its shares and put it at half the price.
--
-- The old row is snapshotted first, so the change is on the record.

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'adr_ratios', 'company', ticker,
       json_object('ordinary_per_adr', ordinary_per_adr, 'note', note, 'updated_at', updated_at)
  FROM adr_ratios WHERE ticker = 'AZN';

UPDATE adr_ratios
   SET ordinary_per_adr = 1.0,
       note = '1 US-listed share = 1 ordinary share: ordinary shares listed directly on the NYSE from 2 February 2026, replacing the ADS programme (6-K 0001654954-26-000792)',
       updated_at = datetime('now')
 WHERE ticker = 'AZN';
