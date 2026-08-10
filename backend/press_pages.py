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


def release_urls(markdown: str, listing_url: str) -> list[str]:
    """The release urls a listing page links to, in the order it lists them.

    A link qualifies on two counts together, because either alone lets the nav through:
    its path carries the last segment of the listing's path, and it ends in a slug rather
    than a section name. Merck lists /news/<slug> from a page at /media/news/, so
    requiring the listing's path as a prefix would drop every one of them, and accepting
    any shared segment lets /media/company-fact-sheet/ in.
    """
    listing = urllib.parse.urlsplit(listing_url)
    segments = [s for s in listing.path.strip("/").split("/") if s]
    section = segments[-1] if segments else ""
    seen, out = set(), []
    for url in _LINK.findall(markdown):
        parts = urllib.parse.urlsplit(url)
        if parts.netloc != listing.netloc:
            continue
        path = [s for s in parts.path.strip("/").split("/") if s]
        if not path or section not in path:
            continue
        slug = path[-1]
        if not _SLUG.match(slug):
            continue
        # The same release in another language is the same release.
        if any(_LANG.match(s) and s not in segments for s in path[:-1]):
            continue
        if slug in seen:
            continue
        seen.add(slug)
        out.append(urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, "", "")))
    return out


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
