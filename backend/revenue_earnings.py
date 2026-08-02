"""Quarterly product revenue read out of the table in an 8-K earnings exhibit.

The SEC data sets tag one figure a year, and they tag it from the 10-K, so a product's
revenue is between two and fourteen months old at any moment and a product acquired
mid-year has no figure at all until the following February. Biogen bought Apellis in May
2026; Empaveli and Syfovre were not in the FY2025 data sets and will not be tagged until
the FY2026 10-K. The 8-K filed on 2026-07-29 states 30.4m and 97.4m for the June quarter,
in a table this repository already downloads and stores.

The table itself is read by ``revenue_mdna.parse``, unchanged. Nothing here re-implements
the column arithmetic; a press release prints the same shape of table as the MD&A and the
existing reader handles it. What is new is the period, and the period is the whole risk.

An exhibit prints several tables. Biogen's prints six months before three months, so the
first period heading in the document describes a table further down the page: attribute by
document order and half-year revenue is filed as a quarter, silently, forever. So a figure
is bound to the heading that precedes the table it was read from, the text is cut to that
one table before it is parsed, and a table with no heading above it is skipped. Four of
the seven filers checked print no heading this can read, and they produce nothing rather
than a guess.
"""

from __future__ import annotations

import datetime as dt
import re

import revenue_mdna

SOURCE = "earnings_exhibit"

# The heading a filer prints above a period's columns. Two shapes cover the filers that
# state one at all: the sentence form every US filer uses, and the bare quarter label.
_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_SPAN_WORDS = {"three": 3, "six": 6, "nine": 9, "twelve": 12}

# "For the" is optional, because Gilead heads its columns "Three Months Ended". "ended
# on" is excluded, because that is the prose form and never a column header: Pfizer's
# footnotes say "the three months ended on March 29, 2026".
#
# The year may be separated from the date by the scale statement, which Gilead prints
# between them: "Three Months Ended / March 31, / (in millions, except per share amounts)
# 2026 2025". Only a parenthesis is allowed to intervene, so a stray year further down
# the page is never read as this table's.
_SPAN = re.compile(
    r"(?:for\s+the\s+)?(three|six|nine|twelve)\s+months?\s+ended\s+(?!on\b)"
    r"([a-z]+)\.?\s+(\d{1,2}),?\s*(?:\([^)]{0,60}\))?\s*(\d{4})?", re.I)
# "Second Quarter 2026", "Second-Quarter 2026", "Q2 2026" and "Q2 FY2026". Pfizer heads
# its revenue table "FIRST-QUARTER 2026 and 2025 - (UNAUDITED)".
_QUARTER = re.compile(
    r"\b(?:(first|second|third|fourth)[-\s]+quarter|q([1-4]))\s+(?:fy\s?)?(\d{4})\b",
    re.I)

# A column header sits on a short line. A sentence that happens to name a period does not,
# and Pfizer's exhibit carries several: a 418 character footnote explaining that its
# international subsidiaries close a month early was being read as a table heading, and
# the table it then governed was somebody else's.
HEADING_MAX_LINE = 120

_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4}

# How far below the heading the table runs. Long enough for the biggest product table
# seen (Pfizer's), short enough that the next period's table is never inside it.
TABLE_WINDOW = 9000

# How far above the heading the body starts. A filer prints the table's title and its
# scale statement above the period heading, not below it, and the reader anchors on both:
# Biogen's "PRODUCT REVENUE & TOTAL REVENUE / (unaudited, in millions)" sits immediately
# before "For the Three Months Ended". Cutting at the heading threw away the two lines
# that say what the table is and what the numbers are counted in.
LEAD_IN = 420


def span_to_period(months: int, end_month: int) -> str | None:
    """The period label for a span of months ending in a given month.

    A twelve month span is the year. A three month span is the quarter it ends in. Six
    months is the half. Nine months is a year-to-date stretch with no single label and is
    not stored: it is neither a quarter nor a year, and every use here wants one of those.
    """
    if months == 12:
        return "FY"
    if months == 6:
        return "H1" if end_month <= 6 else None
    if months == 3:
        return f"Q{(end_month - 1) // 3 + 1}"
    return None


