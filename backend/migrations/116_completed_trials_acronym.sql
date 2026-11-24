-- The study's own name on a completed study (ATTAIN-OSA, IDEAL, Tranquillo).
--
-- A company announces a result in the months after a study completes, and names the study
-- by this name. The pipeline fetch reads running studies only and carries the acronym for
-- them; once a study completes it is never read that way again, and the completed-study
-- fetch kept no name, so a release could tie to no study it reported.
ALTER TABLE completed_trials ADD COLUMN acronym TEXT;
