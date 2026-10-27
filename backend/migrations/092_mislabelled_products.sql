-- Twelve products carry another product's label.
--
-- backend/dailymed.py bound a label by asking whether the brand appeared anywhere in a
-- DailyMed search result's title. Wherever one product's name opens another's, that
-- matched both and whichever came back first won. Merck's intravenous KEYTRUDA, the
-- $31.7bn franchise, was bound to the KEYTRUDA QLEX label of the subcutaneous
-- co-formulation. Opdivo carries Opdivo Qvantig's, Darzalex carries Darzalex Faspro's,
-- Rituxan carries Rituxan Hycela's, and so on for twelve.
--
-- It matters because the label is how the book decides what a product is already
-- approved for. The Qlex label's indications omit classical Hodgkin lymphoma, so the
-- book read a disease Keytruda has been approved in since 2017 as an open expansion --
-- a phantom gate on the largest product in the book.
--
-- parse_search now prefers an exact product name over one that merely contains it, so
-- no new label binds this way. This repairs the rows already on file.
--
-- Keyed on the setid, which DailyMed owns and which survives a rebuild, and on the
-- brand name rather than the asset id, which does not.

CREATE TEMP TABLE _mislabelled (setid TEXT, ticker TEXT, belongs_to TEXT);
INSERT INTO _mislabelled (setid, ticker, belongs_to) VALUES
  ('7104d9e5-9910-47f5-9a93-741ac50f43b6', 'ARGX', 'VYVGART HYTRULO'),
  ('7f8c38fa-42f4-4387-9e8c-7a1c66855d8b', 'BMY', 'OPDIVO QVANTIG'),
  ('6e8f7981-f2ca-4b56-8759-4f18cf9706c8', 'GSK', 'BECONASE AQ'),
  ('adb8d669-b91c-46f1-8a86-19f504840eff', 'GSK', 'VENTOLIN HFA'),
  ('4bb241af-4299-4373-8762-2d6709515db0', 'JNJ', 'DARZALEX FASPRO'),
  ('a21f4f4b-b891-4f25-b747-cb9ec7d865d6', 'MRK', 'GARDASIL 9'),
  ('097d166f-b73b-41d3-9b37-7653cd2a0c41', 'MRK', 'KEYTRUDA QLEX'),
  ('10e79593-b991-4899-89fd-6fff7a213d81', 'PFE', 'BRIMONIDINE TARTRATE AND TIMOLOL MALEATE'),
  ('eed99b60-d043-4249-9b2a-f05e46fb588d', 'PFE', 'GLUCOTROL XL'),
  ('d4e2cf51-e6a8-4103-bb1d-6120c6474ff8', 'PFE', 'PREVNAR 20'),
  ('3e5b7e82-f018-4eaf-ae78-d6145a906b20', 'ROG', 'RITUXAN HYCELA'),
  ('07730e8c-1340-4d30-8d71-e20f850db8da', 'SNY', 'SARCLISA ESCENA');

-- Order matters. The delete below matches on the setid, which does not change when a
-- row moves, so moving first and deleting second removed everything.
--
-- Ventolin HFA, Prevnar 20 and the brimonidine combination already hold their own
-- labels, so the duplicate is deleted. Nothing is lost: the correct label for the
-- shorter-named product is fetched on the next refresh, and until then it carries none,
-- which the book reads as "cannot say what this is approved for" rather than as a wrong
-- answer.
DELETE FROM labels
 WHERE setid IN (SELECT setid FROM _mislabelled)
   AND EXISTS (SELECT 1 FROM labels l2
                 JOIN assets a ON a.id = l2.asset_id
                 JOIN companies c ON c.id = a.owner_company_id
                 JOIN _mislabelled m ON m.setid = labels.setid
                WHERE c.ticker = m.ticker
                  AND UPPER(TRIM(COALESCE(a.brand_name, ''))) = m.belongs_to);

-- The rest move: the label is right, it was only filed against the wrong asset.
UPDATE labels SET asset_id = (
        SELECT a.id FROM assets a
          JOIN companies c ON c.id = a.owner_company_id
          JOIN _mislabelled m ON m.setid = labels.setid
         WHERE c.ticker = m.ticker
           AND UPPER(TRIM(COALESCE(a.brand_name, ''))) = m.belongs_to
         LIMIT 1)
 WHERE setid IN (SELECT setid FROM _mislabelled)
   AND EXISTS (SELECT 1 FROM assets a
                 JOIN companies c ON c.id = a.owner_company_id
                 JOIN _mislabelled m ON m.setid = labels.setid
                WHERE c.ticker = m.ticker
                  AND UPPER(TRIM(COALESCE(a.brand_name, ''))) = m.belongs_to);

DROP TABLE _mislabelled;
