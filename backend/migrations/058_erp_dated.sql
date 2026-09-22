-- The equity risk premium says which estimate it is, and on what day.
--
-- 440 rows carried 0.05 sourced "Damodaran US ERP estimate". His estimate is not 0.05
-- and was not 0.05 on any recent date: on 1 September 2026 he publishes 4.14% (trailing
-- twelve month, with adjusted payout), 4.09% (trailing twelve month cash yield), 6.05%
-- (average cash flow yield over ten years), 3.80% (net cash yield) and 3.56%
-- (normalised earnings and payout). The row named an author and did not carry his
-- number, and it carried no date and no URL, which made it the only input in the
-- discount-rate chain a reader could not trace.
--
-- Two ways to fix that: restate the value to the estimate the source names, or restate
-- the source to say it is a convention. The value moves, because this terminal grades
-- published above convention and because a dated published figure can be refreshed
-- next month with one edit, where a round number cannot be refreshed at all.
--
-- The headline variant is the one taken. He quotes it first and it is the one
-- practitioners cite. Naming the variant in the source is what makes the choice
-- visible and changeable rather than implied.
--
-- The 0.22% US default spread is NOT added back. His instruction is to add it only
-- "if you are netting that out of the treasury to get to an adjusted dollar riskfree
-- rate of 4.53%". This book discounts at the raw ten-year, so 4.14% is the figure that
-- pairs with it, and the two legs are consistent in kind. They still differ in age:
-- his premium is struck against his own 4.75% Treasury on 1 September and the book now
-- reads the Treasury live. That residual is stated in the basis rather than hidden,
-- which is why the source carries his risk-free rate as well as his premium.
--
-- Measured with tools/rate_sensitivity.py on 2026-09-22, this raises equity per share
-- by a median 6.44%, from 3.29% at CRISPR to 9.69% at Novo Nordisk.
--
-- The old rows are snapshotted first, one per distinct value and source, so what the
-- book used before is on the record. A database being built from nothing holds no
-- assumptions yet and keeps no history.

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'erp_restatement', 'assumption', 'erp:assumptions',
       json_object('value', value, 'source', source, 'rows', COUNT(*),
                   'replaced_on', date('now'))
  FROM assumptions
 WHERE key = 'erp'
 GROUP BY value, source;

INSERT INTO snapshots (source, entity_type, entity_key, payload)
SELECT 'erp_restatement', 'assumption', 'erp:company_lines',
       json_object('value', value, 'source', source, 'rows', COUNT(*),
                   'replaced_on', date('now'))
  FROM company_lines
 WHERE key = 'erp'
 GROUP BY value, source;

-- Where the old source was an explanation rather than a citation (Vertex's three rows
-- say why they exist at all), the explanation moves to the note rather than being lost.
UPDATE assumptions
   SET note = TRIM(COALESCE(note, '') || ' ' || source)
 WHERE key = 'erp' AND source NOT LIKE 'Damodaran%';

UPDATE assumptions
   SET value = 0.0414,
       source = 'Damodaran implied US equity risk premium, 2026-09-01: 4.14% on the trailing twelve month with adjusted payout basis, against his own 4.75% US Treasury. The 0.22% US default spread is not added back, since this book discounts at the raw ten-year (pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm)',
       updated_at = datetime('now')
 WHERE key = 'erp';

UPDATE company_lines
   SET note = TRIM(COALESCE(note, '') || ' ' || source)
 WHERE key = 'erp' AND source NOT LIKE 'Damodaran%';

UPDATE company_lines
   SET value = 0.0414,
       source = 'Damodaran implied US equity risk premium, 2026-09-01: 4.14% on the trailing twelve month with adjusted payout basis, against his own 4.75% US Treasury. The 0.22% US default spread is not added back, since this book discounts at the raw ten-year (pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm)',
       updated_at = datetime('now')
 WHERE key = 'erp';