def read_heading(text: str):
    """The last period heading in ``text``, as (period, period_end, fiscal_year).

    The last one, not the first: the heading that governs a table is the one directly
    above it, and this is called on the text leading up to a table rather than on the
    document. Returns None where no heading can be read, which is the signal to skip.
    """
    best = None
    for m in _SPAN.finditer(text):
        month_name = m.group(2).lower()
        if month_name not in _MONTHS:
            continue
        months = _SPAN_WORDS[m.group(1).lower()]
        end_month = _MONTHS.index(month_name) + 1
        year = m.group(4)
        if not year:
            continue                     # a period with no year is not a period
        period = span_to_period(months, end_month)
        if period is None:
            continue
        try:
            end = dt.date(int(year), end_month, int(m.group(3)))
        except ValueError:
            continue
        best = (m.start(), period, end.isoformat(), int(year))
    for m in _QUARTER.finditer(text):
        quarter = _ORDINALS.get((m.group(1) or "").lower()) or int(m.group(2))
        year = int(m.group(3))
        # A quarter label carries no closing day, so the period end is the quarter's on a
        # calendar year. A filer on a broken fiscal year states the span form instead.
        month = quarter * 3
        end = dt.date(year, month, 30 if month in (6, 9) else 31)
        if best is None or m.start() > best[0]:
            best = (m.start(), f"Q{quarter}", end.isoformat(), year)
    return best[1:] if best else None


def _on_a_heading_line(text: str, index: int) -> bool:
    """Whether the match at ``index`` sits on a line short enough to be a column header."""
    start = text.rfind("\n", 0, index) + 1
    stop = text.find("\n", index)
    stop = len(text) if stop == -1 else stop
    return stop - start <= HEADING_MAX_LINE


def tables(text: str) -> list:
    """Every period heading in the document with the stretch of text it governs.

    Each entry is (period, period_end, fiscal_year, body). Bodies overlap where a filer
    prints two headings close together; each is parsed separately and the reader binds a
    product to whichever heading is nearest above it.
    """
    marks = []
    for pattern in (_SPAN, _QUARTER):
        for m in pattern.finditer(text):
            if not _on_a_heading_line(text, m.start()):
                continue
            head = read_heading(text[max(0, m.start() - 4): m.end()])
            if head:
                marks.append((m.start(), head))
    marks.sort()
    out = []
    for i, (start, head) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        # A heading owns the text up to the next heading, capped so a document that
        # states one heading and then runs on does not hand a table the whole filing.
        # The lead-in reaches back for the title and scale line printed above it, but
        # never past the previous heading, which belongs to another period.
        floor = marks[i - 1][0] if i else 0
        body = text[max(floor, start - LEAD_IN): min(stop, start + TABLE_WINDOW)]
        out.append((*head, body))
    return out


# --- Table shapes revenue_mdna does not read --------------------------------
#
# It reads a table whose row is one line of product name and figures. Two filers here
# print neither.
#
# Gilead splits a product across a geography block, so the name line carries only the US
# figure and the worldwide total is a bare line of numbers underneath:
#
#     Biktarvy U.S. $ 2,573 $ 2,474
#     Europe 437 375
#     Rest of World 352 301
#     3,361 3,150
#
# Pfizer leads with the worldwide figure and puts the name on its own line whenever a
# footnote marker follows it:
#
#     Eliquis (b)
#     2,166 1,923 13% 8% 1,435 1,299 10% 731 624 17% 4%
#
# Reading either by position alone would be guessing, so neither is trusted on position:
# a figure is kept only when the row's own arithmetic holds. Gilead's legs must sum to
# the total it prints, and Pfizer's United States and international columns must sum to
# the worldwide one. A misread row does not reconcile and is dropped, which is what makes
# it safe to read a table this repository cannot see the column headers of.

_NUMBER = re.compile(
    r"\(?\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\)?(\s*%)?")
_GEOGRAPHY = re.compile(r"^\s*(u\.?s\.?|united states|europe|rest of world|international)",
                        re.I)
