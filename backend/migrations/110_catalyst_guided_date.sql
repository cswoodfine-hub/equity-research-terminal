-- The date a company has given for a readout, held beside the registry's and never over it.
--
-- A derived readout is dated by the registry's primary completion, the day the last
-- patient's primary measurement is taken. A company says when the result will be public,
-- and that is weeks to months later: on 2026-11-22 the book read 68 Phase 3 readouts as
-- overdue, and nine of them had a date from the company that had not come. Biogen's two
-- litifilimab studies completed in September and report "in the first half of December".
--
-- The registry date cannot carry that. derive_readouts rewrites expected_date from the
-- trial on every run, so a guided date written there is gone by morning, and a slip on
-- the registry would no longer be seen against the date it moved from. A second catalyst
-- row at the guided date, which is what the curated file wrote until now, left the study
-- on the calendar twice: once overdue, once to come.
--
-- So the two stand side by side on the study's own row. expected_date stays the
-- registry's. guided_date is the last day of the period the company names, as the
-- curated rows are dated; guided_confidence says how wide that period is (month,
-- quarter, half); guided_source_url is the page and guided_note the sentence. Null on
-- every row no company has dated. Written by curated_catalysts.load from the rows of
-- data/curated_catalysts.csv that name the study they guide.
ALTER TABLE catalysts ADD COLUMN guided_date TEXT;
ALTER TABLE catalysts ADD COLUMN guided_confidence TEXT;
ALTER TABLE catalysts ADD COLUMN guided_source_url TEXT;
ALTER TABLE catalysts ADD COLUMN guided_note TEXT;
