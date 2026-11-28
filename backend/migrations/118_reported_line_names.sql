-- Four products named for the line their company reports, renamed by a register pass.
--
-- Each row was created from product revenue and named as the filing names the line. The
-- weekly register pass of 2026-11-28 wrote a presentation's brand over the name
-- (assets_util.upsert_asset passed any brand sharing a first word; it now fills an empty
-- name and tidies the same one, nothing else), so the four seed files that bind by the
-- line's name loaded nothing and the next product revenue read would have made each row
-- a second time. The name goes back only where the row is still the revenue-created one
-- under the name the pass gave it and no row of that company holds the line's name.
UPDATE assets SET brand_name = 'Rybrevant / Lazcluze', updated_at = datetime('now')
 WHERE brand_name = 'Rybrevant Faspro' AND notes LIKE 'created from product revenue reported in the filing%'
   AND owner_company_id = (SELECT id FROM companies WHERE ticker = 'JNJ')
   AND NOT EXISTS (SELECT 1 FROM assets o WHERE o.owner_company_id = assets.owner_company_id
                    AND o.brand_name = 'Rybrevant / Lazcluze');
UPDATE assets SET brand_name = 'Simponi Simponi Aria', updated_at = datetime('now')
 WHERE brand_name = 'Simponi' AND notes LIKE 'created from product revenue reported in the filing%'
   AND owner_company_id = (SELECT id FROM companies WHERE ticker = 'JNJ')
   AND NOT EXISTS (SELECT 1 FROM assets o WHERE o.owner_company_id = assets.owner_company_id
                    AND o.brand_name = 'Simponi Simponi Aria');
UPDATE assets SET brand_name = 'Piqray Vijoice', updated_at = datetime('now')
 WHERE brand_name = 'Vijoice' AND notes LIKE 'created from product revenue reported in the filing%'
   AND owner_company_id = (SELECT id FROM companies WHERE ticker = 'NVS')
   AND NOT EXISTS (SELECT 1 FROM assets o WHERE o.owner_company_id = assets.owner_company_id
                    AND o.brand_name = 'Piqray Vijoice');
UPDATE assets SET brand_name = 'Nurtec ODT / Vydura', updated_at = datetime('now')
 WHERE brand_name = 'Nurtec Odt' AND notes LIKE 'created from product revenue reported in the filing%'
   AND owner_company_id = (SELECT id FROM companies WHERE ticker = 'PFE')
   AND NOT EXISTS (SELECT 1 FROM assets o WHERE o.owner_company_id = assets.owner_company_id
                    AND o.brand_name = 'Nurtec ODT / Vydura');
