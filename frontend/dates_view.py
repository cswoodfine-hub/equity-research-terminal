"""Dates that moved and dates that end, for one company: pure, no Streamlit.

A slipped completion date is a fact about a study and an expiry a fact about a product,
so they are read on the company's Portfolio tab rather than in the Universe tab's
week. Both read the company's change feed (``/changes?ticker=``)."""

from __future__ import annotations

import datetime as dt
import re

SLIP_DAYS = 30
LOE_SOON_DAYS = 60
_SLIP_RE = re.compile(r"(NCT\d{8}).*?slips (\d{4}-\d{2}(?:-\d{2})?) -> "
                      r"(\d{4}-\d{2}(?:-\d{2})?)")


def first_day(text: str):
    """A registry date as a day: a month-only date is its first day."""
    try:
        return dt.date.fromisoformat(text if len(text) == 10 else text + "-01")
    except (TypeError, ValueError):
        return None


def slip_rows(feed: list, today: dt.date, days: int = SLIP_DAYS) -> list:
    """The company's study completion dates that moved in the last ``days``, one row a
    study, taken first date to last when it moved twice. A move of a date already past
    when it was seen is a correction, not a slip, and is left out. The largest move first."""
    since = today - dt.timedelta(days=days)
    studies: dict = {}
    for r in feed or []:
        if r.get("change_type") != "date_slip":
            continue
        m = _SLIP_RE.search(r.get("headline") or "")
        seen = first_day(str(r.get("detected_at") or r.get("date") or "")[:10])
        if not m or not seen or seen < since:
            continue
        nct, was, now = m.groups()
        a, b = first_day(was), first_day(now)
        if not a or not b or a < seen:
            continue
        o = studies.get(nct)
        if o:
            was = min((o["was"], was), key=first_day)
            now = max((o["now"], now), key=first_day)
            seen = max(o["seen"], seen)
        studies[nct] = {"nct": nct, "was": was, "now": now, "seen": seen,
                        "days": (first_day(now) - first_day(was)).days,
                        "moves": (o["moves"] + 1) if o else 1}
    return sorted(studies.values(), key=lambda s: -s["days"])


def loe_soon(feed: list, today: dt.date, days: int = LOE_SOON_DAYS) -> list:
    """The company's listed patents and exclusivities ending in the next ``days``, from
    the Orange and Purple Books: {date, brand, what}, soonest first."""
    end = today + dt.timedelta(days=days)
    out = []
    for r in feed or []:
        if r.get("change_type") != "loe":
            continue
        d = first_day(str(r.get("date") or "")[:10])
        if not d or not today <= d <= end:
            continue
        text = re.sub(r"^[A-Z0-9.]+ LOE: ", "", r.get("headline") or "")
        m = re.match(r"(.+?) \(((?:NDA|BLA|ANDA)\d+)\) (.+?)(?: expires \S+)?$", text)
        brand, what = (m.group(1), f"{m.group(2)} {m.group(3)}") if m else (text, "")
        out.append({"date": d.isoformat(), "brand": brand, "what": what})
    return sorted(out, key=lambda e: (e["date"], e["brand"]))
