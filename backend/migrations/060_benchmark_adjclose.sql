-- A benchmark keeps its adjusted close beside its close, because for an ETF they are
-- two different things.
--
-- XLV's close ten years ago was 73.34 and its adjusted close 62.04, an 18.2% gap, which
-- is the dividend stream the sector has paid since. The S&P index has the two identical
-- at 2177.18, because an index pays nothing. So a relative figure computed on closes
-- charges the whole of a sector ETF's dividends to the sector as underperformance, and
-- a beta regressed against one benchmark on closes and another on adjusted closes is
-- comparing two different series.
--
-- Both are stored and a reader compares like with like. Existing rows are ^GSPC only,
-- where the two are equal, so the backfill below is exact rather than an assumption;
-- it is still written only where a row exists, so a database built from nothing does
-- nothing here.
--
-- Nothing about an index or an ETF goes in ``prices``. Its company_id is NOT NULL and
-- migration 048 states what a pseudo-company row would do to the treemap, the comps
-- table and the coverage counts.

ALTER TABLE benchmark_prices ADD COLUMN adjclose REAL;

UPDATE benchmark_prices
   SET adjclose = close
 WHERE adjclose IS NULL AND symbol = '^GSPC' AND close IS NOT NULL;