_BRAND = r"[A-Z][A-Za-z0-9\u00ae\u2019'\-/ ]*?"
# A name that leads its own geography block: "Biktarvy U.S. $ 2,573 $ 2,474".
_BLOCK_HEAD = re.compile(rf"^\s*({_BRAND})\s*(?:\(\d\))?\s+(?:U\.S\.|United States)\s",
                         re.I)
# The same, where a footnote pushes the geographies onto the following lines.
_BLOCK_ALONE = re.compile(rf"^\s*({_BRAND})(?:\s*-\s*[A-Za-z ]+)?\s*\(\d\)\s*$")
# A name and its figures on one line, and a name whose figures are on the next.
_ROW_INLINE = re.compile(rf"^\s*({_BRAND})\s+(\d[\d,.].*)$")
_ROW_ALONE = re.compile(rf"^\s*({_BRAND})\s*(?:\([a-z]\))?\s*$")


def _figures(line: str) -> list:
    """The plain numbers on a line. Percentages are not figures and are dropped, which is
    what separates a value column from the change column printed beside it."""
    return [float(m.group(1).replace(",", ""))
            for m in _NUMBER.finditer(line) if not m.group(2)]


def read_geography_blocks(text: str) -> dict:
    """{brand: total} for a table that splits each product across its regions."""
    lines, out = text.split("\n"), {}
    index = 0
    while index < len(lines):
        head = _BLOCK_HEAD.match(lines[index])
        if head:
            brand, legs, cursor = head.group(1).strip(), _figures(lines[index])[:1], index + 1
        else:
            alone = _BLOCK_ALONE.match(lines[index])
            if not (alone and index + 1 < len(lines)
                    and _GEOGRAPHY.match(lines[index + 1])):
                index += 1
                continue
            brand, legs, cursor = alone.group(1).strip(), [], index + 1
        while cursor < len(lines) and _GEOGRAPHY.match(lines[cursor]):
            legs += _figures(lines[cursor])[:1] or [0.0]
            cursor += 1
        total = _figures(lines[cursor])[:1] if cursor < len(lines) else []
        # Every leg and the total are printed rounded, so the sum can be out by half a
        # unit per line. Further apart than that is not this shape, and is dropped.
        if total and legs and abs(sum(legs) - total[0]) <= 0.5 * (len(legs) + 1):
            out[brand] = total[0]
        index = cursor + 1
    return out


def read_worldwide_rows(text: str) -> dict:
    """{brand: worldwide} for a table whose row leads with the worldwide figure."""
    lines, out = text.split("\n"), {}
    for index, line in enumerate(lines):
        inline = _ROW_INLINE.match(line)
        if inline:
            brand, values = inline.group(1).strip(), _figures(inline.group(2))
        else:
            alone = _ROW_ALONE.match(line)
            if not alone or not alone.group(1).strip() or index + 1 >= len(lines):
                continue
            brand, values = alone.group(1).strip(), _figures(lines[index + 1])
        # Worldwide, then the prior year, then the same pair for the United States and
        # for international. Fewer columns than that is a different table.
        if len(values) < 5:
            continue
        worldwide, united_states, international = values[0], values[2], values[4]
        if abs((united_states + international) - worldwide) <= 1.5:
            out[brand] = worldwide
    return out


def read_table(body: str, brands, company_revenue=None) -> dict:
    """The products in one table, whichever of the three shapes it is printed in.

    The shapes are tried in order and the first that yields anything wins. They do not
    overlap: a row read by one is not a row the others recognise, since each is gated on
    arithmetic only its own layout satisfies.
    """
    found = revenue_mdna.parse(body, brands, company_revenue)
    if found:
        return found
    known = set(brands)
    for reader in (read_geography_blocks, read_worldwide_rows):
        # A subtotal row is shaped exactly like a product row, so the brand list is the
        # only thing separating "Total HIV" from a drug. Same guard revenue_mdna applies.
        got = {brand: value for brand, value in reader(body).items() if brand in known}
        if got:
            # The table states its own scale. Both filers reading this way print
            # millions, but the statement is read rather than assumed.
            scale = revenue_mdna.scale(body)
            return {brand: value * scale for brand, value in got.items()}
    return {}


