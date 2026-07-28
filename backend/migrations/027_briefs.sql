-- The thematic brief: one modality read across every company that runs it.
--
-- Kept alongside `insights` rather than inside it, because an insight belongs to a
-- company and the whole point of a brief is that it does not. Appended, never updated,
-- so a brief written today can be read back against the one written last month and the
-- change in the read is itself visible.
--
-- `model` records what wrote it. Without a key the rules layer writes it and says so,
-- which has to survive into storage: a rules brief and a generated one read very
-- differently and must never be mistaken for each other.

CREATE TABLE briefs (
    id           INTEGER PRIMARY KEY,
    theme        TEXT NOT NULL,
    generated_at TEXT DEFAULT (datetime('now')),
    body         TEXT NOT NULL,
    model        TEXT,
    horizon_days INTEGER
);
CREATE INDEX idx_briefs_theme ON briefs(theme, generated_at);
