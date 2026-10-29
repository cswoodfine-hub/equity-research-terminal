"""FDA Paragraph IV patent certifications, the challenged state on the LOE cliff.

A Paragraph IV certification is a generic filer telling the FDA that a branded drug's
patent is invalid or will not be infringed. It is the opening move of the litigation
that ends a small molecule's exclusivity, and it is filed years before the patent
expires, so it is exactly the signal the LOE cliff misses: the cliff reads the latest
patent expiry, and a challenge is the reason that date may not hold.

The FDA published the list as a PDF until mid 2026 and as a spreadsheet from the
2026-09-28 issue, under the same link on the certifications page. The PDF reads as text:
a reference drug (RLD) NDA number followed by the date of the first certification
against it, or "Pre-MMA" for a pre-1984 drug with no cert date on record. The
spreadsheet carries every column (``parse_workbook``), including the date the first
filer began commercial marketing, which is a generic launch that happened. This module
is the pure half: it turns either payload into rows and resolves the current link off
the certifications page. The download and the company match live in the fetcher.

Matching is on the NDA number against an asset's internal_code, which is exact, so
nothing is guessed. The list is by RLD, so several strengths of one drug repeat its
number; the earliest real date wins.
"""

from __future__ import annotations

import datetime as dt
import io
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


# The spreadsheet's columns by header, so a reordered issue still reads. The headers are
# matched with their whitespace collapsed and case folded; FDA spells one of them
# "APPLICANTAPPROVAL", which is why the keys are prefixes rather than whole headers.
_COLUMNS = (
    ("drug name", "drug_name"),
    ("dosage form", "dosage_form"),
    ("strength", "strength"),
    ("rld/nda", "rld"),
    ("date of submission", "submission"),
    ("number of andas", "anda_count"),
    ("180-day status", "status_180"),
    ("180-day decision posting", "status_180_posted"),
    ("date of first applicant", "first_approval"),
    ("date of first commercial", "first_marketing"),
    ("expiration date of last", "last_patent_expiry"),
)
_TITLE_DATE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")
# The application number is the RLD cell's last line on most rows. Some rows put it in
# the name instead, "Oxycontin (NDA 022272)", "NDA 21-490", "Omeprazole 22032 (OTC)", and
# some give none at all ("Simcor"); those keep a null number rather than a name match.
_RLD_NUMBER = re.compile(r"(\d{4,6})\s*$")
_RLD_NDA = re.compile(r"NDA\s*(\d{2,3}-?\d{3})\b", re.I)
_RLD_BARE = re.compile(r"\b(\d{5,6})\b")


def is_workbook(payload: bytes) -> bool:
    """A spreadsheet (a ZIP container) rather than a PDF."""
    return payload[:4] == b"PK\x03\x04"


def parse_workbook(payload: bytes) -> tuple[str | None, list[dict]]:
    """(issue date, rows) from the spreadsheet issue of the list. Pure.

    One row per line of the sheet, every column kept. Dates come as spreadsheet dates on
    most rows and as "m/d/yyyy" text on some; both are read, and any other text in a date
    column (a note, a strength that slipped a column) is left null rather than guessed.
    A row whose RLD cell names no application number keeps a null number, so it stays in
    the count without matching anything.
    """
    import openpyxl                               # only this source reads a workbook
    sheet = openpyxl.load_workbook(io.BytesIO(payload), read_only=True,
                                   data_only=True).worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    list_date = None
    header_at = None
    for i, row in enumerate(rows[:10]):
        first = _clean(row[0]) if row else None
        if first and list_date is None:
            m = _TITLE_DATE.search(first)
            if m:
                month, day, year = (int(g) for g in m.groups())
                list_date = dt.date(year, month, day).isoformat()
        if first and first.lower() == "drug name":
            header_at = i
            break
    if header_at is None:
        raise ValueError("Paragraph IV workbook: no DRUG NAME header row")
    index = {}
    for col, head in enumerate(rows[header_at]):
        head = " ".join((_clean(head) or "").lower().split())
        for prefix, key in _COLUMNS:
            if head.startswith(prefix) and key not in index:
                index[key] = col
    missing = [key for _, key in _COLUMNS if key not in index]
    if missing:
        raise ValueError(f"Paragraph IV workbook: columns not found: {missing}")

    out = []
    for row in rows[header_at + 1:]:
        cell = {key: (row[col] if col < len(row) else None) for key, col in index.items()}
        if not any(v not in (None, "") for v in cell.values()):
            continue
        rld = _clean(cell["rld"]) or ""
        lines = [ln.strip() for ln in rld.splitlines() if ln.strip()]
        number = _RLD_NUMBER.search(lines[-1]) if lines else None
        name_lines = lines[:-1] if number and lines[-1].strip().isdigit() else lines
        number = number or _RLD_NDA.search(rld) or _RLD_BARE.search(rld)
        submission = cell["submission"]
        pre_mma = isinstance(submission, str) and "pre-mma" in submission.lower()
        out.append({
            "drug_name": _clean(cell["drug_name"]),
            "dosage_form": _clean(cell["dosage_form"]),
            "strength": _clean(cell["strength"]),
            "rld_name": " ".join(name_lines) or None,
            "application_number": (f"NDA{int(number.group(1).replace('-', ''))}"
                                   if number else None),
            "submission_date": None if pre_mma else _date(submission),
            "pre_mma": int(pre_mma),
            "anda_count": cell["anda_count"] if isinstance(cell["anda_count"], int)
                          else None,
            "status_180": " ".join((_clean(cell["status_180"]) or "").split()) or None,
            "status_180_posted": _date(cell["status_180_posted"]),
            "first_approval": _date(cell["first_approval"]),
            "first_marketing": _date(cell["first_marketing"]),
            "last_patent_expiry": _date(cell["last_patent_expiry"]),
        })
    return list_date, out


def summarise(rows: list[dict]) -> list[dict]:
    """One row per reference drug, the earliest certification kept: the shape
    ``parse_list`` gives, so either issue format feeds the same challenged state."""
    best: dict[str, str | None] = {}
    for row in rows:
        key = row.get("application_number")
        if not key:
            continue
        date = row.get("submission_date")
        prior = best.get(key, "missing")
        if prior == "missing" or (date and (prior is None or date < prior)):
            best[key] = date
    return [{"application_number": k, "first_submission": v} for k, v in best.items()]


def _clean(value) -> str | None:
    """Cell text with the sheet's stray carriage-return escapes removed."""
    if value is None:
        return None
    text = str(value).replace("_x000D_", "").replace("\r", "").strip()
    return text or None


def _date(value) -> str | None:
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return _iso(value)
    return None
