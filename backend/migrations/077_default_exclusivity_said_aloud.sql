-- Three seeds that take the engine's 12-year exclusivity default say so, and why.
--
-- Zoldonrasib, AXS-14 and zodasiran carry no loe_year because none of their companies
-- files a patent date for the molecule: Revolution gives a portfolio range, Axsome lists
-- only pending applications and Arrowhead names nothing. The engine then takes 12 years
-- from launch. That is the right handling (no date is invented), but it was silent in the
-- seed. The forecast_start_year note, which the default counts from, now states it.
--
-- Text only; no value moves. The seed files carry the same sentence, and the loader never
-- overwrites a row that exists, so a database that already holds these needs this.

UPDATE assumptions
   SET note = RTRIM(note, '. ') || '. ' || 'LOE: no molecule patent date is filed. Revolution''s FY2025 10-K (0001193125-26-071563, patents section) gives only a 2031 to 2045 range across its tri-complex RAS portfolio, with no date for zoldonrasib, so the engine''s default applies: 12 years from this launch year, 2043. No date is written here because none is filed', updated_at = datetime('now')
 WHERE key = 'forecast_start_year' AND indication_id IS NULL AND scenario = 'base'
   AND note NOT LIKE '%LOE: no molecule patent date is filed%'
   AND asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                     WHERE c.ticker = 'RVMD' AND LOWER(TRIM(a.generic_name)) = 'zoldonrasib');

UPDATE assumptions
   SET note = RTRIM(note, '. ') || '. ' || 'LOE: no molecule patent date is filed. Axsome''s FY2025 10-K (0001193125-26-064267, patents section) lists only pending US and foreign applications for AXS-14, so the engine''s default applies: 12 years from this launch year, 2042. No date is written here because none is filed', updated_at = datetime('now')
 WHERE key = 'forecast_start_year' AND indication_id IS NULL AND scenario = 'base'
   AND note NOT LIKE '%LOE: no molecule patent date is filed%'
   AND asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                     WHERE c.ticker = 'AXSM' AND LOWER(TRIM(a.generic_name)) = 'axs-14 (esreboxetine)');

UPDATE assumptions
   SET note = RTRIM(note, '. ') || '. ' || 'LOE: no molecule patent date is filed. Arrowhead''s FY2025 10-K (0000879407-25-000029, patents section) names no expiry for zodasiran, so the engine''s default applies: 12 years from this launch year, 2041. No date is written here because none is filed', updated_at = datetime('now')
 WHERE key = 'forecast_start_year' AND indication_id IS NULL AND scenario = 'base'
   AND note NOT LIKE '%LOE: no molecule patent date is filed%'
   AND asset_id IN (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
                     WHERE c.ticker = 'ARWR' AND LOWER(TRIM(a.generic_name)) = 'zodasiran');
