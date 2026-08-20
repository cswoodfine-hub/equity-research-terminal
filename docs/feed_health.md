# Feed health

Audited 2026-08-20 against all 56 seeded IR feeds. Ten are not delivering, and none of
them was reporting that. A feed answering HTTP 200 with year-old content looked exactly
like a healthy one, and a feed refusing with a 403 wrote the same snapshot as a source
deliberately skipped on its TTL.

Both blind spots are closed in code. `PressIrFetcher.stale_by_days` reports a feed whose
newest item is older than `STALE_FEED_DAYS` (90) as a run note, and the snapshot now
carries `newest_published` so the history shows when a feed went quiet. A fetch that
raises now writes `fetch_kind: "error"` with the exception, instead of borrowing the
`"cache"` stamp that means a skip.

## Stale: answers, but stopped carrying the company

| Ticker | Newest item | Days behind | What the URL now serves |
|---|---|---|---|
| NVS | 2021-11-08 | 1,746 | 10 items, frozen since 2021 |
| MRNA | 2025-05-01 | 476 | 142 items, all "IR Insights" commentary, not the press wire |
| ALNY | 2026-05-13 | 99 | 10 items, just past the threshold, may simply be quiet |

## Unreadable

| Ticker | Failure |
|---|---|
| BMRN, BMY, GILD | HTTP 403, on `*/rss/pressrelease.aspx`, refused with and without the contact header |
| ABEO, ATRA, CABA, CAPR | Feed parses, but no item carries a date, and an undated release never reaches the change feed |

## Why these are not a URL fix

Novartis and Moderna both publish JavaScript-rendered newsrooms. Their listing pages
render through the reader (23kB and 7kB of markdown) and yield zero release links,
because the list is fetched client-side after load. Moderna advertises two feeds, rss2
and atom, and both return the same 142 items frozen at 2025-05-01. The three 403s are all
Q4-hosted and refuse whatever the headers say.

So there is no free route to these companies' releases with what this repo is allowed to
use. The gap is now visible rather than silent, which is the part that was actually
costing us: Merck and Moderna announced on 2026-08-19 that Phase 3 INTerpath-001 met both
recurrence-free and distant metastasis-free survival, and the only reason the terminal has
it is that Merck's page route carried the joint release.

What would close the rest is a renderer that executes JavaScript. That is a capability
decision, not a configuration one.

## Covered

The other 46 feeds are current, the newest between 15 and 22 days old at the time of the
audit, which is the ordinary rhythm of a large-cap news page.
