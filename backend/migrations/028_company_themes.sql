-- What platform a company says it runs, read from its own filing.
--
-- Separate from asset_themes on purpose. An asset theme says what one drug is, read
-- from that drug's own name or label. This says what the company describes itself as
-- doing, which is a different claim and a weaker one: a company that calls itself a
-- gene editing company may also run an unrelated small molecule.
--
-- It exists because the asset axis cannot reach the companies that matter most to it.
-- Beam's programmes are named BEAM-101 and CTX112, ClinicalTrials gives a dosing
-- instruction where a description would be, and no free field says what those drugs
-- are. The 10-K does: "our proprietary base editing platform". So the company is
-- classified where its assets cannot be, and the two are never mixed in one count.
--
-- The evidence is the phrase, so a reader can see that "our suite of gene editing" is
-- Beam describing itself and not Beam describing a competitor.

CREATE TABLE company_themes (
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    theme       TEXT NOT NULL,
    evidence    TEXT,
    accession   TEXT,
    derived_at  TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (company_id, theme)
);
CREATE INDEX idx_company_themes_theme ON company_themes(theme);
