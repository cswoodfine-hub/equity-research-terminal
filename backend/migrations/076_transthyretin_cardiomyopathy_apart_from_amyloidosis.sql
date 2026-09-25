-- ATTR cardiomyopathy gets an indication of its own, apart from "Amyloidosis".
--
-- The registry files both amyloidoses under one MeSH descriptor, Amyloidosis (D000686):
-- AL, a plasma-cell disorder treated with daratumumab, belantamab and etentamig, and ATTR,
-- a transthyretin disease treated with vutrisiran and, in trial, nex-z. The nex-z seed put
-- the ATTR cardiomyopathy pool there (Alexander et al.: 55,372 prevalent, 25,605 a year),
-- so the first AL seed would have inherited it: assembly copies the pool another asset
-- carries for the same indication, and the book allows one prevalence per disease.
--
-- The pool now sits on "Transthyretin Amyloid Cardiomyopathy", a curated indication with no
-- MeSH descriptor of its own (indication_mapping.CURATED keeps it on every refresh; the
-- rebuild keys on MeSH ids and never removes an indication). An AL seed takes the registry's
-- own "Immunoglobulin Light-chain Amyloidosis" (D000075363); test_seed_shape refuses a pool
-- written on the mixed "Amyloidosis". Trial links to "Amyloidosis" are unchanged: they are
-- rebuilt from the registry on every refresh and carry no figures.
--
-- nex-z's rows are moved, not copied, after a snapshot. A database built from nothing holds
-- no assumptions yet, and the seed file already names the new indication.

-- Only in a book that already holds the registry's indications. A database built from
-- nothing gets the row from indication_mapping.CURATED on its first refresh, before the
-- seeds load, and an empty one (every test fixture) is left alone.
INSERT OR IGNORE INTO indications (name, therapeutic_area)
SELECT 'Transthyretin Amyloid Cardiomyopathy', 'cardiometabolic'
 WHERE EXISTS (SELECT 1 FROM indications WHERE name = 'Amyloidosis');

CREATE TEMP TABLE attr_cm_rows AS
SELECT s.id AS assumption_id
  FROM assumptions s
  JOIN assets a ON a.id = s.asset_id
  JOIN companies c ON c.id = a.owner_company_id
  JOIN indications i ON i.id = s.indication_id
 WHERE c.ticker = 'NTLA' AND LOWER(TRIM(a.generic_name)) = 'nexiguran ziclumeran'
   AND i.name = 'Amyloidosis';

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'attr_cm_indication', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'indication_id', s.indication_id, 'key', s.key,
                   'value', s.value, 'moved_on', date('now'))
  FROM assumptions s JOIN attr_cm_rows r ON r.assumption_id = s.id;

UPDATE assumptions
   SET indication_id = (SELECT id FROM indications
                         WHERE name = 'Transthyretin Amyloid Cardiomyopathy'),
       updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM attr_cm_rows);

DROP TABLE attr_cm_rows;
