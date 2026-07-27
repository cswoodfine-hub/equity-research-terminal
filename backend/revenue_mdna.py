"""Product revenue read out of the revenue table in a 10-K's MD&A.

The SEC data sets tag six products for a company that sells thirty. The rest are in the
filing, in the table every large-cap pharma prints of revenue by product, and that table
is already stored in ``filing_sections``. This reads it with rules and no model.

Two things make that harder than it sounds, and both are handled by refusing rather than
guessing. A 10-K contains other tables keyed by product name: Gilead prints patent
expiry years beside its products, so "Epclusa 2033 2032" parses as two-thousand-and-
thirty-three million dollars of revenue unless the table is anchored to a revenue
heading first. And filers lay the columns out differently, some giving US, non-US and
total, some total and growth, so which number is the revenue has to be worked out from
the numbers themselves rather than assumed from a position.

Every value is checked against the total revenue the company reported, and a product
whose row cannot be read unambiguously is skipped. What this cannot do is read a filer
that prints no such table, which is the honest limit of the approach.
"""

from __future__ import annotations

import re

# Where a revenue table starts. A heading naming revenue and products, or the sentence a
# filer writes before printing one.
_ANCHORS = (
    r"revenue by product",
    r"revenues? by product",
    r"product revenues?",
    r"net product sales",
    r"worldwide revenues?",
    r"revenue[s]? (?:for|of) (?:our|the) (?:key |principal |major )?products",
    r"selected (?:products|revenue)",
    r"the following table (?:summari[sz]es|presents|sets forth)[^.]{0,80}revenue",
    r"sales of (?:our|the company's) products",
    r"worldwide product sales",
    # A scale statement is itself a table: filers print one immediately above the
    # columns, and no prose carries it.
    r"\((?:dollars? |dollar )?(?:amounts )?in (?:millions|thousands)\)",
)
_ANCHOR = re.compile("|".join(_ANCHORS), re.I)

# A table's own scale statement.
_SCALE = re.compile(r"\(?(?:dollars |amounts )?in (millions|thousands|billions)\)?", re.I)
_SCALES = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}

_NUMBER = re.compile(r"\(?\$?\s*(\d[\d,]*(?:\.\d+)?)\)?")

# How far past the anchor a table runs. Long enough for thirty products, short enough
# that the next section's numbers are not swept in.
WINDOW = 4000


def table_regions(text: str) -> list:
    """Every place a revenue table might start.

    The first anchor is rarely the table: "product revenue" appears in the prose long
    before the columns do, and a window opened there reads nothing. So every anchor is a
    candidate and the caller keeps whichever reads the most products.
    """
    return [(m.start(), min(m.start() + WINDOW, len(text or "")))
            for m in _ANCHOR.finditer(text or "")]


def scale(text: str, default: float = 1e6) -> float:
    """The multiplier the table states, defaulting to millions, which is what every
    large-cap pharma uses. A wrong scale is a thousandfold error, so the statement is
    read from the table's own words where it makes one."""
    match = _SCALE.search(text or "")
    return _SCALES.get(match.group(1).lower(), default) if match else default


def _numbers(run: str) -> list:
    out = []
    for match in _NUMBER.finditer(run):
        raw = match.group(1)
        try:
            out.append((float(raw.replace(",", "")), raw))
        except ValueError:
            continue
    return out


def read_row(run: str) -> float | None:
    """The revenue on one product's row, or None when the row cannot be read.

    Filers print different columns. Lilly gives US, non-US, total, prior year and
    growth, so the total is the number the first two add to. Merck gives total and
    growth, so the total is the first and the growth is the small bare integer after it.
    A row that fits neither shape is refused: a number that might be revenue and might
    be a patent year is worth less than nothing.
    """
    values = _numbers(run)
    if not values:
        return None
    numbers = [v for v, _ in values]

    # A total is whatever the columns before it add up to, however many there are.
    # Lilly splits US and outside-US; Gilead splits US, Europe and other, so a rule
    # written for two components read Gilead's US column as its revenue.
    for start in range(len(numbers) - 1):
        running = 0.0
        for end in range(start, min(start + 4, len(numbers) - 1)):
            running += numbers[end]
            total = numbers[end + 1]
            if (end > start and _looks_like_money(values[end + 1])
                    and abs(running - total) <= max(2.0, total * 0.005)):
                return total

    # Revenue then its growth: "Prolia $ 4,414 1 %". The growth is a bare small
    # integer, which is what separates it from another money column.
    if (len(numbers) >= 2 and _looks_like_money(values[0])
            and _looks_like_percent(values[1])):
        return numbers[0]

    # This year, last year, then growth: "Camzyos 2,910 2,530 15 %". Both money
    # columns carry a separator and only the third is small and bare.
    if (len(numbers) >= 3 and _looks_like_money(values[0])
            and _looks_like_money(values[1]) and _looks_like_percent(values[2])):
        return numbers[0]

    # A single number is a revenue only when it carries a thousands separator, which
    # rules out the bare years and percentages that keep other tables company.
    if len(numbers) == 1 and _looks_like_money(values[0]):
        return numbers[0]
    return None


