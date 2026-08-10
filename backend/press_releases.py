"""What a company says about itself, read off its own investor-relations feed.

The change feed knew what a company filed and what the FDA published, and almost nothing
of what the company announced. AstraZeneca's news came to sixty-six rows, every one of
them an 8-K whose title was the words "8-K" twice over, while its own feed carried
sixteen hundred items reading "US FDA decision date extended for SERENA-6 filing of
camizestrant", "Ultomiris granted Priority Review", "Truqap recommended by FDA Advisory
Committee". A PDUFA date moving, a priority review, an adcomm outcome and a CHMP opinion,
none of which reached the terminal.

That matters most for catalysts. There is no free PDUFA calendar, which is why the
catalyst table is curated by hand; a company announcing its own decision date is the one
free route to the same fact, and it is the company's own words rather than an inference.

This module is the parsing and the classifying, kept pure so the fetcher around it is
only plumbing and every rule here has a test with a saved payload.
"""

from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET

# What kind of announcement a headline is. Ordered, because a headline can match more
# than one and the first is the one that matters: "FDA approves X following Priority
# Review" is an approval, not a review. Each maps to (kind, is a dated future event).
#
# The vocabulary is the regulatory language these companies actually use in headlines,
# not a general classifier. A press release says "recommended for approval by CHMP" and
# never "the committee was positive", so matching the phrase is enough and guessing is
# not needed.
KINDS = (
    (r"\bfda (?:approves|approval)|\bapproved by the fda\b|receives? (?:us )?fda approval"
     r"|granted (?:full |accelerated )?approval\b", "approval", False),
    # "recommended for approval in the EU by CHMP" is the committee's opinion and not the
    # Commission's decision, which follows about two months later. Without the lookbehind
    # it read as the approval and dated every EU approval early, so the phrase is refused
    # here and caught by the regulatory rule below.
    (r"\bapproved in the (?:us|eu|uk|japan|china)\b"
     r"|(?<!recommended for )\bapproval in the\b", "approval", False),
    (r"\bcomplete response letter\b|\bcrl\b", "regulatory", False),
    (r"\bpdufa\b|decision date|action date|target action", "PDUFA", True),
    (r"advisory committee|\badcom(?:m|mittee)\b|odac\b", "panel", True),
    (r"\bchmp\b|committee for medicinal products|positive opinion"
     r"|recommended for approval", "regulatory", False),
    (r"priority review|breakthrough therapy|fast track|orphan drug designation"
     r"|\brmat\b|accepted for (?:filing|review)|\bfiling accepted\b"
     r"|\bnda\b|\bbla\b|\bmaa\b|\bsnda\b|\bsbla\b", "regulatory", False),
    (r"phase (?:1|2|3|i{1,3})\b.*\b(?:results|data|readout|met|missed|topline)"
     r"|topline (?:results|data)|met (?:its |the )?primary endpoint"
     r"|did not meet|failed to meet", "data readout", False),
    (r"\bacquire|acquisition of|to buy\b|merger with|collaboration with"
     r"|licen[sc]ing agreement|partnership with", "deal", False),
    (r"\bdividend\b", "dividend", False),
    (r"\b(?:q[1-4]|first|second|third|fourth)[- ]quarter\b|full[- ]year results"
     r"|\bh[12] (?:and|results)\b|financial results|earnings", "results", False),
)

# A notice of when results will be published, which announces nothing. "Exelixis to
# Release Second Quarter 2026 Financial Results on Wednesday, August 5" and "Lilly
# confirms date and conference call for second-quarter 2026 financial results" both match
# the results vocabulary and both are diary entries. The results themselves say "reports"
# or "announces", never "to report".
_SCHEDULING = re.compile(
    r"\bto (?:release|report|announce|host|webcast)\b|\bwebcast of\b"
    r"|confirms date|\bschedules?\b|\bwill (?:release|report|host)\b", re.I)

