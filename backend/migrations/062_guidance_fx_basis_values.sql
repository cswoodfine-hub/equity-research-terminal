-- The currency basis on the guidance rows already loaded, transcribed by hand.
--
-- The consensus seeds are insert-only, so a row that already exists keeps what it had
-- and adding the column to the CSV changes nothing for a database that has loaded it
-- once. The same is true of the assumption seeds and it is deliberate: a live revision
-- beats the file it started from. So the values are set here, once, and the CSV carries
-- them for a database built from nothing.
--
-- Every value comes from the sentence stored verbatim beside it in
-- data/consensus/guidance_2026.csv, and from nothing else:
--
--   AZN  cer   "guidance for FY 2026 at CER, based on the average foreign exchange
--              rates through 2025"
--   NVO  cer   "Adjusted sales growth is now expected to be 0% to -6% at CER"
--   NVS  cer   "growth vs. prior year in cc"
--   SNY  cer   "sales are now expected to grow by around 10% at CER"
--   AMGN reported  "Scope: total revenues (product sales plus other revenues),
--                   reported USD."
--   GILD reported  "Reported USD."
--   MRK  reported_with_stated_rate_date  "including a positive impact from foreign
--                   exchange of approximately 1% at mid-July 2026 exchange rates"
--   BIIB reported_with_stated_rate_date  "Growth on a reported basis ... assuming
--                   foreign exchange rates as of July 24, 2026 hold for the rest of
--                   the year; no constant-currency basis is stated"
--
-- The four left null are left null on purpose. ABBV, REGN and UTHR guide no revenue at
-- all, and INCY's release names no currency basis. GSK's two rows are not touched
-- either: the stored sentence is a bare "turnover growth of between 3% to 5%" with no
-- basis in it, and GSK guiding at constant currency is something a reader knows rather
-- than something this file records. Its lens is withheld until somebody transcribes
-- the basis from the release, which is the right outcome: the alternative is to guess
-- and print a fair value off it.
--
-- Written only where the column is still null, so a value edited in the terminal
-- survives.

UPDATE consensus_estimates
   SET fx_basis = 'reported'
 WHERE source = 'guidance' AND metric = 'Revenue' AND period = 'FY2026' AND as_of = '2026-08-04'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'AMGN');

UPDATE consensus_estimates
   SET fx_basis = 'cer'
 WHERE source = 'guidance' AND metric = 'RevenueGrowth' AND period = 'FY2026' AND as_of = '2026-07-27'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'AZN');

UPDATE consensus_estimates
   SET fx_basis = 'reported_with_stated_rate_date'
 WHERE source = 'guidance' AND metric = 'RevenueGrowth' AND period = 'FY2026' AND as_of = '2026-07-29'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'BIIB');

UPDATE consensus_estimates
   SET fx_basis = 'reported'
 WHERE source = 'guidance' AND metric = 'ProductSales' AND period = 'FY2026' AND as_of = '2026-08-04'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'GILD');

UPDATE consensus_estimates
   SET fx_basis = 'reported_with_stated_rate_date'
 WHERE source = 'guidance' AND metric = 'Revenue' AND period = 'FY2026' AND as_of = '2026-08-04'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'MRK');

UPDATE consensus_estimates
   SET fx_basis = 'cer'
 WHERE source = 'guidance' AND metric = 'RevenueGrowth' AND period = 'FY2026' AND as_of = '2026-08-04'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'NVO');

UPDATE consensus_estimates
   SET fx_basis = 'cer'
 WHERE source = 'guidance' AND metric = 'RevenueGrowth' AND period = 'FY2026' AND as_of = '2026-07-21'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'NVS');

UPDATE consensus_estimates
   SET fx_basis = 'cer'
 WHERE source = 'guidance' AND metric = 'RevenueGrowth' AND period = 'FY2026' AND as_of = '2026-07-30'
   AND fx_basis IS NULL
   AND company_id = (SELECT id FROM companies WHERE ticker = 'SNY');