def parse(text: str, brands, company_revenue=None) -> dict:
    """{brand: {value, period, period_end, fiscal_year}} for the periods stated.

    A brand found under more than one heading keeps the shortest period, so a product
    printed in both the three month and six month table is stored as the quarter. The
    half-year figure is the quarter plus the one before it and carries nothing the two
    quarters do not.
    """
    rank = {"FY": 3, "H1": 2}
    found = {}
    for period, period_end, year, body in tables(text):
        for brand, value in read_table(body, brands, company_revenue).items():
            prior = found.get(brand)
            if prior and rank.get(prior["period"], 1) <= rank.get(period, 1):
                continue
            found[brand] = {"value": value, "period": period,
                            "period_end": period_end, "fiscal_year": year}
    return found


def _quarter_revenue(conn, company_id: int, period_end: str):
    """The company's own total for the period, as the ceiling a product is checked on.

    The annual figure is the wrong ceiling for a quarter: it would pass a product whose
    row was misread by four times over. Returns None where no quarterly total is on file,
    and the caller then parses without a ceiling rather than against a wrong one.
    """
    row = conn.execute(
        "SELECT value, unit FROM financials WHERE company_id = ?"
        "  AND metric = 'Revenues' AND period_type = 'Q' AND period_end = ?"
        "  ORDER BY fiscal_year DESC LIMIT 1", (company_id, period_end)).fetchone()
    return (row["value"], row["unit"]) if row else (None, None)


def extract(db_path=None) -> dict:
    """Read every stored earnings exhibit and record the product revenue it states.

    Never overwrites a figure already on file for the same asset, year and period, so a
    hand entered correction and the data sets both outrank this. Idempotent.
    """
    import db

    conn = db.get_connection(db_path)
    written, skipped_no_period = 0, 0
    try:
        for company in conn.execute("SELECT id, ticker FROM companies"):
            sections = conn.execute(
                "SELECT text, filed_date, accession, form_type FROM filing_sections"
                "  WHERE company_id = ? AND form_type IN ('8-K', '6-K')"
                "    AND section LIKE 'exhibit%'"
                "  ORDER BY filed_date DESC LIMIT 8", (company["id"],)).fetchall()
            if not sections:
                continue
            # Only products the database can identify by something other than a name: a
            # subtotal row headed "Launches" would otherwise be collected as a drug.
            # Pfizer's six largest products failed this for a while, being brand-only
            # rows whose applications Astellas and Bristol Myers hold; asset_identity
            # gives them their ingredient, so the guard can stay as strict as it reads.
            brands = {r["brand_name"]: r["id"] for r in conn.execute(
                """
                SELECT a.id, a.brand_name FROM assets a
                 WHERE a.owner_company_id = ? AND a.brand_name IS NOT NULL
                   AND a.brand_name <> ''
                   AND (a.internal_code IS NOT NULL OR a.generic_name IS NOT NULL
                        OR EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = a.id))
                """, (company["id"],))}
            if not brands:
                continue
            for section in sections:
                if not tables(section["text"]):
                    skipped_no_period += 1
                    continue
                for period, period_end, year, body in tables(section["text"]):
                    total, unit = _quarter_revenue(conn, company["id"], period_end)
                    for brand, value in read_table(
                            body, list(brands), total).items():
                        asset_id = brands[brand]
                        if conn.execute(
                                "SELECT 1 FROM asset_revenue WHERE asset_id = ?"
                                "  AND fiscal_year = ? AND period = ?",
                                (asset_id, year, period)).fetchone():
                            continue
                        conn.execute(
                            "INSERT INTO asset_revenue (asset_id, fiscal_year, period,"
                            "   period_end, value, unit, source, note, is_curated)"
                            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                            (asset_id, year, period, period_end, value, unit or "USD",
                             SOURCE,
                             f"{section['form_type']} exhibit {section['accession']}, "
                             f"filed {section['filed_date']}"))
                        written += 1
        conn.commit()
    finally:
        conn.close()
    return {"written": written, "skipped_no_period": skipped_no_period}
