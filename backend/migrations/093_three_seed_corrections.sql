-- Three seeded numbers corrected where they stand, found in the research round of 2026-10-28.
--
-- The seed loader never overwrites a row that exists, so a number wrong in the book is
-- corrected here as well as in its file, as 068 corrected the myeloma pool. Only a row
-- still carrying the old value moves: a row an analyst has since set to some other
-- number is a decision, not the error this corrects. Each old row is snapshotted and each
-- change written to the edit ledger, so what the book used before stays on the record.
--
-- Rinvoq, Takayasu arteritis: penetration 0.2 put 42% of every US patient on the drug
-- once the pool could replenish; 0.0768 is solved to the middle of Rinvoq's own layers.
-- Evenity, osteogenesis imperfecta: the layer priced the children of the paediatric study
-- on the adult row; retired, because the paediatric row now carries them.
-- Baxfendy: discontinuation 0.30 carried a solid tumour rationale; an antihypertensive
-- loses about half its patients a year (Vrijens, BMJ 2008).

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'seed_correction_2026_10_28', 'assumption', 'assumption:' || id,
       json_object('asset_id', asset_id, 'key', key, 'value', value, 'source', source,
                   'replaced_on', date('now'))
  FROM assumptions
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'ABBV' AND a.brand_name = 'Rinvoq')
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Takayasu Arteritis')
   AND key = 'penetration_peak_pct' AND scenario = 'base' AND value = 0.2;

INSERT INTO assumption_edits
    (asset_id, indication_id, region, scenario, key, year, op, old_value, old_unit,
     old_source, old_note, new_value, new_unit, new_source, new_note, reason, rationale,
     ticker, asset_name, indication_name)
SELECT asset_id, indication_id, region, scenario, key, year, 'update', value, unit,
       source, note, 0.0768, unit, 'a judgement, solved through the engine so the treated stock peaks at 20.5% of eligible patients, the middle of the shares Rinvoq''s own layers reach (systemic lupus 15.4%, hidradenitis suppurativa 20.5%, vitiligo 23.2%), measured on a copy of the book on 2026-10-28. At 0.2 the stock reached 42% of every US Takayasu patient once the incidence row let the pool replenish, double any sibling. The competitive case stands: no agent carries a US label for Takayasu arteritis, and standard of care is glucocorticoids with off-label methotrexate, tocilizumab and TNF inhibitors', note, 'correction', 'at 0.2 the treated stock reached 42% of every US Takayasu patient, double any of Rinvoq''s other layers',
       'ABBV', 'Rinvoq', 'Takayasu Arteritis'
  FROM assumptions
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'ABBV' AND a.brand_name = 'Rinvoq')
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Takayasu Arteritis')
   AND key = 'penetration_peak_pct' AND scenario = 'base' AND value = 0.2;

UPDATE assumptions
   SET value = 0.0768, source = 'a judgement, solved through the engine so the treated stock peaks at 20.5% of eligible patients, the middle of the shares Rinvoq''s own layers reach (systemic lupus 15.4%, hidradenitis suppurativa 20.5%, vitiligo 23.2%), measured on a copy of the book on 2026-10-28. At 0.2 the stock reached 42% of every US Takayasu patient once the incidence row let the pool replenish, double any sibling. The competitive case stands: no agent carries a US label for Takayasu arteritis, and standard of care is glucocorticoids with off-label methotrexate, tocilizumab and TNF inhibitors', updated_at = datetime('now')
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'ABBV' AND a.brand_name = 'Rinvoq')
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Takayasu Arteritis')
   AND key = 'penetration_peak_pct' AND scenario = 'base' AND value = 0.2;

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'seed_correction_2026_10_28', 'assumption', 'assumption:' || id,
       json_object('asset_id', asset_id, 'key', key, 'value', value, 'source', source,
                   'replaced_on', date('now'))
  FROM assumptions
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'AMGN' AND a.brand_name = 'Evenity')
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Osteogenesis Imperfecta')
   AND key = 'penetration_peak_pct' AND scenario = 'base' AND value = 0.3;

