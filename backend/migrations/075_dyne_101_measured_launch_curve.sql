-- DYNE-101 reaches its peak capture along a measured launch curve, not a step.
--
-- The seed reused z-rostudirsen's step (k 4.0, midpoint -1.0), fitted to Exondys, which put
-- 98% of the peak rate into z-basivarsen's H1 2028 launch year. It now reuses the book's
-- measured rare-neuromuscular launch, Vyvgart's Medicare uptake (k 0.5633, midpoint 2.0,
-- the nipocalimab seed's, as deramiocel reuses it). The peak stays at 0.107: Skyclarys
-- launched in a step, at full rate from its first year, so that rate is measured whatever
-- curve leads up to it; its note says so.
--
-- The seed file is corrected too, but the loader never overwrites a row that exists, so a
-- database that already holds these needs this. Only a row still carrying the old value
-- moves, after a snapshot.

CREATE TEMP TABLE dyne_101_curve AS
SELECT s.id AS assumption_id, s.key
  FROM assumptions s
  JOIN assets a ON a.id = s.asset_id
  JOIN companies c ON c.id = a.owner_company_id
 WHERE c.ticker = 'DYN' AND LOWER(TRIM(a.generic_name)) = 'zeleciment basivarsen (dyne-101)'
   AND s.scenario = 'base' AND s.indication_id IS NOT NULL
   AND ((s.key = 'ramp_steepness' AND s.value = 4.0)
        OR (s.key = 'ramp_midpoint_year' AND s.value = -1.0)
        OR (s.key = 'penetration_peak_pct' AND s.value = 0.107 AND s.note NOT LIKE 'MEASURED:%'));

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'dyne_101_launch_curve', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'key', s.key, 'value', s.value,
                   'source', s.source, 'note', s.note, 'replaced_on', date('now'))
  FROM assumptions s JOIN dyne_101_curve d ON d.assumption_id = s.id;

UPDATE assumptions
   SET value = 0.5633, source = 'reused from the book''s nipocalimab seed (jnj_imaavy.csv), as the deramiocel seed reuses it: logistic k implied by Vyvgart and Vyvgart Hytrulo''s Medicare uptake, 1,397 beneficiaries across Parts B and D in 2022 to 4,310 in 2024 (lookup.py demand Vyvgart, CMS spending by drug)', note = 'MEASURED on the closest modelled launch: Vyvgart is the book''s measured launch of a rare neuromuscular IV infusion given in specialist centres, which z-basivarsen, dosed IV every eight weeks, would be. It replaces the step (k 4.0, midpoint -1.0) reused from z-rostudirsen, which put 98% of the peak rate into the H1 2028 launch year. Case against: Skyclarys itself launched in a step, reaching more than 1,100 US patients within nine months, so a first DM1 therapy could move faster than this', updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM dyne_101_curve WHERE key = 'ramp_steepness');

UPDATE assumptions
   SET value = 2.0, source = 'reused from the nipocalimab seed with its steepness, as one measured curve: Vyvgart had 2,561 of its 4,310 2024 beneficiaries in 2023, its second year (CMS, lookup.py demand Vyvgart)', note = 'Reused with the steepness as one measured curve. At k 0.5633 and midpoint 2.0 the launch year runs at 24.5% of the peak rate, and half of it is reached in 2030', updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM dyne_101_curve WHERE key = 'ramp_midpoint_year');

UPDATE assumptions
   SET note = 'MEASURED: Skyclarys''s capture rate at full speed. Its launch was a step, at its full rate from the first year, so the rate is identified whatever curve leads up to it; this seed reaches it along Vyvgart''s measured curve (ramp_steepness). On the step it reproduced Skyclarys''s 473, 862, 1,170 and 1,410 patients in years 0 to 3, about 1,290 at the end-2025 point against 1,341 measured, undershooting the early bolus (862 against 1,134 in 2024). A least-squares fit on 2024 and 2025 prefers about 0.125; with a 5,000 pool instead of 4,500 the solve is about 0.095. Re-solving on the slower curve to hit 1,170 in year 2 would need 0.28 and would carry the analogue to 53% of its pool by year 5 against Skyclarys''s plateau, so the full-speed rate is kept', updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM dyne_101_curve WHERE key = 'penetration_peak_pct');

DROP TABLE dyne_101_curve;
