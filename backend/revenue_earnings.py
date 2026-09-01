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
#
# Merck stacks its column header one token to a line and puts the scale between the
# span and the date: "Year Ended / $ in millions / Dec. 31, 2025". So "year ended" is a
# twelve month span, an unbracketed scale line may sit before the date, and the month
# may be abbreviated. Its quarterly table does the same with a bare ordinal: "Second
# Quarter / $ in millions / 2026".
_SPAN = re.compile(
    r"(?:for\s+the\s+)?(?:(?P<months>three|six|nine|twelve)\s+months?|(?P<year_span>year))"
    r"\s+ended\s+(?!on\b)"
    r"(?:\$?\s*in\s+(?:millions|thousands|billions)\s*)?"
    r"(?P<month>[a-z]+)\.?\s+(?P<day>\d{1,2}),?\s*(?:\([^)]{0,60}\))?\s*(?P<year>\d{4})?",
    re.I)
# "Second Quarter 2026", "Second-Quarter 2026", "Q2 2026" and "Q2 FY2026". Pfizer heads
# its revenue table "FIRST-QUARTER 2026 and 2025 - (UNAUDITED)".
_QUARTER = re.compile(
    r"\b(?:(first|second|third|fourth)[-\s]+quarter|q([1-4]))"
    r"(?:\s*\$?\s*in\s+(?:millions|thousands|billions))?"
    r"\s+(?:fy\s?)?(\d{4})\b",
    re.I)

# A table these readers must not touch, whatever heading sits above it. Merck's Table 3,
# "Franchise / Key Product Sales", prints every quarter of two years plus the year-to-
# date and full-year columns on one row: "Keytruda 7,906 7,904 15,810 7,205 7,956
# 15,161 8,142 8,337 31,641". read_row proves a total by its arithmetic, and here the
# arithmetic holds three times over, so it returned 15,161 for a heading that said Q2
# and 31,641 for one that said Q4. A half year and a full year were stored as quarters.
# Reading that grid means mapping figures to column headers, which nothing here does;
# until something does, the grid fences a heading's reach the way an unreadable header
# line does. A YTD column is the same shape by any filer.
_UNREADABLE_TABLE = re.compile(
    r"franchise\s*/\s*key\s+product\s+sales|^\s*(?:[a-z]+\s+)?ytd\s*$", re.I | re.M)

# A line naming a period that no pattern above turns into one. Bristol Myers heads both
# its product tables with a column header this module cannot read: "($ amounts in
# millions) Year Ended December 31, 2025 % Change from Year Ended December 31, 2024 %
# Change from Year Ended December 31, 2024 Ex-F/X**" is 190 characters, too long to be a
# heading line, and states a year rather than a span of months. The quarterly table's
# header is the same shape. So neither table has a heading, and the module's rule is that
# such a table is skipped rather than guessed at. Without this the nearest heading eight
# thousand characters above reaches down and claims it, and Eliquis's full year of 14,443
# is stored as a quarter.
#
# "ended on" is excluded here for the same reason it is excluded above: that is the prose
# form, and Pfizer's footnote about its international subsidiaries is not a column header
# whose table should be skipped.
_PERIOD_PHRASE = re.compile(
    r"\b(?:year|(?:three|six|nine|twelve)\s+months?)\s+ended\s+(?!on\b)", re.I)

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


def _month_index(name: str):
    """1..12 for a month written in full or abbreviated, else None. "Dec." and "Sept" are
    both Merck's; three letters settle every month."""
    name = name.lower().rstrip(".")
    for i, full in enumerate(_MONTHS):
        if name == full or (len(name) >= 3 and full.startswith(name[:3])
                            and full.startswith(name)):
            return i + 1
    return None


def _span_head(m, year=None):
    """(period, period_end, fiscal_year) for a span match, or None where it is not one.

    ``year`` is the fallback for a heading that states none of its own, which is what
    happens where several headings share a line and the year row printed beneath them.
    """
    end_month = _month_index(m.group("month"))
    if end_month is None:
        return None
    stated = m.group("year") or year
    if not stated:
        return None                      # a period with no year is not a period
    months = 12 if m.group("year_span") else _SPAN_WORDS[m.group("months").lower()]
    period = span_to_period(months, end_month)
    if period is None:
        return None
    try:
        end = dt.date(int(stated), end_month, int(m.group("day")))
    except ValueError:
        return None
    return period, end.isoformat(), int(stated)


def _quarter_head(m):
    """(period, period_end, fiscal_year) for a bare quarter label.

    A quarter label carries no closing day, so the period end is the quarter's on a
    calendar year. A filer on a broken fiscal year states the span form instead.
    """
    quarter = _ORDINALS.get((m.group(1) or "").lower()) or int(m.group(2))
    year, month = int(m.group(3)), quarter * 3
    end = dt.date(year, month, 30 if month in (6, 9) else 31)
    return f"Q{quarter}", end.isoformat(), year


