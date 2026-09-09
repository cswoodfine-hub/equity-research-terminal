-- What a reader actually asks about an acquisition.
--
-- A deal was recorded as a verb, a counterparty and a figure: "Acquired ZEGFROVY for
-- $600m upfront, $900m milestones (Oncology), 2026-09-01." That answers one of the five
-- questions a reader has and none of the other four. The questions are always the same
-- shape, whatever the deal:
--
--   why did they buy it            -> rationale
--   what are the financial details -> already held, in the terms columns
--   how will they use it           -> intended_use
--   what does the approval cover   -> approval_scope
--   what are the expansion plans   -> expansion
--
-- Each is stored only where the source states it, in the source's own words, so a deal
-- announced in three lines carries three lines and is not padded out to five. Null is a
-- fact here: it says the announcement did not address that question.
ALTER TABLE deals ADD COLUMN rationale TEXT;
ALTER TABLE deals ADD COLUMN intended_use TEXT;
ALTER TABLE deals ADD COLUMN approval_scope TEXT;
ALTER TABLE deals ADD COLUMN expansion TEXT;