# Phrasing that says the event has already happened, which demotes a kind whose default
# is forward-dated. Nearly every advisory committee headline is the outcome rather than
# the scheduling: of AstraZeneca's, "Truqap recommended by FDA Advisory Committee",
# "FDA Advisory Committee reviewed Imfinzi" and "Update on FDA Advisory Committee vote on
# camizestrant" are all votes already taken, and reading them as upcoming would put a
# past event on the calendar.
_PAST = re.compile(
    r"\brecommended\b|\breviewed\b|\bvoted?\b|\bvotes\b|\boutcome\b|\bstatus on\b"
    r"|\bupdate on\b|\bconcluded\b|\bbacked\b", re.I)

# A headline that is the feed's own furniture rather than an announcement. The page title
# rides in the feed as an item on some platforms, and "Press releases" is not news.
HOUSEKEEPING = re.compile(
    r"^(?:press releases?|news releases?|media releases?|latest news|rss|"
    r"investor relations|news|media centre)$", re.I)

# A date a headline states about itself, for the events that carry one: "PDUFA date of
# 12 March 2027", "decision expected in the first quarter of 2027". Only the explicit
# forms are read. A quarter is not a date and is not turned into one.
_DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|"
               r"september|october|november|december)\s+(\d{4})\b", re.I),
    re.compile(r"\b(january|february|march|april|may|june|july|august|september|"
               r"october|november|december)\s+(\d{1,2}),?\s+(\d{4})\b", re.I),
)
_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}


def classify(title: str) -> tuple[str | None, bool]:
    """(kind, is_forward_dated) for a headline, or (None, False) where it is not news.

    Forward-dated means the headline announces something that has not happened yet, which
    is what makes it a catalyst rather than a change.
    """
    text = (title or "").strip()
    if not text or HOUSEKEEPING.match(text):
        return None, False
    for pattern, kind, ahead in KINDS:
        if re.search(pattern, text, re.I):
            if kind == "results" and _SCHEDULING.search(text):
                return None, False
            return kind, ahead and not _PAST.search(text)
    return None, False


def stated_date(text: str, today=None):
    """A date the text states in full, or None.

    Only an unambiguous day-month-year is read. "In the first quarter of 2027" names a
    quarter and this returns nothing rather than inventing the middle of it, and a date
    already in the past is not a catalyst.
    """
    today = today or dt.date.today()
    for pattern in _DATE_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        groups = match.groups()
        try:
            if groups[0].isdigit():
                day, month, year = int(groups[0]), _MONTHS[groups[1].lower()], int(groups[2])
            else:
                month, day, year = _MONTHS[groups[0].lower()], int(groups[1]), int(groups[2])
            found = dt.date(year, month, day)
        except (ValueError, KeyError):
            continue
        if found >= today:
            return found.isoformat()
    return None


def parse_feed(xml_text: str) -> list[dict]:
    """(title, link, published) per item, for RSS and Atom alike.

    Pure, so the parser is testable against a saved payload. A feed that will not parse
    raises, and the fetcher turns that into one company's reported error rather than a
    failed run.
    """
    root = ET.fromstring(xml_text)
    out = []
    # RSS puts items at .//item with plain tags; Atom uses .//{ns}entry with a link href.
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = published = ""
        for child in item:
            name = child.tag.rsplit("}", 1)[-1]
            if name == "title":
                title = (child.text or "").strip()
            elif name == "link":
                link = (child.text or "").strip() or child.attrib.get("href", "")
            elif name in ("pubDate", "published", "updated", "date"):
                published = published or (child.text or "").strip()
        if title:
            out.append({"title": title, "url": link, "published": _as_date(published)})
    return out


_RSS_DATE = "%a, %d %b %Y %H:%M:%S"


def _as_date(raw: str) -> str | None:
    """The item's date as YYYY-MM-DD, or None. Feeds spell it several ways."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):        # ISO, with or without a time
        return raw[:10]
    try:                                             # RFC 822, the RSS default
        return dt.datetime.strptime(raw[:25].strip(), _RSS_DATE).date().isoformat()
    except ValueError:
        return None
