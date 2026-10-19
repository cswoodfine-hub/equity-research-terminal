-- A 52/53-week year that ends in the first week of January belongs to the year before.
--
-- Every row was labelled with the year of its period end, so Exelixis's fiscal 2025,
-- which ended on 2 January 2026, sat under 2026, and Johnson & Johnson's fiscal 2022,
-- which ended on 1 January 2023, shared 2023 with its fiscal 2023. The parser now takes
-- the year from statements.fiscal_year_of; these are the rows it labelled before.
--
-- Product rows first, while the totals still carry their old labels. The MD&A reader
-- took its year from the latest reported total, so its rows inherited that label. A row
-- is moved only where the total's year is unambiguous: one full-year revenue row under
-- that label, ending in the first week of January. Johnson & Johnson's 2023 holds two and
-- is left for the next refresh to rewrite. The data sets' rows are not touched: their
-- period end is rounded to the month, so 2 January 2026 already read as 31 December 2025.
-- One transaction. The product move reads the totals' old labels and the last statement
-- corrects them, so a run cut off between the two would, run again, move the product rows
-- a second year back onto the data sets' rows and delete them as duplicates.
BEGIN;
UPDATE asset_revenue
   SET fiscal_year = -(fiscal_year - 1)
 WHERE source IN ('mdna_10k', 'mdna_10k_discovered')
   AND period = 'FY'
   AND EXISTS (
       SELECT 1
         FROM assets a
         JOIN financials f ON f.company_id = a.owner_company_id
        WHERE a.id = asset_revenue.asset_id
          AND f.metric = 'Revenues' AND f.period_type = 'FY'
          AND f.fiscal_year = asset_revenue.fiscal_year
          AND CAST(substr(f.period_end, 1, 4) AS INTEGER) = f.fiscal_year
          AND substr(f.period_end, 6, 2) = '01'
          AND CAST(substr(f.period_end, 9, 2) AS INTEGER) <= 7
          AND NOT EXISTS (
              SELECT 1 FROM financials g
               WHERE g.company_id = f.company_id AND g.metric = 'Revenues'
                 AND g.period_type = 'FY' AND g.fiscal_year = f.fiscal_year
                 AND g.period_end <> f.period_end));
-- Moved through negative years so no two rows ever hold one label at once. A row whose
-- right year is already on file is that year's figure under the wrong label, and goes.
UPDATE OR IGNORE asset_revenue SET fiscal_year = -fiscal_year WHERE fiscal_year < 0;
DELETE FROM asset_revenue WHERE fiscal_year < 0;

-- The totals are keyed by period end, so the label corrects in place.
UPDATE financials
   SET fiscal_year = CAST(substr(period_end, 1, 4) AS INTEGER) - 1
 WHERE substr(period_end, 6, 2) = '01'
   AND CAST(substr(period_end, 9, 2) AS INTEGER) <= 7
   AND fiscal_year = CAST(substr(period_end, 1, 4) AS INTEGER);
COMMIT;
