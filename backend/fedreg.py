"""Federal Register notices, the free and structured route to FDA advisory committee
meetings.

An advisory committee meeting is a binary regulatory event: the panel votes, and the
stock moves on the vote days before the FDA decision that follows. No free calendar of
these exists, but the FDA has to publish each meeting in the Federal Register, whose
API returns the notice as JSON. The meeting notice title follows a stable template,

    "<Committee>; Notice of Meeting; ...-Biologics License Application (BLA) 125827,
     From Replimune, Inc. for Vusolimogene Oderparepvec"

so the committee, the application number, the sponsor and the product all read straight
off the title, and the meeting date reads off the dates field. This module is the pure
half: it turns the payload into meeting rows. The network fetch and the match to a
tracked company live in the fetcher.

Renewals, terminations and authority notices come back from the same search; they carry
no meeting date, so they are dropped here rather than mistaken for events.
"""

from __future__ import annotations

import datetime as dt
import re

# The whole universe of FDA advisory committee notices, newest first. term filters to
# meeting-related notices; the meeting-date parse below drops the rest.
API_URL = (
    "https://www.federalregister.gov/api/v1/documents.json"
    "?conditions[agencies][]=food-and-drug-administration"
    "&conditions[term]=advisory+committee+meeting"
    "&conditions[type][]=NOTICE"
    "&per_page=100&order=newest"
    "&fields[]=title&fields[]=dates&fields[]=html_url"
    "&fields[]=publication_date&fields[]=document_number"
)

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
           "November|December")

# "The meeting will be held ... on July 30, 2026". The date is the event; a notice
# without one is a renewal or a termination, not a meeting.
_MEETING_DATE = re.compile(
    rf"meeting will be held[^.]*?\bon\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)

# "(BLA) 125827", "BLA 125827", "NDA 021780", or the concatenated internal_code form
# "NDA21780". The lookbehind rejects the NDA inside ANDA (a generic, not an AdComm
# application); leading zeros are dropped so either spelling of the number compares
# equal to an asset's internal_code.
_APP_NO = re.compile(r"(?<![A-Za-z])(BLA|NDA)\)?\s*0*(\d{3,6})", re.I)

# "From Replimune, Inc. for Vusolimogene Oderparepvec": sponsor and product only when
# the whole template is present, so a bare "Request for Comments" yields neither rather
# than reading "Comments" as a product.
_FROM_FOR = re.compile(r"\bfrom\s+(.+?)\s+for\s+([^;,]+?)\s*$", re.I)


def parse_documents(payload: dict) -> list[dict]:
    """Meeting rows from a Federal Register documents.json payload. Pure."""
    return [row for r in (payload.get("results") or []) if (row := _one(r))]


def _one(r: dict) -> dict | None:
    meeting_date = _meeting_date(r.get("dates") or "")
    if meeting_date is None:
        return None                       # not a scheduled meeting
    title = (r.get("title") or "").strip()
    committee = title.split(";")[0].strip()
    if "advisory committee" not in committee.lower():
        return None                       # a user-fee or board meeting, not a panel
    app = _APP_NO.search(title)
    application_number = normalise_appno(app.group(0)) if app else None
    application_label = (f"{app.group(1).upper()} {int(app.group(2))}"
                         if app else None)
    from_for = _FROM_FOR.search(title)
    return {
        "title": title,
        "committee": committee,
        "meeting_date": meeting_date,
        "application_number": application_number,
        "application_label": application_label,
        "sponsor": from_for.group(1).strip() if from_for else None,
        "product": from_for.group(2).strip() if from_for else None,
        "url": r.get("html_url"),
        "document_number": r.get("document_number"),
        "published": r.get("publication_date"),
    }


def _meeting_date(dates_text: str) -> str | None:
    m = _MEETING_DATE.search(dates_text or "")
    if not m:
        return None
    try:
        return dt.datetime.strptime(
            f"{m.group(1)} {int(m.group(2))} {m.group(3)}", "%B %d %Y").date().isoformat()
    except ValueError:
        return None


def normalise_appno(text: str) -> str | None:
    """A BLA/NDA reference to the internal_code shape (letters plus the number with no
    leading zeros), so 'BLA) 125827' and 'NDA 021780' compare equal to 'BLA125827' and
    'NDA21780'. Returns None when the text holds no application number."""
    m = _APP_NO.search(text or "")
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else None
