-- Kesimpta stood in the book twice, and the row holding it was called Arzerra.
--
-- BLA125326 is ofatumumab under two brands. Arzerra was approved in 2009 for chronic
-- lymphocytic leukaemia and withdrawn from commercial sale; Kesimpta was approved under
-- the same application in 2020 for multiple sclerosis and is what Novartis reports:
-- 4,426mm USD in FY2025. The book held the application as one asset, and a register
-- that lists the application under both names wrote "Arzerra" over it. Everything on
-- the row stayed Kesimpta's: the label ("KESIMPTA is indicated for the treatment of
-- relapsing forms of multiple sclerosis"), the two MS studies and the thirteen completed
-- ones, the Part D prescribing, the revenue and the forecast built on it. Only the name
-- was wrong, and with it the exclusivity, since the 20-F's date is read by brand: the
-- row was dated by the application's statutory twelve years, which ended in 2021.
--
-- On 2026-11-21, once an application could carry two products, the approvals fetcher
-- found no asset called Kesimpta and made one. The revenue fetcher, which goes by brand,
-- filled it: the same six revenue rows, the same two regions, the same eighteen
-- assumptions. So Novartis carried ofatumumab at 22.36 a share as "Arzerra", a product
-- no longer sold, dated to an exclusivity that had lapsed, and at 13.70 a share as
-- Kesimpta: 36.06 of a 131.19 a share book, for one product. The Portfolio tab showed
-- 4.43bn of revenue against "lapsed".
--
-- assets_util.upsert_asset no longer renames an asset to another product's brand, so
-- this does not recur. Here the name goes back to the row that is the product, the
-- two-day-old row takes the name it was a stand-in for, and what was copied onto it is
-- removed. Nothing is lost: every deleted row is on the other asset, figure for figure
-- (checked on 2026-11-23: eighteen assumptions and six revenue rows, no difference).
-- Novartis reports no revenue for Arzerra, so that asset is left with its approval and
-- its statutory exclusivity and no model.
--
-- Keyed on the ticker, the application, the brand and the label, never an asset id,
-- which does not survive a rebuild. The row that is Kesimpta is the one called Arzerra
-- whose label names Kesimpta; the stand-in is the one called Kesimpta with no label. On
-- a book where either is missing, both selections are empty and nothing below matches.

CREATE TEMP TABLE _ofatumumab AS
SELECT
  (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
    WHERE c.ticker = 'NVS' AND a.internal_code = 'BLA125326'
      AND LOWER(TRIM(a.brand_name)) = 'arzerra'
      AND EXISTS (SELECT 1 FROM labels l WHERE l.asset_id = a.id
                     AND UPPER(l.indications_text) LIKE '%KESIMPTA%')) AS product,
  (SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
    WHERE c.ticker = 'NVS' AND a.internal_code = 'BLA125326'
      AND LOWER(TRIM(a.brand_name)) = 'kesimpta'
      AND NOT EXISTS (SELECT 1 FROM labels l WHERE l.asset_id = a.id)) AS standin;

-- Both or neither: a book with only one of the two rows is not the case this repairs.
UPDATE _ofatumumab SET product = NULL, standin = NULL
 WHERE product IS NULL OR standin IS NULL;

-- The product codes RxNav gives for the brand were filed on the stand-in, and the
-- product's own row has none.
UPDATE drug_codes SET asset_id = (SELECT product FROM _ofatumumab)
 WHERE asset_id = (SELECT standin FROM _ofatumumab);

-- What was copied. Each is keyed to the brand's sales, which the product's row holds.
DELETE FROM asset_revenue WHERE asset_id = (SELECT standin FROM _ofatumumab);
DELETE FROM asset_revenue_regions WHERE asset_id = (SELECT standin FROM _ofatumumab);
DELETE FROM assumptions WHERE asset_id = (SELECT standin FROM _ofatumumab);
DELETE FROM drug_demand WHERE asset_id = (SELECT standin FROM _ofatumumab);

-- The names, last, since the selections above are made by them.
UPDATE assets SET brand_name = 'Arzerra', updated_at = datetime('now')
 WHERE id = (SELECT standin FROM _ofatumumab);
UPDATE assets SET brand_name = 'Kesimpta', updated_at = datetime('now')
 WHERE id = (SELECT product FROM _ofatumumab);

DROP TABLE _ofatumumab;
