"""An IR page read as text, for the companies that publish no feed.

Fifty-four of seventy carry RSS. The sixteen left include GSK, Merck, Johnson & Johnson,
Sanofi, Roche and Novo Nordisk, whose releases exist only as a web page. Jina Reader
(``https://r.jina.ai/<url>``) renders one to markdown for free and without a key, which
is the route in.

The four listing pages look nothing like each other:

    GSK   *   [29 July 2026 ## Headline Standfirst](url)
    JNJ   *   [](url)[Category](url) August 4, 2026
          ## [Headline](url)
    MRK   [August 6, 2026](url)
          [Headline](url)
    ROG   *   ### [Headline](url)
          July 24, 2026

Writing a title rule for each would be four rules that break separately. So the listing
is read for one thing it states unambiguously, the release urls, and each release page is
then read for its own ``Title:`` and ``Published Time:``, which Jina emits in the same
shape for every site. The headline is then the company's, exactly, rather than something
reassembled out of a list item.

This module is the parsing. The fetching, and the rate limit that comes with it, sit in
``fetchers.press_page``.
"""

from __future__ import annotations

import datetime as dt
import re
import urllib.parse

# Only the target, never the text. Roche titles a release "[Ad hoc announcement pursuant
# to Art. 53 LR] Roche's strong momentum continues", and a pattern that has to cross the
# link text loses every headline containing a bracket.
_LINK = re.compile(r"\]\((https?://[^)\s]+)\)")

# Jina's header block, which precedes the markdown body of any page it renders.
_TITLE = re.compile(r"^Title:\s*(.+)$", re.M)
_PUBLISHED = re.compile(r"^Published Time:\s*(\S+)", re.M)

# A release url ends in a slug: three or more hyphenated words, or a dated identifier
# like Roche's med-cor-2026-07-24. A section link ends in one word, "corporate" or
# "locations", and is how the nav is told from the news.
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+){2,}$", re.I)

# Language variants of the same release. Roche lists a DE link beside every English one,
# pointing at the same slug under /de/.
_LANG = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.I)


def _qualifies(url: str, listing) -> str | None:
    """The release's slug if this url is one, else None. Shared by both readers."""
    segments = [s for s in listing.path.strip("/").split("/") if s]
    section = segments[-1] if segments else ""
    parts = urllib.parse.urlsplit(url)
    if parts.netloc != listing.netloc:
        return None
    path = [s for s in parts.path.strip("/").split("/") if s]
    if not path or section not in path:
        return None
    if not _SLUG.match(path[-1]):
        return None
    # The same release in another language is the same release.
    if any(_LANG.match(s) and s not in segments for s in path[:-1]):
        return None
    return path[-1]


def release_urls(markdown: str, listing_url: str) -> list[str]:
    """The release urls a listing page links to, in the order it lists them.

    A link qualifies on two counts together, because either alone lets the nav through:
    its path carries the last segment of the listing's path, and it ends in a slug rather
    than a section name. Merck lists /news/<slug> from a page at /media/news/, so
    requiring the listing's path as a prefix would drop every one of them, and accepting
    any shared segment lets /media/company-fact-sheet/ in.
    """
    listing = urllib.parse.urlsplit(listing_url)
    seen, out = set(), []
    for url in _LINK.findall(markdown):
        slug = _qualifies(url, listing)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        parts = urllib.parse.urlsplit(url)
        out.append(urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, "", "")))
    return out


def listing_dates(markdown: str, listing_url: str) -> dict:
    """{release url: YYYY-MM-DD} for the dates the listing itself prints.

    Roche's release pages carry no Published Time, so read from the page alone its news
    has no date, and a release with no date never reaches the change feed. The listing
    prints one under every headline, so it is the fallback.

    Where the date sits relative to the link is the one thing these pages disagree about
    most: inside the link text at GSK, at the end of the list line at Johnson & Johnson,
    on the line above at Merck, on the line below at Roche. So the nearest date within two
    lines wins, ties going to the line before, which is the order they occur in.
    """
    listing = urllib.parse.urlsplit(listing_url)
    lines = markdown.splitlines()
    dated = {i: d for i, line in enumerate(lines)
             for d in [_line_date(line)] if d}
    out = {}
    for i, line in enumerate(lines):
        for url in _LINK.findall(line):
            slug = _qualifies(url, listing)
            if not slug:
                continue
            parts = urllib.parse.urlsplit(url)
            clean = urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, parts.path, "", ""))
            if clean in out:
                continue
            for j in (i, i - 1, i + 1, i - 2, i + 2):
                if j in dated:
                    out[clean] = dated[j]
                    break
    return out


_MONTHS = {m: n for n, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}
_DATES = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})\b"),          # 29 July 2026
    re.compile(r"\b([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\b"),         # July 24, 2026
)


def _line_date(line: str) -> str | None:
    """The first full date a line states, as YYYY-MM-DD."""
    for pattern in _DATES:
        match = pattern.search(line)
        if not match:
            continue
        a, b, c = match.groups()
        try:
            if a.isdigit() and len(a) == 4:
                year, month, day = int(a), int(b), int(c)
            elif a.isdigit():
                day, month, year = int(a), _MONTHS[b.lower()], int(c)
            else:
                month, day, year = _MONTHS[a.lower()], int(b), int(c)
            return dt.date(year, month, day).isoformat()
        except (ValueError, KeyError):
            continue
    return None


def release(markdown: str) -> dict | None:
    """The headline and date of one release, from Jina's rendering of its page.

    Returns None where the page carries no title, which is what a redirect to a consent
    wall or an error page looks like. A release with no date keeps None rather than
    today's, since the day it was published is the fact and the day it was read is not.
    """
    title = _TITLE.search(markdown or "")
    if not title:
        return None
    text = title.group(1).strip()
    # Jina takes the browser tab, which carries the site's name after a pipe. Only a pipe
    # counts: a hyphen is inside the headline more often than it is around it, and
    # stripping on one turns "Merck Announces Fourth-Quarter 2026 Dividend" into "Merck
    # Announces Fourth".
    text = re.sub(r"\s*\|\s*[^|]{1,40}$", "", text).strip() or text
    if not text:
        return None
    published = _PUBLISHED.search(markdown or "")
    date = published.group(1)[:10] if published else None
    if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        date = None
    return {"title": text, "published": date}
