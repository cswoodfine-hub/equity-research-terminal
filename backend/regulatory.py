"""The FDA regulatory stream: advisory committee meetings and announcement feeds, merged.

These were two tables asking the same question, what the agency is doing, split only by
which source they came from. One is dated forward (a panel vote scheduled), the others
backward (something announced), so merged they read as a single timeline: what is coming,
then what just happened.

Every item carries a ``kind`` the UI colours by, so a safety communication is not read as
a press release, and a ``ticker`` when the item names a covered company.

Most of what the agency publishes is not an event. The same feeds that carry a panel vote
and a safety communication also carry the FDA's own website upkeep: "Withdrawn and Expired
Guidances", "Over-The-Counter Monograph Drug User Fee Program", "Patient Listening Session
Summaries", "Upcoming Product-Specific Guidances for Generic Drug Product Development".
Eighty-one items over four months, of which nine touched a covered company and most of the
rest were standing resource pages republished. A reader scanning that list is doing the
filtering the tool should have done.

So an item has to earn its place. A scheduled panel vote is always an event, since it is
the one firm regulatory date free data gives. A safety communication is always an event. An
announcement naming a covered company is an event about that company. Everything else is
agency housekeeping and is counted rather than listed, so the page says what it dropped.
"""

from __future__ import annotations

import datetime as dt
import re

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

# A standing page rather than an announcement. These republish on their own schedule and
# say nothing new: a title that is the name of a programme, a resource or a list is the
# agency's furniture. Applied whether or not the item matched a company, because a match
# on a page like "New Approach Methodologies" is a false match, not a signal.
_HOUSEKEEPING = re.compile(
    r"\bguidances?\b|user fee|listening session|labeling resources|untitled letters|"
    r"^drug alerts and statements$|^drug trials snapshots$|^warning letters$|"
    r"new approach methodolog|^recalls|resources for|^compliance|^enforcement report|"
    r"^import alert|^cder |^cber |\bwebinar\b|\bworkshop\b|public meeting|"
    r"^advisory committee calendar|federal register notice", re.I)


# A device, not a drug. The MedWatch feed is mostly hardware: catheters, infusion pumps,
# ventilators, stent grafts, convenience kits. This universe is large-cap pharma, and a
# ventilator recall at a company it does not cover is somebody else's subject. Where the
# recall does belong to a covered company it is kept by the ticker match: J&J owns Abiomed,
# and its heart pump recall is a J&J event.
_DEVICE = re.compile(
    r"\b(?:catheter|stent|graft|pump|ventilator|infusion|introducer|kits?|"
    r"breathing (?:device|circuit)|administration set|circuit set|monitor|syringe|"
    r"implant|valve delivery|guidewire|dialy[sz]er|endoscope|defibrillator|tubing|"
    r"cannula|insulin pod|glucose meter)\b", re.I)


def is_event(item: dict) -> bool:
    """Whether this is something that happened, or something the FDA reposted.

    A scheduled panel vote is an event on its own, being the one firm regulatory date free
    data gives. A safety communication is an event unless it is a device recall at a
    company outside the universe. Everything else has to name a company we cover, and no
    housekeeping page counts however it was matched.
    """
    title = (item.get("title") or "").strip()
    if _HOUSEKEEPING.search(title):
        return False
    if item.get("ticker"):
        return True
    if item.get("kind") == "panel":
        return True
    if item.get("kind") == "safety":
        return not _DEVICE.search(title)
    return False


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

    events = [i for i in items if is_event(i)]
    ahead = [i for i in events if i["when"] == AHEAD]
    behind = [i for i in events if i["when"] == BEHIND]
    # Soonest first ahead, newest first behind; within a date, a company-matched item
    # leads, so a bound item never sits under an unmatched safety notice.
    ahead.sort(key=lambda i: (i["date"] or "9999", i["ticker"] is None))
    behind.sort(key=lambda i: (i["date"] or "", i["ticker"] is not None), reverse=True)

    return {
        "ahead": ahead,
        "behind": behind,
        "counts": {
            "ahead": len(ahead),
            "behind": len(behind),
            "matched": sum(1 for i in events if i["ticker"]),
            "safety": sum(1 for i in events if i["kind"] == "safety"),
            # What was read and set aside. Reported rather than hidden, so a reader can
            # tell an empty stream from a filtered one.
            "housekeeping": len(items) - len(events),
        },
    }
