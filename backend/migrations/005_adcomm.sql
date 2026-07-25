-- FDA advisory committee meetings, read from the Federal Register. An advisory
-- committee meeting is a binary regulatory event; the panel votes days before the FDA
-- decision. This table is the calendar of scheduled meetings across all sponsors, so
-- the view has agency context, while the matched ones are also written to catalysts.
-- Additive only.
--
-- The FDA publishes several notices for one meeting (an establishment notice, then
-- amendments), so meeting_key (committee, date, application number) is the meeting's
-- identity and dedupes them; company_id and asset_id are set when the meeting matches a
-- tracked company on its application number or its sponsor and product names.

CREATE TABLE adcomm_meetings (
    id                 INTEGER PRIMARY KEY,
    meeting_key        TEXT UNIQUE,             -- committee|date|appno, dedupes notices
    committee          TEXT,
    meeting_date       TEXT,
    application_number TEXT,                    -- internal_code shape, e.g. BLA125827
    application_label  TEXT,                    -- as printed, e.g. "BLA 125827"
    sponsor            TEXT,
    product            TEXT,
    company_id         INTEGER REFERENCES companies(id),
    asset_id           INTEGER REFERENCES assets(id),
    url                TEXT,
    document_number    TEXT,
    published          TEXT,
    fetched_at         TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_adcomm_date ON adcomm_meetings(meeting_date);
CREATE INDEX idx_adcomm_company ON adcomm_meetings(company_id, meeting_date);
