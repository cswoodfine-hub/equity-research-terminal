-- Annotations: the analyst's own line, attached to a company, a change, or a
-- catalyst. Additive only; nothing existing is touched.

CREATE TABLE annotations (
    id          INTEGER PRIMARY KEY,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ticker      TEXT NOT NULL,
    entity_type TEXT NOT NULL,       -- company, change, catalyst
    entity_id   TEXT,                -- changes.id or catalysts.id as text; null = company
    body        TEXT NOT NULL
);
CREATE INDEX idx_annotations_entity ON annotations(ticker, entity_type, entity_id);
