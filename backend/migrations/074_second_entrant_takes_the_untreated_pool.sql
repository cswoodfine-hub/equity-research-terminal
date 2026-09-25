-- A second entrant draws on the patients the incumbent has not already treated.
--
-- DYNE-251 and zodasiran each replayed their incumbent's launch into the whole pool, as if
-- the incumbent were absent. DYNE-251's stock built to 82% of the exon 51 pool while some
-- 650 of those boys were already infusing Exondys; zodasiran carried a 0.5 multiple on
-- Evkeeza's fitted capture as a stand-in for the same netting. The engine now takes a
-- per-indication already_treated_patients out of the opening pool (forecast.py), and the
-- seeds state the incumbent's measured patients there. With the netting explicit, each
-- seed takes its incumbent's measured capture as it was measured: zodasiran's peak moves
-- from 0.1486 to Evkeeza's 0.2972. DYNE-251 also gains the stationary retention the house
-- rule gives a chronic pool (0.9702, as SGT-003 holds the same Duchenne pool), so
-- Exondys's capture is re-solved under it: 0.1016, from 0.0953 with the pool left to grow.
--
-- The seed files are corrected too, and the new already_treated_patients rows are inserted
-- by the loader, but the loader never overwrites a row that exists, so a database that
-- already holds these needs this. Only a row still carrying the old value moves. The old
-- rows are snapshotted first.

CREATE TEMP TABLE second_entrant AS
SELECT s.id AS assumption_id, c.ticker
  FROM assumptions s
  JOIN assets a ON a.id = s.asset_id
  JOIN companies c ON c.id = a.owner_company_id
 WHERE s.key = 'penetration_peak_pct' AND s.scenario = 'base'
   AND ((c.ticker = 'ARWR' AND LOWER(TRIM(a.generic_name)) = 'zodasiran' AND s.value = 0.1486)
        OR (c.ticker = 'DYN' AND LOWER(TRIM(a.generic_name)) = 'zeleciment rostudirsen (dyne-251)'
            AND s.value = 0.0953));

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'second_entrant_netting', 'assumption', 'assumption:' || s.id,
       json_object('asset_id', s.asset_id, 'key', s.key, 'value', s.value,
                   'source', s.source, 'note', s.note, 'replaced_on', date('now'))
  FROM assumptions s JOIN second_entrant e ON e.assumption_id = s.id;

UPDATE assumptions
   SET value = 0.2972,
       source = 'Solved from Evkeeza''s own US launch (FDA approval February 2021), fitting the engine''s identity (backend/forecast.py derive_new_patients and treated_stock) to its filed US net sales read at this seed''s net price. Sales: $18.4mm 2021 (Regeneron FY2021 results, seen via search), $48.6mm 2022, $77.3mm 2023, $125.7mm 2024 (FY2024 10-K 0001804220-25-000011), $162.2mm 2025 (FY2025 10-K 0000872589-26-000008), $99.0mm in H1 2026 (10-Q 0000872589-26-000025: Q1 $45.7mm, Q2 $53.3mm), annualised. Net price $327,110 in 2024, scaled for 2021 to 2023 by CMS Part B spend per claim ($36,392, $36,230, $39,508 against $40,378; lookup.py demand Evkeeza), gives patient-equivalents of 62, 166, 242, 384, 496 and 605. Pool 975 aged 12 and over (1,133.7 x 0.8599), inflow 10.4 a year, retention 0.9894, discontinuation 0.0451, k fixed at 0.657. Least squares: peak 0.2972, midpoint 2.13 years from 2021, fitted 58, 145, 258, 384, 502, 598, rmse 11.65 (the researcher''s 0.290 and 2.05 fit at rmse 11.79 and are not the minimum). Zodasiran takes Evkeeza''s measured 0.2972',
       note = 'MEASURED: Evkeeza''s fitted capture of the untreated pool, applied as it was measured, with no multiple. Evkeeza''s 605 US patient-equivalents (H1 2026 annualised) are out of the pool this seed draws on (already_treated_patients), so zodasiran starts from the untreated remainder instead of the whole pool; the 0.5 multiple that stood in for that netting is gone. Units: the fit''s patients are per-beneficiary equivalents, 1.51 per full-year patient; at a full-year net price of $495,200 the same fit reads peak 0.145 (midpoint 1.39, rmse 6.6 on 41 to 400 patients). Case for higher: 4 subcutaneous injections a year against 13 IV infusions, and patients on Evkeeza may switch, which the netting does not allow. Case for lower: Evkeeza reaches age 1 and has long-term and real-world data; the efficacy rests on a 70-patient trial not yet read out; CTX310, a one-time ANGPTL3 editor, is in Phase 1. Evkeeza''s curve cannot separate peak from steepness over 5.5 years (profile: k 0.40 gives peak 0.57, midpoint 4.95, rmse 9.3; k 1.0 rmse 18.1), so the 0.297 depends on the borrowed k',
       updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM second_entrant WHERE ticker = 'ARWR');

UPDATE assumptions
   SET value = 0.1016,
       source = 'Exondys 51 net revenue $154.6mm 2017 (Sarepta FY2017 results release, investorrelations.sarepta.com), $380.7mm 2019, $422.0mm 2020, $454.4mm 2021 (Sarepta FY2021 10-K, sec.gov/Archives/edgar/data/873303/000095017022002517/srpt-20211231.htm). Converted to US patient-equivalents at this seed''s net price ($610,358): x 0.8854 US share (PMO US $747.1mm of $843.8mm in 2022, FY2024 10-K 0000950170-25-029973) / 0.6104 = 224 (2017), 552 (2019), 612 (2020), 659 (2021). Over the US exon 51 pool of 1,554, Exondys held 14% in its first full year and 42% in its fifth (2021). The engine (pool 1,554, inflow 48 a year, the untreated pool held stationary at 0.9702, discontinuation 0.0078, ramp below) needs 0.1016 to reach 659 in year five (0.0953 with no retention set)',
       note = 'MEASURED: Exondys''s own capture of the untreated exon 51 pool, applied as it was measured, with no multiple. It is a revenue-parity figure: patient-equivalents at the model''s own price, so the model reproduces Exondys''s revenue at the same age of launch whatever the true average weight. Exondys''s 659 US patient-equivalents (2021) are out of the pool this seed draws on (already_treated_patients), so z-rostudirsen captures at the incumbent''s measured rate from the untreated remainder rather than replaying Exondys''s launch into all 1,554. The 2018 figure was not confirmed ($295-305mm guidance only) and is left out; the US share for 2017 to 2021 is the 2022 PMO share, a judgement. Case for higher: monthly rather than weekly infusions and higher dystrophin expression, and Exondys patients can switch, which the netting does not allow. Case for lower: Elevidys competes for ambulatory patients aged 4 and over, and at 0.78% discontinuation the stock keeps accumulating on the untreated remainder (see discontinuation_pct)',
       updated_at = datetime('now')
 WHERE id IN (SELECT assumption_id FROM second_entrant WHERE ticker = 'DYN');

DROP TABLE second_entrant;
