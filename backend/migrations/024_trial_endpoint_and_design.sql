-- What a trial is measuring, and how it is built.
--
-- The diff engine has watched a trial's status, phase and completion date since it was
-- written. Those catch a delay and a stall. They do not catch the thing an analyst
-- reading the field would notice first: a sponsor changing the primary endpoint, or
-- dropping the blind, or halving enrolment, part way through.
--
-- A changed primary endpoint mid-trial is a real and increasingly common event, and it
-- is the kind of claim nobody can make from a snapshot of today: it needs the previous
-- value, which is what this stores.

ALTER TABLE trials ADD COLUMN primary_outcome TEXT;   -- the measure, as worded
ALTER TABLE trials ADD COLUMN design TEXT;            -- allocation, masking, purpose
