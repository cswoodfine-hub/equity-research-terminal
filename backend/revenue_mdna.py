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
    # A 20-F prints its scale in the column header rather than a sentence: "2025 $m %
    # %". AstraZeneca's revenue table carries no other heading a reader could match.
    r"\$m\s+%",
    r"(?:sales|revenue)\s+actual\s+cer",
    r"geographical review",
    # A European filer heads its columns with the currency and the constant-exchange
    # comparison rather than a sentence: "2025 USD m", "Change (at CER)".
    r"\b(?:usd|eur|dkk|chf|gbp)\s?(?:m|mn|millions?)\b",
    r"change\s*\(at\s*cer\)",
    r"\bnet\s+sales\b",
    r"(?:million|millions)\s+of\s+(?:euro|dkk|kroner)",
)
_ANCHOR = re.compile("|".join(_ANCHORS), re.I)

# A table's own scale statement.
_SCALE = re.compile(r"\(?(?:dollars |amounts )?in (millions|thousands|billions)\)?", re.I)
_SCALES = {"thousands": 1e3, "millions": 1e6, "billions": 1e9}

# A number, and whether a percent sign follows it. Novartis separates thousands with a
# space, so "7 748" is one number and not two; the groups after the first are required
# to be exactly three digits, which is what keeps "2025 2024" two years apart.
_NUMBER = re.compile(r"\(?([-+]?)\s*\$?\s*(\d[\d,]*(?:\.\d+)?)\)?\s*(%?)")
# The same, for a table that separates thousands with a space. Read only when the table
# uses no commas, because "93 105" is one number in Novartis's table and two in
# Gilead's, and nothing inside the row itself can tell them apart.
# Exactly one group is merged, never a run of them: "1 198 754" is Leqvio's 1,198
# followed by last year's 754, not 1.2 trillion. One merge reaches 999 999, which is
# more than a product earns in millions of any currency.
_NUMBER_SPACED = re.compile(
    r"\(?([-+]?)\s*\$?\s*(\d{1,3}[ ]\d{3}|\d[\d,]*(?:\.\d+)?)\)?\s*(%?)")
_COMMA_THOUSANDS = re.compile(r"\d,\d{3}")

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


def _numbers(run: str, spaced: bool = None) -> list:
    """(value, as written, followed by a percent sign) for each number in the run.

    ``spaced`` says whether this table writes thousands with a space. Left unset, it is
    read from the run itself: a run carrying a comma-separated thousand is not one.
    """
    if spaced is None:
        spaced = not _COMMA_THOUSANDS.search(run or "")
    pattern = _NUMBER_SPACED if spaced else _NUMBER
    out = []
    for match in pattern.finditer(run):
        sign, raw, pct = match.group(1), match.group(2), match.group(3)
        try:
            value = float(raw.replace(",", "").replace(" ", ""))
        except ValueError:
            continue
        out.append((-value if sign == "-" else value, raw, pct == "%"))
    return out


def _growth_agrees(current, prior, stated) -> bool:
    """Whether current against prior really is the change the row states."""
    if not prior or stated is None:
        return False
    return abs((current / prior - 1) * 100 - stated) <= max(1.5, abs(stated) * 0.05)


def _read_spaced(values) -> float | None:
    """One row of a table that separates thousands with a space.

    A footnote marker is a bare digit printed before the number, so "Fabhalta 3 505 129
    291" is footnote 3, then 505, then last year's 129, then +291%. Nothing in the shape
    separates that from "7 748", which is seven thousand seven hundred and forty-eight,
    so the row is asked to prove itself: the change column states the growth, and only
    the reading that produces it is taken. A row that proves neither is refused.
    """
    numbers = [v for v, _raw, _pct in values]
    if len(numbers) < 3:
        return None
    stated = numbers[2] if len(numbers) > 2 else None
    if _growth_agrees(numbers[0], numbers[1], stated):
        return numbers[0]
    # The same row with a leading footnote digit taken off the front.
    raw_first = values[0][1]
    if " " in raw_first and len(numbers) >= 3:
        split = float(raw_first.split(" ")[1])
        if _growth_agrees(split, numbers[1], numbers[2]):
            return split
    return None


