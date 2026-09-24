-- Multiple myeloma and follicular lymphoma, one population each, on every asset.
--
-- data/epidemiology.csv (commit 1414fc1) settled both: myeloma at SEER's 36,000 new US
-- cases for 2026, follicular lymphoma at Teras et al.'s cited 13,960. But an asset's own
-- row wins over the disease file, and the rows that disagreed were never changed, so the
-- disagreement it described as resolved was still in the book: AZD0120, ramantamig and
-- JNJ-79635322 at 36,110 (the American Cancer Society's 2025 estimate) beside etentamig
-- at 36,000, and surovatamig at an uncited 13,619 beside MK-1045 at 13,960. The seed
-- files are corrected too, but the loader never overwrites a row that exists, so a
-- database that already holds these needs this.
--
-- Only a row still carrying the old value moves. A row an analyst has since set to some
-- other number is a decision, not the drift this corrects.
--
-- The old rows are snapshotted first, so what the book used before is on the record. A
-- database being built from nothing holds no assumptions yet and keeps no history.

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'epidemiology_alignment', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'indication', i.name, 'key', s.key,
                   'value', s.value, 'source', s.source, 'note', s.note,
                   'replaced_on', date('now'))
  FROM assumptions s JOIN indications i ON i.id = s.indication_id
 WHERE s.key IN ('prevalence', 'incidence')
   AND ((i.name = 'Multiple Myeloma' AND s.value = 36110)
        OR (i.name = 'Lymphoma, Follicular' AND s.value = 13619));

UPDATE assumptions
   SET value = 36000,
       source = 'SEER Cancer Stat Facts, myeloma: 36,000 estimated new US cases in 2026',
       note = 'the disease''s figure in data/epidemiology.csv. This row carried 36,110, the American Cancer Society''s 2025 estimate, while etentamig carried SEER''s 36,000, and two drugs cannot disagree about one disease, so the more current is carried for both',
       updated_at = datetime('now')
 WHERE key = 'prevalence' AND value = 36110
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Multiple Myeloma');

UPDATE assumptions
   SET value = 36000,
       source = 'SEER Cancer Stat Facts, myeloma: 36,000 estimated new US cases in 2026: the same annual diagnoses feeding the same pool',
       note = '',
       updated_at = datetime('now')
 WHERE key = 'incidence' AND value = 36110
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Multiple Myeloma');

UPDATE assumptions
   SET value = 13960,
       source = 'Teras LR et al., CA Cancer J Clin 2016;66:443-459: 13,960 new US follicular lymphoma cases expected in 2016',
       note = 'the disease''s figure in data/epidemiology.csv. This row carried 13,619 with no citation while MK-1045 carried the cited 13,960, and two drugs cannot disagree about one disease',
       updated_at = datetime('now')
 WHERE key = 'prevalence' AND value = 13619
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Lymphoma, Follicular');

UPDATE assumptions
   SET value = 13960,
       source = 'Teras LR et al., CA Cancer J Clin 2016;66:443-459: 13,960 new US follicular lymphoma cases expected in 2016: the same annual diagnoses feeding the same pool',
       note = '',
       updated_at = datetime('now')
 WHERE key = 'incidence' AND value = 13619
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Lymphoma, Follicular');
