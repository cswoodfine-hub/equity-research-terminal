-- Incyte carries no debt, so its discount rate carries none.
--
-- Every Incyte seed struck its debt weight on the only TotalDebt the SEC company facts
-- hold for the filer: $19,094mm for FY2018. That is a scale error in the filed XBRL, $19.1mm
-- of convertible notes tagged a thousand times over (FY2017 carried $26.8mm), and seven
-- years stale besides. Over a $25bn market capitalisation it put 43% debt into Incyte's
-- WACC and discounted every Incyte product at a rate that leaned on borrowing Incyte does
-- not have. Its 10-Q for the quarter to 2026-06-30 (0000879169-26-000056) states "As of
-- June 30, 2026, we had no outstanding borrowings" under its revolving credit facility.
-- Found while building a cost block for a company that had none.
--
-- The seed files are corrected too, but the loader never overwrites a row that exists, so
-- a database that already holds these needs this. Only a row still at the old value moves.
-- The old rows are snapshotted first.

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'incyte_debt_weight', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'key', s.key, 'value', s.value,
                   'source', s.source, 'note', s.note, 'replaced_on', date('now'))
  FROM assumptions s JOIN assets a ON a.id = s.asset_id
  JOIN companies c ON c.id = a.owner_company_id
 WHERE c.ticker = 'INCY' AND s.key = 'debt_weight' AND s.value = 0.433277;

UPDATE assumptions
   SET value = 0,
       source = 'no outstanding borrowings: Incyte''s 10-Q for the quarter to 2026-06-30 (0000879169-26-000056, MD&A) states ''As of June 30, 2026, we had no outstanding borrowings'' under its $500mm revolving credit facility, and the SEC company facts tag no debt since FY2018',
       note = 'a reading of the balance sheet, as for Viking and United Therapeutics. This row carried 0.433277 until 2026-09-24, struck on the only TotalDebt on file, $19,094mm for FY2018: a scale error in the filed XBRL ($19.1mm of convertible notes; FY2017 carried $26.8mm) and seven years stale, which put 43% debt into Incyte''s discount rate',
       updated_at = datetime('now')
 WHERE key = 'debt_weight' AND value = 0.433277
   AND asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                     WHERE c.ticker = 'INCY');