def read_heading(text: str):
    """The last period heading in ``text``, as (period, period_end, fiscal_year).

    The last one, not the first: the heading that governs a table is the one directly
    above it, and this is called on the text leading up to a table rather than on the
    document. Returns None where no heading can be read, which is the signal to skip.
    """
    best = None
    for pattern, reader in ((_SPAN, _span_head), (_QUARTER, _quarter_head)):
        for m in pattern.finditer(text):
            head = reader(m)
            if head and (best is None or m.start() >= best[0]):
                best = (m.start(), *head)
    return best[1:] if best else None


def _on_a_heading_line(text: str, index: int) -> bool:
    """Whether the match at ``index`` sits on a line short enough to be a column header."""
    start = text.rfind("\n", 0, index) + 1
    stop = text.find("\n", index)
    stop = len(text) if stop == -1 else stop
    return stop - start <= HEADING_MAX_LINE


def _line_start(text: str, index: int) -> int:
    """Where the line holding ``index`` begins."""
    return text.rfind("\n", 0, index) + 1


# How far apart two headings can sit and still head one table's columns. Vertex prints
# both on one line with a space between them; BioMarin's wraps, so its "Three Months
# Ended" and "Six Months Ended" are separated by a newline and the date that belongs to
# the first. Two headings over two different tables are separated by the whole of the
# first table, which is never this close.
HEADER_GAP = 80


def _one_per_header(text: str, marks: list) -> list:
    """Collapse a block of headings to the leftmost, which heads the leftmost columns.

    Vertex prints its product table under two headings on one line, "Three Months Ended
    June 30, Six Months Ended June 30,", over the columns 2026 2025 2026 2025. Every
    reader here takes the figures at the front of a row, so the figures they return are
    the quarter's, and the heading describing them is the first of the block rather than
    the last. Binding them to the nearest heading above filed each Vertex quarter as a
    half year: Casgevy's June quarter of 76.4 was stored as six months, when the six
    month column two places to its right reads 119.3.

    Proximity rather than a shared line, because the same header wraps. BioMarin prints

        Three Months Ended
        June 30, Six Months Ended
        June 30,
        2026 2025 % Change 2026 2025 % Change

    which is one header over six columns and two headings on three lines. Keyed on the
    line, the three month heading was invisible and the six month one took the table, so
    VOXZOGO's June quarter of $253mm was filed as a half year against the $472mm printed
    three columns along.

    The rest of the block is dropped rather than parsed, because the columns those
    headings own are not columns these readers can reach. The headings share the year row
    printed beneath them, so one stating no year of its own takes a neighbour's.
    """
    out, consumed, index = [], set(), 0
    while index < len(marks):
        stop = index + 1
        while stop < len(marks) and marks[stop][0] - marks[stop - 1][1] <= HEADER_GAP:
            stop += 1
        group = marks[index:stop]
        year = next((head[2] for _, _, head, _ in reversed(group) if head), None)
        start, _end, head, match = group[0]
        if head is None and match is not None and year is not None:
            head = _span_head(match, year)
        if head:
            out.append((start, head))
            # Every line the block spans, so the members this dropped are not then read
            # as headers nobody could parse. BioMarin's header wraps onto the line that
            # carries its six month heading, and fencing there cut the table off at the
            # heading that had just been chosen for it.
            for mark in group:
                consumed.add(_line_start(text, mark[0]))
                consumed.add(_line_start(text, mark[1]))
        index = stop
    return out, consumed


def _unread_headings(text: str, headed: set) -> list:
    """Line starts that name a period but that no reader here turned into one, sorted.

    These fence a heading's reach. A table sitting under one of them is headed by
    something this module cannot read, and the module skips such a table rather than
    letting a heading further up the page describe it.

    ``headed`` is every line a heading block covers, not only the line of the heading
    kept from it: a block's other members were read and deliberately dropped, and a
    fence on one of those lines would cut a table off from the heading just chosen for
    it.
    """
    out = set()
    for m in _PERIOD_PHRASE.finditer(text):
        line = _line_start(text, m.start())
        if line not in headed:
            out.add(line)
    for m in _UNREADABLE_TABLE.finditer(text):
        out.add(_line_start(text, m.start()))
    return sorted(out)


def tables(text: str) -> list:
    """Every period heading in the document with the stretch of text it governs.

    Each entry is (period, period_end, fiscal_year, body). Bodies overlap where a filer
    prints two headings close together; each is parsed separately and the reader binds a
    product to whichever heading is nearest above it.
    """
    marks = []
    for pattern, reader in ((_SPAN, _span_head), (_QUARTER, _quarter_head)):
        for m in pattern.finditer(text):
            if _on_a_heading_line(text, m.start()):
                marks.append((m.start(), m.end(), reader(m),
                              m if pattern is _SPAN else None))
    marks.sort(key=lambda mark: mark[0])
    heads, consumed = _one_per_header(text, marks)
    fences = _unread_headings(text, consumed)
    out = []
    for i, (start, head) in enumerate(heads):
        stop = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        # A heading owns the text up to the next heading or the next header line that
        # could not be read as one, capped so a document that states one heading and then
        # runs on does not hand a table the whole filing. The lead-in reaches back for the
        # title and scale line printed above it, but never past the previous heading,
        # which belongs to another period.
        stop = min(stop, next((f for f in fences if f > start), stop))
        floor = heads[i - 1][0] if i else 0
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
