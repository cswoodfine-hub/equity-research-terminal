-- The opening of a press release a result was read from, up to its "About" sections.
--
-- A release names the study it reports in its first paragraphs ("in TRANSCEND-T2D-2, a
-- Phase 3 trial", "the Phase 3 ATTAIN-OSA study") and the result sentence the classifier
-- quotes often does not. The tie read the quote and the headline only, so a release that
-- named its study in the opening tied to nothing. Kept so the tie can read it, and only
-- where it names one study and no other.
ALTER TABLE trial_readouts ADD COLUMN lead TEXT;
