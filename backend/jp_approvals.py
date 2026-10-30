"""Reading the PMDA's English list of approved new drugs.

The list is one PDF from April 2004 on, laid out as a table with one row per approval:
review category, approval date, number, brand names with the applicant, approval or
partial change, active ingredient and a note. The note says when the row is a new
active ingredient ("A drug with a new active ingredient", "Drugs containing a new
active ingredient") and carries "[Orphan drug]" where it is one. The PDF underlines a
new ingredient, which text extraction loses, so the note is what is read.

Two date styles: "May 19, 2025" from FY2008 on, "11-Oct-05" before it. A row runs from
its date line to the next date line or the next table heading, and is kept as its text
with the whitespace collapsed, since the columns interleave once extracted: the row is
searched for a product's name, never split into fields.
"""

from __future__ import annotations

import datetime as dt
import io
import re

_MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
_LONG_DATE = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),\s*(\d{4})")
_SHORT_DATE = re.compile(
    r"\b(\d{1,2})-(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(\d{2})\b")
# A date sits in the first two columns; one further right is inside a note.
_DATE_COLUMNS = 100
_HEADING = re.compile(r"\s*(New Drugs Approved|Review Reports|Review Category|Category\s"
                      r"|List of Approved|Table|FY\d{4} List)")
# The PDF link on the list's page, with the span it covers beside it.
_RELEASE = re.compile(r'href="(/files/\d+\.pdf)"[^>]*>\s*([^<\[]*?\d{4}[^<\[]*?)\s*[\[<]')


def release_link(page: str) -> tuple[str, str] | None:
    """(absolute PDF url, "April 2004 to February 2026") from the list's page, or None."""
    found = _RELEASE.search(page or "")
    if not found:
        return None
    return "https://www.pmda.go.jp" + found.group(1), re.sub(r"\s+", " ", found.group(2))


def text_of(pdf: bytes) -> str:
    """The PDF's text with its columns kept on their lines."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join(page.extract_text(extraction_mode="layout") for page in reader.pages)


def _date(line: str) -> str | None:
    head = line[:_DATE_COLUMNS]
    found = _LONG_DATE.search(head)
    if found:
        month, day, year = found.group(1), found.group(2), found.group(3)
        return dt.date(int(year), _MONTHS[month.lower()], int(day)).isoformat()
    found = _SHORT_DATE.search(head)
    if found:
        day, month, year = found.group(1), found.group(2), found.group(3)
        return dt.date(2000 + int(year), _MONTHS[month.lower()], int(day)).isoformat()
    return None


def parse(text: str) -> list[dict]:
    """[{approved_on, entry, is_new_ingredient, is_orphan}] in the order listed."""
    rows, current = [], None
    for line in (text or "").splitlines():
        stamp = _date(line)
        if stamp:
            if current:
                rows.append(current)
            current = {"approved_on": stamp, "lines": [line]}
        elif current is not None:
            if _HEADING.match(line):
                rows.append(current)
                current = None
            else:
                current["lines"].append(line)
    if current:
        rows.append(current)
    out = []
    for row in rows:
        entry = re.sub(r"\s+", " ", " ".join(row["lines"])).strip()
        lowered = entry.lower()
        out.append({"approved_on": row["approved_on"], "entry": entry,
                    "is_new_ingredient": int("new active ingredient" in lowered),
                    "is_orphan": int("orphan drug" in lowered)})
    return out
