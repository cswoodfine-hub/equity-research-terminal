-- Where a deal's announced value came from.
--
-- A filing names the counterparty far more reliably than it names the price: Lilly's
-- April 10-Q listed four acquisitions with no figure against any of them, while the
-- headlines that announced the same four all carried a number. So a headline is allowed
-- to fill a size the filing left blank, and this column records that it did. It never
-- replaces a figure the filing states, and the counterparty, quote and accession stay
-- the filing's own.
--
-- 'filing' or 'news', or null for a row that states no value at all.

ALTER TABLE deals ADD COLUMN announced_value_source TEXT;

UPDATE deals SET announced_value_source = CASE WHEN accession IS NULL THEN 'news'
                                               ELSE 'filing' END
 WHERE announced_value IS NOT NULL;
