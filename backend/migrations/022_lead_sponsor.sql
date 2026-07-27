-- Who the registry says leads a study.
--
-- A study can sit under a company because that company acquired the one that registered
-- it, and the registry still names the original sponsor months later. Storing that name
-- is what makes the attribution explain itself: a Lilly trial whose lead sponsor reads
-- "Centessa Pharmaceuticals" is there because Lilly bought Centessa, and nothing has to
-- be inferred from the absence of an explanation.

ALTER TABLE trials ADD COLUMN lead_sponsor TEXT;
ALTER TABLE completed_trials ADD COLUMN lead_sponsor TEXT;
