-- The daily pulse's schema 2 (pulse.py): an item says which universe companies it is
-- about and how, and carries a key that stays the same on every day its story runs.
--
-- event_key lets a story repeated on Tuesday and Wednesday count once in the week; the
-- rows themselves are kept, one per briefing, since each is what that day's file said.
-- role is subject (the story is about the company), party (the other side of it) or
-- read_across; an item read under schema 1 names every company as a subject.
ALTER TABLE pulse_items ADD COLUMN event_key TEXT;
ALTER TABLE pulse_items ADD COLUMN first_reported TEXT;
ALTER TABLE pulse_items ADD COLUMN is_update INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pulse_items ADD COLUMN phase TEXT;
ALTER TABLE pulse_item_companies ADD COLUMN role TEXT NOT NULL DEFAULT 'subject';
CREATE INDEX IF NOT EXISTS pulse_items_event_key ON pulse_items (event_key);
