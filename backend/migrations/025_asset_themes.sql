-- What kind of thing each drug is, on the modality axis.
--
-- The therapeutic area says what a drug treats; this says what it is. Oncology holds a
-- CAR-T, a checkpoint antibody and a kinase inhibitor, and those three trade on
-- completely different news, so the area cannot carry a thematic view and this can.
--
-- One row per asset per theme, because a drug is often several: a CRISPR-edited
-- autologous cell therapy is gene editing, gene therapy and cell therapy at once, and
-- counting it under only the most specific would empty the broader view.
--
-- The evidence column holds the phrase that produced the tag, so "why is this a
-- radioligand" is answerable from the row rather than by rerunning the classifier.

CREATE TABLE asset_themes (
    asset_id   INTEGER NOT NULL REFERENCES assets(id),
    theme      TEXT NOT NULL,
    evidence   TEXT,           -- the matched phrase, or which theme implied it
    source     TEXT,           -- where the text came from: name, trial, label
    derived_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (asset_id, theme)
);
CREATE INDEX idx_asset_themes_theme ON asset_themes(theme);
