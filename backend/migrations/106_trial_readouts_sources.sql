-- Where an announced result came from, and the trial it names.
--
-- The register of announced results read 8-K and 6-K filings only. Roche and Bayer
-- file neither, and Roche alone carried 30 of the 271 readouts that fell due in the
-- last two years; 438 investor-relations releases already on file had a result in
-- their title and were never read as readouts, 300 of them AstraZeneca's, the company
-- with the most unresolved readouts of all. And a trial stopped for futility is rarely
-- announced in a filing at all: the registry records it, with the reason.
--
-- source names the register a row was read from: null for the SEC filings the table
-- began with, 'press' for a company release, 'registry' for ClinicalTrials.gov. nct_id
-- is set where the source states the trial, and a result pinned to its trial resolves
-- that catalyst without matching on drug and phase at all. The accession stays the
-- key: a press row is keyed news:<id>, a registry row registry:<nct>:<date>.
ALTER TABLE trial_readouts ADD COLUMN source TEXT;
ALTER TABLE trial_readouts ADD COLUMN nct_id TEXT;
CREATE INDEX IF NOT EXISTS idx_readouts_nct ON trial_readouts(nct_id);
