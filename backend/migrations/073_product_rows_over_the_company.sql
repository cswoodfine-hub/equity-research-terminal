-- A product row larger than its company is a misread, and comes out.
--
-- revenue_earnings read Alnylam's Q4 2025 exhibit at millions where the table prints
-- thousands, so Amvuttra went into the book at $826,588mm for the quarter against $2,314mm
-- for the year, and Onpattro, Givlaari and Oxlumo a thousandfold high beside it. Q4 has no
-- quarterly total on file to check a row against, so nothing refused them. The reader now
-- refuses a row above twice the company's latest annual revenue where no quarter is on
-- file; this removes the rows it would have refused. The figures are the exhibit's own and
-- a refresh does not re-read them once refused, so nothing true is lost: the full-year rows
-- from the SEC data sets stand beside them.
--
-- Only an unreviewed earnings-exhibit row goes, and only above the same ceiling the reader
-- now applies. The removed rows are snapshotted first.

CREATE TEMP TABLE over_ceiling AS
SELECT r.id AS revenue_id
  FROM asset_revenue r
  JOIN assets a ON a.id = r.asset_id
 WHERE r.source = 'earnings_exhibit' AND r.is_curated = 0
   AND r.value > 2.0 * (SELECT f.value FROM financials f
                         WHERE f.company_id = a.owner_company_id AND f.metric = 'Revenues'
                           AND f.period_type = 'FY'
                         ORDER BY f.period_end DESC LIMIT 1);

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'product_row_over_company', 'asset_revenue', 'asset_revenue:' || r.id,
       json_object('asset_id', r.asset_id, 'fiscal_year', r.fiscal_year, 'period', r.period,
                   'value', r.value, 'source', r.source, 'note', r.note,
                   'removed_on', date('now'))
  FROM asset_revenue r JOIN over_ceiling o ON o.revenue_id = r.id;

DELETE FROM asset_revenue WHERE id IN (SELECT revenue_id FROM over_ceiling);

DROP TABLE over_ceiling;
