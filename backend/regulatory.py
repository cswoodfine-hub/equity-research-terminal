"""The FDA regulatory stream: advisory committee meetings and announcement feeds, merged.

These were two tables asking the same question, what the agency is doing, split only by
which source they came from. One is dated forward (a panel vote scheduled), the others
backward (something announced), so merged they read as a single timeline: what is coming,
then what just happened.

Every item carries a ``kind`` the UI colours by, so a safety communication is not read as
a press release, and a ``ticker`` when the item names a covered company. An item matching
no covered company is kept rather than filtered, since the agency layer is context, but
the matched ones sort first within a day so a bound item is never below the fold.
"""

from __future__ import annotations

import datetime as dt

import db

# The announcement feeds, mapped to the kind the UI colours by. A safety communication
# moves a stock differently from a press release, so they do not share a colour.
_NEWS_KIND = {
    "fda_safety": "safety",
    "fda_drugs": "drugs",
    "fda_press": "press",
}
AHEAD = "ahead"
BEHIND = "behind"


def _short_committee(name: str) -> str:
    """The committee without the boilerplate, so the panel is readable at a glance."""
    text = (name or "").replace("Advisory Committee", "").strip()
    return text.rstrip(",").strip() or "advisory committee"


def build(db_path=None, days: int = 120, today=None) -> dict:
    """The merged stream, upcoming panel votes first, then announcements newest first.

    ``days`` bounds how far back the announcement feeds reach. Advisory committee meetings
    are not bounded the same way: a scheduled vote is the forward-looking half of this view
    and is kept whatever its date, with past meetings falling into the behind group.
    """
    today = today or dt.date.today()
    iso = today.isoformat()
    conn = db.get_connection(db_path)
    try:
        meetings = [dict(r) for r in conn.execute(
            """
            SELECT m.meeting_date AS date, m.committee, m.product, m.application_label,
                   m.url, c.ticker
              FROM adcomm_meetings m LEFT JOIN companies c ON c.id = m.company_id
             ORDER BY m.meeting_date
            """)]
        news = [dict(r) for r in conn.execute(
            """
            SELECT n.published_at AS date, n.source, n.title, n.url, c.ticker
              FROM news n LEFT JOIN companies c ON c.id = n.company_id
             WHERE n.source LIKE 'fda_%'
               AND (n.published_at IS NULL OR n.published_at >= date('now', ?))
             ORDER BY n.published_at DESC, n.id DESC LIMIT 80
            """, (f"-{int(days)} days",))]
    finally:
        conn.close()

    items = []
    for m in meetings:
        date = (m["date"] or "")[:10]
        items.append({
            "kind": "panel", "date": date,
            "when": AHEAD if date and date >= iso else BEHIND,
            "title": m["product"] or _short_committee(m["committee"]),
            "detail": _short_committee(m["committee"]),
            "tag": m["application_label"] or "",
            "ticker": m["ticker"], "url": m["url"],
        })
    for n in news:
        date = (n["date"] or "")[:10]
        items.append({
            "kind": _NEWS_KIND.get(n["source"], "press"), "date": date,
            "when": BEHIND,                     # an announcement is always after the fact
            "title": n["title"] or "",
            "detail": "", "tag": "",
            "ticker": n["ticker"], "url": n["url"],
        })

    ahead = [i for i in items if i["when"] == AHEAD]
    behind = [i for i in items if i["when"] == BEHIND]
    # Soonest first ahead, newest first behind; within a date, a company-matched item
    # leads, so a bound item never sits under agency housekeeping.
    ahead.sort(key=lambda i: (i["date"] or "9999", i["ticker"] is None))
    behind.sort(key=lambda i: (i["date"] or "", i["ticker"] is not None), reverse=True)

    return {
        "ahead": ahead,
        "behind": behind,
        "counts": {
            "ahead": len(ahead),
            "behind": len(behind),
            "matched": sum(1 for i in items if i["ticker"]),
            "safety": sum(1 for i in items if i["kind"] == "safety"),
        },
    }
