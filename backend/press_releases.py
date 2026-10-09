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

This module is the parsing, the classifying, and the one write path both routes into it
share. A feed and a scraped page differ in how a headline is obtained and in nothing that
happens after, so ``record`` is here rather than duplicated in two fetchers that are
forbidden from importing each other.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.parse
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


_NOT_YET = re.compile(r"\bappoints?\b|board of directors|potential (?:fda )?approval"
                     r"|toward (?:potential )?(?:fda )?approval", re.I)


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
            # "Appoints X to its Board ... Toward Potential FDA Approval" names an approval
            # the company hopes for, not one it has: a board change is not news here.
            if kind == "approval" and _NOT_YET.search(text):
                return None, False
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
        title = _AGGREGATOR_LABEL.sub("", title)
        if title:
            out.append({"title": title, "url": link, "published": _as_date(published)})
    return out


# An aggregator's feed puts its own label after the headline: StockTitan writes
# "Pfizer Declares Fourth-Quarter 2026 Dividend | PFE Stock News". The release's
# headline is the part before it, and the label would stop the same release read off
# another route from being recognised as the same.
_AGGREGATOR_LABEL = re.compile(r"\s*\|\s*[A-Z][A-Z.]{0,6} Stock News\s*$")


def parse_sxa(json_text: str, base_url: str) -> list[dict]:
    """(title, link, published) per result of a Sitecore SXA search, the listing a
    Sitecore newsroom draws its news page from.

    Gilead's investor site answers a bot challenge, and gilead.com's own news page
    answers in full: it is drawn by script from ``/sxa/search/results/``, a JSON
    listing whose every result carries the release's url, its date as "September 16,
    2026" and its headline. The ids in the query are the page's own, copied from it,
    and the sort is the page's own date field, newest first.

    This is a listing, not a feed, so a site rebuild can change its shape without
    warning. A result that no longer parses is left out, and an empty listing is
    reported by the fetcher as nothing found, never as a quiet success.
    """
    data = json.loads(json_text)
    out = []
    for result in data.get("Results") or []:
        body = result.get("Html") or ""
        path = (result.get("Url") or "").strip()
        heading = re.search(r"<h\d[^>]*>(.*?)</h\d>", body, re.S)
        when = re.search(r"field-news-date[^>]*>\s*([^<]+?)\s*<", body)
        if not (heading and path):
            continue
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", heading.group(1))))
        out.append({"title": title.strip(), "url": urllib.parse.urljoin(base_url, path),
                    "published": _long_date(when.group(1)) if when else None})
    return out


def _long_date(raw: str) -> str | None:
    """"September 16, 2026" as 2026-09-16, or None."""
    try:
        return dt.datetime.strptime(raw.strip(), "%B %d, %Y").date().isoformat()
    except ValueError:
        return None


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


# --- what a classified release becomes -------------------------------------

# How recent an announcement must be to also count as a change. The first run for a
# company reads its whole archive, which for AstraZeneca is 1,626 items back to 2013 and
# 523 that classify. Writing a change for each would bury the day's news under a decade
# of it. Everything older is still stored as news; it just does not claim to be new.
CHANGE_WINDOW_DAYS = 21

# What a kind is worth in the feed. An approval or a deal moves the stock, a CHMP opinion
# or a filing acceptance is a step on the way, and a dividend is neither.
SIGNIFICANCE = {
    "approval": "high",
    "deal": "high",
    "PDUFA": "high",
    "data readout": "high",
    "regulatory": "medium",
    "panel": "medium",
    "results": "low",
    "dividend": "low",
}

# The kinds that name a dated future event, and so can become a catalyst as well as a
# change. A decision date being set is itself news, so both rows are written.
CATALYST_KINDS = {"PDUFA": "PDUFA", "panel": "AdCom"}


def change_type(kind: str) -> str:
    """A press release's change type, e.g. ``press_data_readout``.

    The kind stays in the type rather than in a separate column, so the changes table
    keeps saying what it holds and one prefix separates announcements from everything
    else.
    """
    return "press_" + kind.lower().replace(" ", "_")