def read_row(run: str, spaced: bool = None) -> float | None:
    """The revenue on one product's row, or None when the row cannot be read.

    Filers print different columns. Lilly gives US, non-US, total, prior year and
    growth, so the total is the number the first two add to. Merck gives total and
    growth, so the total is the first and the growth is the small bare integer after it.
    A row that fits neither shape is refused: a number that might be revenue and might
    be a patent year is worth less than nothing.
    """
    values = _numbers(run, spaced)
    if not values:
        return None
    # A spaced table cannot be read by shape alone, so it is read by its own arithmetic.
    if spaced and any(" " in raw for _v, raw, _p in values):
        return _read_spaced(values)
    numbers = [v for v, _raw, _pct in values]

    # A total is whatever the columns before it add up to, however many there are.
    # Lilly splits US and outside-US; Gilead splits US, Europe and other, so a rule
    # written for two components read Gilead's US column as its revenue.
    # The arithmetic is the evidence here, so the total does not have to be written
    # like money: Gilead's row reads "470 151 290 911 892 284 623 1,799", where 911 is
    # this year's total and 1,799 is last year's. Requiring a thousands separator
    # rejected the right number and took the one behind it.
    for start in range(len(numbers) - 1):
        running = 0.0
        for end in range(start, min(start + 4, len(numbers) - 1)):
            running += numbers[end]
            total = numbers[end + 1]
            # Tight: a filer's rounding is a unit or two, and a loose tolerance lets
            # consecutive patent years satisfy the arithmetic (2036 + 7 is 2035 to
            # within half a percent).
            if (end > start and not values[end + 1][2]
                    and abs(running - total) <= max(2.0, total * 0.001)):
                return total

    # A total printed before its parts: Novo gives world sales, then the regions that
    # add up to it. Same arithmetic, read the other way round.
    for total_at in range(len(numbers) - 2):
        if not _looks_like_money(values[total_at]):
            continue
        running = 0.0
        for end in range(total_at + 1, min(total_at + 6, len(numbers))):
            running += numbers[end]
            if (end > total_at + 1
                    and abs(running - numbers[total_at])
                    <= max(2.0, numbers[total_at] * 0.001)):
                return numbers[total_at]

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
    """A percent sign settles it; without one, a small bare integer is the growth
    column every filer prints beside a revenue."""
    number, raw, has_sign = value
    return has_sign or ("," not in raw and "." not in raw and " " not in raw
                        and number <= 300)


def _looks_like_money(value) -> bool:
    """Whether a number is written the way a filer writes money.

    A revenue in millions carries a thousands separator or a decimal point. A bare
    four-digit integer in a product table is a year: Gilead prints patent expiries
    beside its products, and "Veklury 2036 (7) 2035" is not two billion dollars of
    revenue. Refusing it costs the products stated under a thousand million without a
    separator, which are the rows that cannot be told from a footnote anyway.
    """
    number, raw, has_sign = value
    if has_sign:
        return False                  # a percentage is not money, however it is written
    return ("," in raw or "." in raw or " " in raw) and number > 0


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
    spaced = not _COMMA_THOUSANDS.search(window)
    out = {}
    for brand in sorted(brands, key=len, reverse=True):
        if not brand or len(brand) < 4:
            continue
        pattern = re.compile(
            # The trailing separator is optional on the last column, or a row that
            # ends the window loses the very number the row is for.
            # Trademark symbols and footnote markers sit between the name and its
            # number: Novo writes "Wegovy ® 79,106", Sanofi "Sarclisa (*) 588".
            re.escape(brand)
            + r"[\s®™*†‡]*(?:\((?:\*|\d|[a-z])\)[\s]*)?"
            + r"((?:\(?[-+]?\$?\s*[\d,.]+\s?%?\)?(?:\s+|$)){1,8})",
            re.I)
        match = pattern.search(window)
        if not match:
            continue
        value = read_row(match.group(1), spaced)
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
            # A 10-K's MD&A or a 20-F's financial review, whichever this filer files.
            section = conn.execute(
                "SELECT text, filed_date FROM filing_sections WHERE company_id = ?"
                "  AND section IN ('mdna', 'financial_review')"
                "  AND form_type IN ('10-K', '20-F')"
                "  ORDER BY filed_date DESC LIMIT 1", (company["id"],)).fetchone()
            if not section:
                continue          # nothing filed here to read
            # Only products the database can identify by something other than a name.
            # Sanofi's table has a subtotal row headed "Launches", and an asset row
            # exists under that name with no approval, no code and no ingredient behind
            # it, so a name-only row would collect a subtotal as if it were a drug.
            brands = {r["brand_name"]: r["id"] for r in conn.execute(
                """
                SELECT a.id, a.brand_name FROM assets a
                 WHERE a.owner_company_id = ? AND a.brand_name IS NOT NULL
                   AND (a.internal_code IS NOT NULL OR a.generic_name IS NOT NULL
                        OR EXISTS (SELECT 1 FROM approvals ap WHERE ap.asset_id = a.id))
                """, (company["id"],))}
            # The filer's own currency and year, since a 20-F is not filed in dollars:
            # Novo reports in kroner and Sanofi in euro, and storing either as USD
            # would overstate one product by sevenfold.
            total = conn.execute(
                "SELECT value, fiscal_year, unit FROM financials WHERE company_id = ?"
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
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (asset_id, year, value, total["unit"] or "USD", MDNA_SOURCE,
                     f"revenue by product table, filed {section['filed_date']}"))
                written += 1
        conn.commit()
    finally:
        conn.close()
    return {"written": written}
