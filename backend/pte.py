"""Patent term extensions under 35 USC 156: which patent holds the molecule.

The Orange Book flags several patents per product "drug substance" and never says which
one claims the molecule, so the LOE fell back to the latest of them, which is often a
salt, a crystal form or a later formulation: Ozempic read 2034 where semaglutide's own
patent runs to 2031, Evrysdi 2041 where risdiplam's runs to 2033.

The extension settles it from the statute rather than by judgement. Section 156 restores
term lost to FDA review on **one** patent per product, the first approval of the active
ingredient, and the holder picks the patent worth extending, which is the one claiming
the molecule almost every time. The USPTO publishes every certificate it has issued, so a
product's extended patent is a fact of record. All five compound patents an analyst had
established by hand in ``data/compound_patent.csv`` (Farxiga, Ozempic, Mounjaro, Ibrance
and their second presentations) are the extended patent on that list.

Two files, both keyless spreadsheets on www.uspto.gov:

- ``pte_certs.xls``, every certificate issued: patent, trade name, the patent's original
  expiry and the extension granted ("5 years", "1509 days").
- ``pte_past5years.xlsx``, applications filed in the last five years, granted or not:
  patent, filing date, trade name. A pending application names a patent the holder asks
  to extend; a holder may file on several and must elect one, so an application alone
  does not identify the patent and is kept for display, never for the date.

The date itself still comes from the Orange Book, which lists the extended expiry and any
paediatric extension; the USPTO's own note says its expiry column ignores later terminal
disclaimers and lapsed fees. This module only says which patent. Pure: parsing only.
"""

from __future__ import annotations

import calendar
import datetime as dt
import io
import re

BASE = "https://www.uspto.gov/sites/default/files/documents/"
CERTIFICATES_URL = BASE + "pte_certs.xls"
APPLICATIONS_URL = BASE + "pte_past5years.xlsx"
PAGE_URL = ("https://www.uspto.gov/patents/laws/patent-term-extension/"
            "patent-terms-extended-under-35-usc-156")

_EXTENSION = re.compile(r"^\s*([\d,]+)\s*(day|year)s?\s*$", re.I)


def patent_key(value) -> str | None:
    """A patent number in the Orange Book's shape: digits, or RE and digits, with no
    separators. The certificate file spells them as floats (6515117.0), with dots
    (5.093.200), commas and stray spaces."""
    if value is None or value == "":
        return None
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else None
    text = str(value).strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"[\s.,]", "", text)
    m = re.fullmatch(r"(RE)?0*(\d{5,8})", text)
    return f"{m.group(1) or ''}{m.group(2)}" if m else None


def _add_years(day: dt.date, years: int) -> dt.date:
    year = day.year + years
    return day.replace(year=year, day=min(day.day, calendar.monthrange(year, day.month)[1]))


def extended_expiry(original: str | None, extension: str | None) -> str | None:
    """The original expiry plus the extension granted, or None where either is not a
    clean value. A cross-check on the Orange Book's date, not a replacement for it."""
    if not original or not extension:
        return None
    m = _EXTENSION.match(extension)
    if not m:
        return None
    amount, unit = int(m.group(1).replace(",", "")), m.group(2).lower()
    day = dt.date.fromisoformat(original)
    if unit == "year":
        return _add_years(day, amount).isoformat()
    return (day + dt.timedelta(days=amount)).isoformat()


def parse_certificates(payload: bytes) -> list[dict]:
    """Every issued certificate: {patent, trade_name, original_expiry, extension,
    extended_expiry}. The original expiry is a spreadsheet date; the one row that
    spells it as text ("12/13/22025") is left null rather than repaired."""
    import xlrd                                    # the certificate file is .xls (BIFF)
    book = xlrd.open_workbook(file_contents=payload)
    sheet = book.sheet_by_index(0)
    header = [str(v).strip().lower() for v in sheet.row_values(0)]
    col = _columns(header, {"patent": "patent no", "trade_name": "tradename",
                            "original": "original expiration",
                            "extension": "period of extension"})
    out = []
    for i in range(1, sheet.nrows):
        row = sheet.row_values(i)
        patent = patent_key(row[col["patent"]])
        if not patent:
            continue                               # the footnote row, or a blank
        raw = row[col["original"]]
        original = None
        if isinstance(raw, float) and raw > 0:
            original = xlrd.xldate.xldate_as_datetime(raw, book.datemode).date().isoformat()
        extension = " ".join(str(row[col["extension"]]).split()) or None
        out.append({"patent": patent,
                    "trade_name": " ".join(str(row[col["trade_name"]]).split()) or None,
                    "original_expiry": original, "extension": extension,
                    "extended_expiry": extended_expiry(original, extension)})
    return out


def parse_applications(payload: bytes) -> list[dict]:
    """Applications filed in the last five years: {patent, trade_name, filed,
    application_number}."""
    import openpyxl
    sheet = openpyxl.load_workbook(io.BytesIO(payload), read_only=True,
                                   data_only=True).worksheets[0]
    rows = list(sheet.iter_rows(values_only=True))
    header = [str(v or "").strip().lower() for v in rows[0]]
    col = _columns(header, {"application": "u.s. application", "patent": "u.s. patent",
                            "filed": "pte application filing", "trade_name": "trade name"})
    out = []
    for row in rows[1:]:
        patent = patent_key(row[col["patent"]])
        if not patent:
            continue
        filed = row[col["filed"]]
        if isinstance(filed, dt.datetime):
            filed = filed.date().isoformat()
        elif not isinstance(filed, str):
            filed = None
        out.append({"patent": patent,
                    "trade_name": " ".join(str(row[col["trade_name"]] or "").split())
                                  or None,
                    "filed": filed,
                    "application_number": str(row[col["application"]] or "").strip()
                                          or None})
    return out


def _columns(header: list[str], wanted: dict) -> dict:
    found = {}
    for key, prefix in wanted.items():
        for i, head in enumerate(header):
            if head.startswith(prefix):
                found[key] = i
                break
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise ValueError(f"USPTO extension file: columns not found: {missing}")
    return found
