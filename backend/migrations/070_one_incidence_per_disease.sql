-- Sickle cell disease and hypercholesterolemia, one incidence each, on every asset.
--
-- Migration 068 settled prevalence and its guard checks prevalence only, so two diseases
-- still carried two inflows. Casgevy fed sickle cell at CDC's rounded ~2,000 births a year
-- beside osivelotor's 1,971, the count Therrell et al. measured from 76.5mm screened
-- newborns; the measured count is carried for both. AZD0780 fed its ASCVD pool with
-- 805,000, every heart attack a year including 200,000 recurrent ones and no strokes,
-- beside enlicitide's 1,135,700 first heart attacks and first ischaemic strokes for the
-- same 23.8mm pool; first events are what enter a pool, so that figure is carried for both.
-- A research agent caught the first when a new sickle cell seed had no single figure to copy.
--
-- The seed files are corrected too, but the loader never overwrites a row that exists,
-- so a database that already holds these needs this. Only a row still carrying the old
-- value moves. The old rows are snapshotted first, so what the book used before is on the
-- record.

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'incidence_alignment', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'indication', i.name, 'key', s.key,
                   'value', s.value, 'source', s.source, 'note', s.note,
                   'replaced_on', date('now'))
  FROM assumptions s JOIN indications i ON i.id = s.indication_id
 WHERE s.key = 'incidence'
   AND ((i.name = 'Anemia, Sickle Cell' AND s.value = 2000)
        OR (i.name = 'Hypercholesterolemia' AND s.value = 805000));

UPDATE assumptions
   SET value = 1971,
       source = 'Therrell BL Jr et al., Semin Perinatol 2015;39(3):238-251: 39,422 confirmed SCD cases among 76,527,627 US newborns screened over 20 years, 1,971 a year',
       note = 'the engine filters this by the eligibility share before it enters the pool. This row carried CDC''s rounded ~2,000 (about 1 in 365 Black births) while the osivelotor seed carried the measured 1,971, and two drugs cannot disagree about one disease, so the measured count is carried for both',
       updated_at = datetime('now')
 WHERE key = 'incidence' AND value = 2000
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Anemia, Sickle Cell');

UPDATE assumptions
   SET value = 1135700,
       source = '605,000 first heart attacks and 87% of 610,000 first strokes, the ischaemic share, each year (CDC Heart Disease Facts and Stroke Facts, citing AHA Heart Disease and Stroke Statistics 2023 Update): the new entrants to the ASCVD pool the enlicitide seed carries',
       note = 'new events only: a first diagnosis of stable coronary or peripheral disease is not counted. This row carried 805,000, every heart attack a year including 200,000 recurrent ones and no strokes, beside enlicitide''s 1,135,700 for the same pool; two drugs cannot disagree about one disease, and first events are what enter a pool',
       updated_at = datetime('now')
 WHERE key = 'incidence' AND value = 805000
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Hypercholesterolemia');
