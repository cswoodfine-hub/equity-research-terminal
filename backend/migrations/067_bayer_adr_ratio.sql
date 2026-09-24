-- Bayer's ADR is a quarter of an ordinary share, not one.
--
-- Seeded in 015 as one for one. Bayer changed its ADR ratio on 20 September 2017 so that
-- four ADSs represent one ordinary share: the depositary's ratio-change letter, filed
-- with the SEC on Form 424B3 (accession 0001201935-17-000069, CIK 0000790075), and
-- Bayer's own ADR programme page.
-- BAYRY trades at a quarter of the Xetra price for that reason.
--
-- Harmless while Bayer carried no financials, since there was no share count to divide.
-- Once its ESEF reports load, the per-share divisor is ordinary shares over this ratio,
-- and one for one would have put every per-share figure at four times the price it is
-- read against.
--
-- The old row is snapshotted first, so the change is on the record. A database being built
-- from nothing holds no companies yet and has no history to keep, so it takes no snapshot.

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'adr_ratios', 'company', ticker,
       json_object('ordinary_per_adr', ordinary_per_adr, 'note', note, 'updated_at', updated_at)
  FROM adr_ratios
 WHERE ticker = 'BAYN' AND EXISTS (SELECT 1 FROM companies);

UPDATE adr_ratios
   SET ordinary_per_adr = 0.25,
       note = '4 ADS = 1 ordinary share since the ratio change of 20 September 2017 (Form 424B3, accession 0001201935-17-000069)',
       updated_at = datetime('now')
 WHERE ticker = 'BAYN';
