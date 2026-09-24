-- A company's Legal Entity Identifier, the key a filer outside the SEC is found by.
--
-- An SEC filer is found by its CIK. A company listed in the EU files its annual report
-- in the European Single Electronic Format instead, and filings.xbrl.org, the index of
-- those reports, is keyed by LEI. Bayer is the case this is for: no CIK, so EDGAR has
-- nothing for it, and with an LEI its ESEF reports give it the financials a valuation
-- needs (fetchers/financials_esef.py).
--
-- The value comes from the seed CSV and is checked against the ISO 17442 check digits on
-- load, so a mistyped identifier is refused rather than stored. The fetcher checks it a
-- second time against the entity the index files each report under.

ALTER TABLE companies ADD COLUMN lei TEXT;
