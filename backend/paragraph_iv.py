"""FDA Paragraph IV patent certifications, the challenged state on the LOE cliff.

A Paragraph IV certification is a generic filer telling the FDA that a branded drug's
patent is invalid or will not be infringed. It is the opening move of the litigation
that ends a small molecule's exclusivity, and it is filed years before the patent
expires, so it is exactly the signal the LOE cliff misses: the cliff reads the latest
patent expiry, and a challenge is the reason that date may not hold.

The FDA publishes the list as a PDF whose rows read cleanly once the text is extracted:
a reference drug (RLD) NDA number followed by the date of the first certification
against it, or "Pre-MMA" for a pre-1984 drug with no cert date on record. This module
is the pure half: it turns the extracted text into rows and resolves the current PDF
link off the certifications page. The download and the company match live in the
fetcher.

Matching is on the NDA number against an asset's internal_code, which is exact, so
nothing is guessed. The list is by RLD, so several strengths of one drug repeat its
number; the earliest real date wins.
"""

from __future__ import annotations

import datetime as dt
import re

LIST_PAGE = ("https://www.fda.gov/drugs/abbreviated-new-drug-application-anda/"
             "patent-certifications-and-suitability-petitions")
_FDA = "https://www.fda.gov"

# A reference drug's NDA number (4 to 6 digits) followed by the date of the first
# Paragraph IV certification against it, or Pre-MMA. The number-then-date shape is
# specific to the RLD/NDA and submission-date columns; a number that matches no tracked
# asset is dropped by the fetcher, so the odd stray pair is harmless.
_ROW = re.compile(r"\b(\d{4,6})\s+(\d{1,2}/\d{1,2}/\d{4}|Pre-MMA)\b")

# The certifications page names this heading three times: in a table of contents, in an
# aria label, and on the real section heading. Only the real one closes with a heading
# tag; anchor on that, then take the first media link after it. Stopping at the first
# anchor keeps an unrelated guidance PDF earlier on the page out of the match.
_LIST_LINK = re.compile(
    r"New Paragraph IV Certifications</h[1-6]>"
    r"(?:(?!<a\b).)*?<a\b[^>]*?href=\"([^\"]*/media/\d+/download[^\"]*)\"",
    re.I | re.S)


def parse_list(text: str) -> list[dict]:
    """Challenge rows from the extracted PDF text: one per reference drug, the earliest
    certification date kept. Pure."""
    best: dict[str, str | None] = {}
    for number, when in _ROW.findall(text or ""):
        key = f"NDA{int(number)}"
        date = _iso(when)
        prior = best.get(key, "missing")
        if prior == "missing" or (date and (prior is None or date < prior)):
            best[key] = date
    return [{"application_number": k, "first_submission": v} for k, v in best.items()]


def resolve_list_url(page_html: str) -> str | None:
    """The current Paragraph IV list PDF link, read off the certifications page, so a
    monthly reissue under a new media id is followed rather than hard-coded."""
    m = _LIST_LINK.search(page_html or "")
    if not m:
        return None
    href = m.group(1)
    return href if href.startswith("http") else _FDA + href


def _iso(mdy: str) -> str | None:
    """'4/4/2012' to '2012-04-04'. 'Pre-MMA' and anything unparseable become None: a
    pre-1984 reference has no certification date, and none is invented."""
    try:
        return dt.datetime.strptime(mdy.strip(), "%m/%d/%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None