INSERT INTO assumption_edits
    (asset_id, indication_id, region, scenario, key, year, op, old_value, old_unit,
     old_source, old_note, new_value, new_unit, new_source, new_note, reason, rationale,
     ticker, asset_name, indication_name)
SELECT asset_id, indication_id, region, scenario, key, year, 'update', value, unit,
       source, note, 0.0, unit, 'retired 2026-10-28: this layer priced the children of NCT05972551 on the adult osteogenesis imperfecta row. The readout now links to the asset''s Pediatric osteogenesis imperfecta row (data/paediatric_indications.csv), which carries its own layer, so the same children are counted once, there', note, 'correction', 'the same children are priced on the paediatric row, which the readout now links to',
       'AMGN', 'Evenity', 'Osteogenesis Imperfecta'
  FROM assumptions
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'AMGN' AND a.brand_name = 'Evenity')
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Osteogenesis Imperfecta')
   AND key = 'penetration_peak_pct' AND scenario = 'base' AND value = 0.3;

UPDATE assumptions
   SET value = 0.0, source = 'retired 2026-10-28: this layer priced the children of NCT05972551 on the adult osteogenesis imperfecta row. The readout now links to the asset''s Pediatric osteogenesis imperfecta row (data/paediatric_indications.csv), which carries its own layer, so the same children are counted once, there', updated_at = datetime('now')
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'AMGN' AND a.brand_name = 'Evenity')
   AND indication_id IN (SELECT id FROM indications WHERE name = 'Osteogenesis Imperfecta')
   AND key = 'penetration_peak_pct' AND scenario = 'base' AND value = 0.3;

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'seed_correction_2026_10_28', 'assumption', 'assumption:' || id,
       json_object('asset_id', asset_id, 'key', key, 'value', value, 'source', source,
                   'replaced_on', date('now'))
  FROM assumptions
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'AZN' AND a.brand_name = 'Baxfendy')
   AND indication_id IS NULL
   AND key = 'discontinuation_pct' AND scenario = 'base' AND value = 0.30;

INSERT INTO assumption_edits
    (asset_id, indication_id, region, scenario, key, year, op, old_value, old_unit,
     old_source, old_note, new_value, new_unit, new_source, new_note, reason, rationale,
     ticker, asset_name, indication_name)
SELECT asset_id, indication_id, region, scenario, key, year, 'update', value, unit,
       source, note, 0.50, unit, 'Vrijens B et al., ''Adherence to prescribed antihypertensive drug treatments: longitudinal study of electronically compiled dosing histories'', BMJ 2008;336:1114 (PMC2386633), 4,783 patients across 21 Phase IV studies: ''about half of the patients who were prescribed an antihypertensive drug had stopped taking it within one year''', note, 'correction', '0.30 carried a rationale for solid tumour therapy, not an antihypertensive',
       'AZN', 'Baxfendy', NULL
  FROM assumptions
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'AZN' AND a.brand_name = 'Baxfendy')
   AND indication_id IS NULL
   AND key = 'discontinuation_pct' AND scenario = 'base' AND value = 0.30;

UPDATE assumptions
   SET value = 0.50, source = 'Vrijens B et al., ''Adherence to prescribed antihypertensive drug treatments: longitudinal study of electronically compiled dosing histories'', BMJ 2008;336:1114 (PMC2386633), 4,783 patients across 21 Phase IV studies: ''about half of the patients who were prescribed an antihypertensive drug had stopped taking it within one year''', updated_at = datetime('now')
  WHERE asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                      WHERE c.ticker = 'AZN' AND a.brand_name = 'Baxfendy')
   AND indication_id IS NULL
   AND key = 'discontinuation_pct' AND scenario = 'base' AND value = 0.30;
