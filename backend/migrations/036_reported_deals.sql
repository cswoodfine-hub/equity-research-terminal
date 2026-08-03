-- Deals the press reports are being discussed, which nobody has announced.
--
-- Its own table rather than a flag on deals, so that no query anywhere can sum a rumour
-- into a total by forgetting a WHERE clause. Nothing here is a deal: the announced-value
-- sums, the acquisitions line on the financials tab and the deal counts all read `deals`
-- and never this.
--
-- Only the very large ones are kept. A merger being weighed at four hundred billion
-- moves both companies on the day and belongs on the front page; a report that someone
-- is "exploring options" for a subsidiary is chatter, and a lane that takes both fills
-- with the second.
CREATE TABLE IF NOT EXISTS reported_deals (
    id              INTEGER PRIMARY KEY,
    company_id      INTEGER NOT NULL REFERENCES companies(id),
    counterparty    TEXT NOT NULL,
    -- What the report says is being considered: a merger, an acquisition, a stake.
    deal_type       TEXT,
    -- The figure the report states, and the same as a number. Reported, never announced.
    reported_value  TEXT,
    reported_usd    REAL,
    -- The headline verbatim, so any row can be read against the words it came from, and
    -- the publisher that wrote it. A rumour is only worth as much as who is reporting it.
    quote           TEXT NOT NULL,
    publisher       TEXT,
    article_url     TEXT,
    event_date      TEXT,
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, counterparty, event_date)
);

CREATE INDEX IF NOT EXISTS idx_reported_deals_company
    ON reported_deals(company_id, event_date DESC);
