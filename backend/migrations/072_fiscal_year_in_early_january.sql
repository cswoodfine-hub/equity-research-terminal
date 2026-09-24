-- A fiscal year closing in the first week of January is the year before it.
--
-- The company-facts parser labelled every period by the calendar year it ended in. A
-- 52/53-week year closes on the Saturday or Sunday nearest 31 December, which can fall in
-- early January, so such a year took the next year's label: Exelixis's 2024 (ended 3
-- January 2025) sat under 2025 and its 2025 under 2026, leaving no 2024, and Johnson &
-- Johnson's 2022 (ended 1 January 2023) sat beside its 2023 (ended 31 December 2023) under
-- one label, leaving no 2020. Anything that reads a year's revenue, cash flow or R&D by
-- label read the wrong year or one of two. companyfacts.fiscal_year now labels these
-- periods correctly; this relabels the rows already stored. Found building a cost block
-- for Exelixis, whose calibration window came back with 2024 missing.
--
-- Only a row still carrying its calendar-year label moves, so it runs once in effect.

UPDATE financials
   SET fiscal_year = CAST(substr(period_end, 1, 4) AS INTEGER) - 1
 WHERE substr(period_end, 6, 2) = '01'
   AND CAST(substr(period_end, 9, 2) AS INTEGER) <= 7
   AND fiscal_year = CAST(substr(period_end, 1, 4) AS INTEGER)
   AND metric <> 'SharesOutstanding';
