-- Approved efficacy supplements from openFDA drugsfda. An approved efficacy
-- supplement is a label expansion by definition, carrying its application number and
-- approval date, so it corroborates the DailyMed label signal and often arrives
-- first. Additive only.
--
-- drugsfda covers CDER only. Cell and gene therapies are CBER-regulated and absent
-- here; those are tracked through DailyMed labels and the Purple Book instead, which
-- the labels view already carries.

CREATE TABLE supplements (
    id                    INTEGER PRIMARY KEY,
    asset_id              INTEGER REFERENCES assets(id),
    application_number    TEXT NOT NULL,
    submission_number     TEXT NOT NULL,
    submission_class_code TEXT,              -- EFFICACY
    approval_date         TEXT,
    description           TEXT,
    source                TEXT DEFAULT 'openfda',
    fetched_at            TEXT DEFAULT (datetime('now')),
    UNIQUE(application_number, submission_number)
);
CREATE INDEX idx_supplements_asset ON supplements(asset_id, approval_date);
