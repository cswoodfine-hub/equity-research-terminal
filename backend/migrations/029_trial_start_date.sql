-- When a study actually began, and when it was first registered.
--
-- Without these the trial table can say what is running and when it finishes, but not
-- how long anything took. Two questions need a start: how many years a molecule spends
-- from first-in-human to approval, and how many new programmes a company put into the
-- clinic in a given year. Both are productivity measures, and neither is answerable
-- from a completion date alone.
--
-- Both dates are kept because they answer different questions. start_date is when
-- dosing began, which is what a development timeline measures. first_posted is when the
-- record appeared on the registry, which is the earliest date a programme became
-- publicly visible, and it is the one that cannot be revised backwards.

ALTER TABLE trials ADD COLUMN start_date TEXT;
ALTER TABLE trials ADD COLUMN first_posted TEXT;
