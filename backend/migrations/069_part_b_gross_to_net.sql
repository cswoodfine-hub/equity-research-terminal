-- A Part B price takes the Part B deduction.
--
-- gross_to_net.py measured the halving convention on Part D, where CMS spending is gross
-- of the rebates a manufacturer pays, and says it does not apply to Part B: Part B pays
-- 106% of average sales price, ASP is already net of manufacturer discounts, so the
-- deduction is the 6% add-on, 1 - 1/1.06 = 0.056604. Twenty-odd seeds price off a Part B
-- figure and apply that. Nine applied 0.5 instead, which halved a price that was already
-- nearly net: AZD5335, puxitatug samrotecan, sonesitatug vedotin and sofetabart mipitecan
-- off Trodelvy (3,300 Part B beneficiaries in 2024 against 67 in Part D), volrustomig off
-- Imfinzi (14,791 against 463), JNJ-79635322, pasritamig and ramantamig off Tecvayli
-- (1,549 against 13), and venglustat off Cerezyme (140 against 39). A second reader caught
-- it on a new seed priced off Trodelvy; the rest were found by matching every seed's
-- price against the demand table.
--
-- The seed files are corrected too, but the loader never overwrites a row that exists,
-- so a database that already holds these needs this. Only a row still carrying 0.5
-- moves: a row an analyst has since set to some other number is a decision, not this.
--
-- The old rows are snapshotted first, so what the book used before is on the record. A
-- database being built from nothing holds no assumptions yet and keeps no history.

CREATE TEMP TABLE part_b_anchor (ticker TEXT, generic TEXT, anchor TEXT, part_b INTEGER, part_d INTEGER);
INSERT INTO part_b_anchor VALUES
    ('AZN', 'azd5335', 'Trodelvy', 3300, 67),
    ('AZN', 'puxitatug samrotecan', 'Trodelvy', 3300, 67),
    ('AZN', 'sonesitatug vedotin', 'Trodelvy', 3300, 67),
    ('AZN', 'volrustomig', 'Imfinzi', 14791, 463),
    ('LLY', 'sofetabart mipitecan', 'Trodelvy', 3300, 67),
    ('JNJ', 'jnj-79635322', 'Tecvayli', 1549, 13),
    ('JNJ', 'pasritamig', 'Tecvayli', 1549, 13),
    ('JNJ', 'ramantamig', 'Tecvayli', 1549, 13),
    ('SNY', 'venglustat', 'Cerezyme', 140, 39);

CREATE TEMP TABLE part_b_rows AS
SELECT s.id AS assumption_id, p.anchor, p.part_b, p.part_d, p.generic
  FROM assumptions s
  JOIN assets a ON a.id = s.asset_id
  JOIN companies c ON c.id = a.owner_company_id
  JOIN part_b_anchor p ON p.ticker = c.ticker AND p.generic = LOWER(TRIM(a.generic_name))
 WHERE s.key = 'gross_to_net_pct' AND s.scenario = 'base'
   AND s.indication_id IS NULL AND s.value = 0.5;

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'part_b_gross_to_net', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'key', s.key, 'value', s.value,
                   'source', s.source, 'note', s.note, 'replaced_on', date('now'))
  FROM assumptions s JOIN part_b_rows r ON r.assumption_id = s.id;

UPDATE assumptions
   SET value = 0.056604,
       source = 'Social Security Act section 1847A: Medicare Part B pays 106% of average sales price, and ASP is already net of manufacturer discounts and rebates, so the manufacturer''s price is the CMS figure divided by 1.06, which is 5.66% below it (backend/gross_to_net.py: the halving convention is measured on Part D and does not apply to Part B)',
       note = (SELECT 'Part B established from the data: ' || r.anchor || ' carries '
                      || printf('%,d', r.part_b) || ' Part B beneficiaries against ' || r.part_d
                      || ' in Part D (2024), and the list price is its Part B figure. Net is 94.3% of list. This row carried 0.5, the Part D convention, until 2026-09-24'
                      || CASE WHEN r.generic = 'venglustat' THEN '. Case against: venglustat is oral and would be dispensed under Part D, where rebates come off its own list price; the discount here follows the anchor''s basis, not the product''s channel' ELSE '' END
                 FROM part_b_rows r WHERE r.assumption_id = assumptions.id),
       updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM part_b_rows);

DROP TABLE part_b_rows;
DROP TABLE part_b_anchor;