# The routes a company's own announcements arrive by. A release is one release whichever
# of them carried it, and the url, which is news's key, differs between them.
ANNOUNCEMENT_SOURCES = ("press_ir", "press_page")

# How far apart two routes may date the same release. A wire stamps it in GMT and an IR
# site in the company's own time zone, so an evening release lands a day apart.
SAME_RELEASE_DAYS = 3

# The shortest headline that may be matched on its opening alone. Q4's feeds cut a long
# headline and end it with "...", so the stored copy is a prefix of the wire's.
_PREFIX_MIN = 40


def title_key(title: str) -> str:
    """A headline reduced to its letters and digits, so the same release read off two
    routes (curly or straight apostrophes, a trademark sign or not) reads as one."""
    return re.sub(r"[^a-z0-9]", "", html.unescape(title or "").lower())


def _held_under_another_url(conn, row) -> bool:
    """Whether this release is already in news under another url.

    The url is news's key, and it is the route's url, not the release's. When a
    company's feed moves (BMS's investor site began answering a bot challenge in
    September 2026 and its releases are now read off a wire aggregator), every release
    the old route already stored would otherwise be written a second time under its new
    link, and appear twice in every view built on news.
    """
    if not row.get("published"):
        return False
    key = title_key(row["title"])
    if not key:
        return False
    held = conn.execute(
        "SELECT title FROM news WHERE company_id = ? AND url != ?"
        " AND source IN (%s) AND published_at BETWEEN date(?, ?) AND date(?, ?)"
        % ",".join("?" * len(ANNOUNCEMENT_SOURCES)),
        (row["company_id"], row["url"], *ANNOUNCEMENT_SOURCES,
         row["published"], f"-{SAME_RELEASE_DAYS} day",
         row["published"], f"+{SAME_RELEASE_DAYS} day")).fetchall()
    for (title,) in held:
        other = title_key(title)
        if other == key:
            return True
        short, long_ = sorted((other, key), key=len)
        if len(short) >= _PREFIX_MIN and long_.startswith(short):
            return True
    return False


def record(conn, rows, source: str, refresh_run_id=None, today=None) -> tuple:
    """Write releases to news, and the recent classified ones on to changes and
    catalysts. Returns (written, changed, catalysts).

    The caller commits. Only the insert that takes decides anything, so a re-run over the
    same feed reports nothing twice.
    """
    cutoff = ((today or dt.date.today())
              - dt.timedelta(days=CHANGE_WINDOW_DAYS)).isoformat()
    written = changed = catalysts = 0
    for row in rows:
        if _held_under_another_url(conn, row):
            continue
        cursor = conn.execute(
            "INSERT INTO news (company_id, source, title, url, published_at)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT(url) DO NOTHING",
            (row["company_id"], source, row["title"], row["url"], row["published"]))
        if not cursor.rowcount:
            continue
        written += 1
        if not row["kind"]:
            continue
        if row["published"] and row["published"] >= cutoff:
            conn.execute(
                "INSERT INTO changes (entity_type, entity_key, field, old_value,"
                "  new_value, change_type, significance, refresh_run_id)"
                " VALUES ('company', ?, 'press release', NULL, ?, ?, ?, ?)",
                (f"{row['ticker']}|{row['url']}", row["title"],
                 change_type(row["kind"]), SIGNIFICANCE.get(row["kind"], "low"),
                 refresh_run_id))
            changed += 1
        if row["ahead"] and row["stated_date"]:
            conn.execute(
                "INSERT INTO catalysts (company_id, catalyst_type, expected_date,"
                "  date_confidence, title, description, is_curated, source_url, status)"
                " VALUES (?, ?, ?, 'confirmed', ?, ?, 0, ?, 'pending')",
                (row["company_id"], CATALYST_KINDS[row["kind"]], row["stated_date"],
                 row["title"], f"Announced by {row['ticker']} on {row['published']}",
                 row["url"]))
            catalysts += 1
    return written, changed, catalysts
