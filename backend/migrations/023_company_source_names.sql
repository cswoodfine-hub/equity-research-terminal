-- The names each source knows a company by, kept with the company.
--
-- A company's own name is not what the sources call it. ClinicalTrials.gov lists
-- AstraZeneca PLC as "AstraZeneca" and Moderna as "ModernaTX, Inc."; openFDA files
-- approvals under a manufacturer string; the Orange and Purple Books use an applicant
-- name. Those five mappings lived in five hardcoded dictionaries across four fetcher
-- modules, so adding one company meant editing five Python files and adding thirty
-- meant editing them thirty times.
--
-- They belong to the company, so they live on it. A fetcher reads the column and falls
-- back to its own map, which keeps the original eighteen working untouched.

ALTER TABLE companies ADD COLUMN ctgov_sponsor TEXT;
ALTER TABLE companies ADD COLUMN openfda_manufacturer TEXT;
ALTER TABLE companies ADD COLUMN openfda_sponsor TEXT;
ALTER TABLE companies ADD COLUMN orange_book_applicant TEXT;
ALTER TABLE companies ADD COLUMN purple_book_applicant TEXT;
