-- How well each assumption is evidenced, as a field rather than free text: filed,
-- measured, published, analogue, convention or judgement (evidence.py). A grade written by
-- the rules from the row's own source is unreviewed and follows the text on each refresh;
-- one an analyst sets, in the editor or a seed's evidence column, is reviewed and stays.
ALTER TABLE assumptions ADD COLUMN evidence TEXT;
ALTER TABLE assumptions ADD COLUMN evidence_reviewed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE company_lines ADD COLUMN evidence TEXT;
ALTER TABLE company_lines ADD COLUMN evidence_reviewed INTEGER NOT NULL DEFAULT 0;