def _looks_like_percent(value) -> bool:
    number, raw = value
    return "," not in raw and "." not in raw and number <= 300


def _looks_like_money(value) -> bool:
    """Whether a number is written the way a filer writes money.

    A revenue in millions carries a thousands separator or a decimal point. A bare
    four-digit integer in a product table is a year: Gilead prints patent expiries
    beside its products, and "Veklury 2036 (7) 2035" is not two billion dollars of
    revenue. Refusing it costs the products stated under a thousand million without a
    separator, which are the rows that cannot be told from a footnote anyway.
    """
    number, raw = value
    return ("," in raw or "." in raw) and number > 0


def parse(text: str, brands: list, company_revenue: float | None = None) -> dict:
    """{brand: revenue} for the products the table names, in filing units.

    ``brands`` is what the company is known to sell, so a name that is not a product of
    this company is never read as one. ``company_revenue`` bounds the result: a product
    cannot earn more than the company did, and a table that says otherwise was not a
    revenue table.
    """
    best: dict = {}
    for start, end in table_regions(text or ""):
        found = _parse_window(re.sub(r"\s+", " ", text[start:end]), brands,
                              company_revenue)
        if len(found) > len(best):
            best = found
    return best


def _parse_window(window: str, brands: list, company_revenue: float | None) -> dict:
    """The products one candidate table names."""
    multiplier = scale(window)
    out = {}
    for brand in sorted(brands, key=len, reverse=True):
        if not brand or len(brand) < 4:
            continue
        pattern = re.compile(
            # The trailing separator is optional on the last column, or a row that
            # ends the window loses the very number the row is for.
            re.escape(brand)
            + r"\s*(?:\((?:\d|[a-z])\)\s*)?((?:\(?\$?\s*[\d,.]+\)?(?:\s+|$)){1,6})",
            re.I)
        match = pattern.search(window)
        if not match:
            continue
        value = read_row(match.group(1))
        if value is None:
            continue
        value *= multiplier
        if company_revenue and value > company_revenue:
            continue                  # not a revenue table, whatever else it is
        out[brand] = value
    return out


MDNA_SOURCE = "mdna_10k"


def extract(db_path=None) -> dict:
    """Read every stored 10-K MD&A and record the product revenue the SEC does not tag.

    Never overwrites a tagged figure: the data sets are the better record where they
    have one, and this is here for the products they leave out. Idempotent, since a
    year already written for a product is not written again.
    """
    import db

    conn = db.get_connection(db_path)
    written = 0
    try:
        companies = conn.execute("SELECT id, ticker FROM companies").fetchall()
        for company in companies:
            section = conn.execute(
                "SELECT text, filed_date FROM filing_sections WHERE company_id = ?"
                "  AND section = 'mdna' AND form_type = '10-K'"
                "  ORDER BY filed_date DESC LIMIT 1", (company["id"],)).fetchone()
            if not section:
                continue          # a 20-F filer stores no MD&A, so there is nothing here
            brands = {r["brand_name"]: r["id"] for r in conn.execute(
                "SELECT id, brand_name FROM assets WHERE owner_company_id = ?"
                "  AND brand_name IS NOT NULL", (company["id"],))}
            total = conn.execute(
                "SELECT value, fiscal_year FROM financials WHERE company_id = ?"
                "  AND metric = 'Revenues' AND period_type = 'FY'"
                "  ORDER BY fiscal_year DESC LIMIT 1", (company["id"],)).fetchone()
            found = parse(section["text"], list(brands),
                          total["value"] if total else None)
            year = total["fiscal_year"] if total else None
            if not year:
                continue          # a figure with no year is not a figure
            for brand, value in found.items():
                asset_id = brands.get(brand)
                if asset_id is None:
                    continue
                existing = conn.execute(
                    "SELECT source FROM asset_revenue WHERE asset_id = ?"
                    "  AND fiscal_year = ?", (asset_id, year)).fetchone()
                if existing:
                    continue      # the data sets already tag it, or this already ran
                conn.execute(
                    "INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit,"
                    "                           source, note)"
                    " VALUES (?, ?, ?, 'USD', ?, ?)",
                    (asset_id, year, value, MDNA_SOURCE,
                     f"revenue by product table, 10-K filed {section['filed_date']}"))
                written += 1
        conn.commit()
    finally:
        conn.close()
    return {"written": written}
