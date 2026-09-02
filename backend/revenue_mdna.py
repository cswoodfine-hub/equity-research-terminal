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
    # columns, and no prose carries it. Merck writes it without the brackets, on its own
    # line between the period and the years, so the bracketed form alone opened no window
    # over its product table at all.
    r"\((?:dollars? |dollar )?(?:amounts )?in (?:millions|thousands)\)",
    r"(?:^|\n)\s*\$?\s*(?:amounts )?in (?:millions|thousands)\s*(?:$|\n)",
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


# How closely a printed percentage has to match the ratio of two figures before it is
# taken as proof they are the same line in consecutive years. A filer rounds its own
# percentage to a whole number or one decimal, so a point of slack is the rounding, not
# a tolerance for being wrong.
_GROWTH_TOLERANCE = 0.011


# A filer brackets a fall rather than signing it, and the bracket is not part of the
# number, so it was dropped and the percentage read as a magnitude. That let a decline
# prove an increase. Regeneron prints Libtayo as 342.6, 146.8, 489.4 for this quarter,
# the same three for last, and 30%: the United States, elsewhere, and the total. Both
# 489.4 over 376.5 and 342.6 over 489.4 come to thirty per cent, one up and one down,
# and the magnitude test took whichever it reached first, which was the wrong one. The
# filer had said which: it brackets its falls, and 30% is not bracketed.
#
# The bracket closes on either side of the percent sign. Regeneron writes "(52 %)" and
# Bristol writes "(62) %", and a pattern that knew only the first found no sign at all
# on a Bristol row, fell back to magnitudes, and proved nothing.
_PERCENT_SIGN = re.compile(r"(\()?\s*(-)?\s*\d[\d,]*(?:\.\d+)?\s*(\))?\s*%\s*(\))?")


def _percent_signs(run: str, count: int) -> list:
    """+1 or -1 for each percentage in the run, in the order they are printed.

    Where the run does not yield the same number of percentages this reads elsewhere,
    every sign is positive, which leaves the row proved on magnitude as before. A row
    whose signs cannot be established is not a row to start reading signs into.
    """
    signs = [-1.0 if any(m.group(i) for i in (1, 2, 3, 4)) else 1.0
             for m in _PERCENT_SIGN.finditer(run or "")]
    return signs if len(signs) == count else [1.0] * count


def _totals(numbers: list) -> set:
    """Positions of the cells that are the sum of the two to four cells before them.

    A row that splits a product by geography prints the parts and then the whole, and
    the whole is the only cell a growth rate should be built on. Bristol's Abraxane
    reads "12 43 55 33 72 105" and then six percentages: the United States, the rest
    of the world, and the total, this quarter and last. The international pair, 43
    against 72, is a fall of 40%, and the row prints a 40% because that is what the
    international column did. It is a true pair and the wrong one, and the reader took
    it because it came first. 55 against 105 is the product.
    """
    found = set()
    for end in range(2, len(numbers)):
        running = 0.0
        for start in range(end - 1, max(-1, end - 5), -1):
            running += numbers[start]
            if end - start >= 2 and abs(running - numbers[end]) <= max(
                    1.0, abs(numbers[end]) * 0.003):
                found.add(end)
                break
    return found


def read_growth(run: str, spaced: bool = None):
    """(current, prior) for a product row, or None where the row does not prove it.

    Every reader above returns what a product earned. This returns what it earned and
    what it earned a year earlier, which is the pair a growth rate is made of, and no
    filing states a growth rate for the analyst to take instead.

    The danger is that a row of figures says nothing about which column is which year.
    So the proof required is the filer's own percentage: a row that prints 4,591, 3,926
    and 17% is proved, because 4,591 over 3,926 is 16.9% and no other pairing in that row
    comes to what the filer printed. A row with no percentage, or whose percentage does
    not match, returns nothing rather than a guess. That is what makes this safe to run
    across filers whose table shapes this module has never seen.

    The percentage is read with its sign, because on a row carrying a geography split as
    well as a total, a rise and a fall of the same size are both on the page and only the
    sign says which one the filer meant. And on such a row only the totals are paired,
    because the parts carry percentages of their own that prove pairs of their own.
    """
    values = _numbers(run, spaced)
    if len(values) < 3:
        return None
    money = [(i, v) for i, (v, _raw, pct) in enumerate(values) if not pct and v > 0]
    percents = [(i, v / 100.0, values[i][1]) for i, (v, _raw, pct) in enumerate(values) if pct]
    if not money or not percents:
        return None
    # Where the row prints parts and their totals, only the totals are candidates. One
    # total proves nothing about the shape, since any two cells might add to a third;
    # two is a row that does this on purpose.
    totals = _totals([v for _i, v in money])
    if len(totals) >= 2:
        money = [pair for k, pair in enumerate(money) if k in totals]
    signs = _percent_signs(run, len(percents))
    for a, (i, current) in enumerate(money):
        for j, prior in money[a + 1:]:
            if prior <= 0:
                continue
            ratio = current / prior - 1.0
            for position, (k, stated, _raw) in enumerate(percents):
                if k < j:
                    continue                  # the percentage closes the pair, never precedes it
                if abs(ratio - stated * signs[position]) <= _GROWTH_TOLERANCE:
                    return current, prior
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
    if (len(numbers) >= 2 and _money_in_row(values[0])
            and _looks_like_percent(values[1])):
        return numbers[0]

    # This year, last year, then growth: "Camzyos 2,910 2,530 15 %". Both money
    # columns carry a separator and only the third is small and bare.
    if (len(numbers) >= 3 and _money_in_row(values[0])
            and _money_in_row(values[1]) and _looks_like_percent(values[2])):
        return numbers[0]

    # Any run of money columns closed by a percentage column, the first being the
    # current year. The two cases above are this with one and two money columns;
    # AbbVie prints three, 2025 beside 2024 beside 2023, then four percentage columns
    # for actual and constant currency, and neither of the fixed shapes reached it.
    money_run = 0
    for value in values:
        if _looks_like_money(value):
            money_run += 1
        else:
            break
    if money_run >= 1 and len(values) > money_run and _looks_like_percent(values[money_run]):
        return numbers[0]

    # Year columns and nothing else: "INGREZZA $ 2,513.7 $ 2,313.5 $ 1,836.0". A table
    # with no growth column has no percentage to close the run, which every shape above
    # was relying on, and this is the commonest layout among the mid-caps. A bare year
    # cannot be mistaken for one of these: 2030 carries no separator and no decimal, so
    # it is not money, which is what keeps a patent-expiry table out.
    #
    # The run goes to eight because BioMarin states the change in dollars rather than in
    # percent: "VOXZOGO $ 926.9 $ 735.1 $ 469.9 $ 191.8 $ 265.2" is three years and two
    # movements, five money columns and not a percentage among them, and a cap of four
    # refused the whole table.
    if 1 <= len(values) <= 8 and all(_looks_like_money(v) for v in values):
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
    revenue.

    Strict, and used wherever a figure has to stand on its own. ``_money_in_row`` below
    is the same test relaxed for a number with a row around it.
    """
    number, raw, has_sign = value
    if has_sign:
        return False                  # a percentage is not money, however it is written
    return ("," in raw or "." in raw or " " in raw) and number > 0


def _money_in_row(value) -> bool:
    """Whether a number is money, given that a percentage closes the row it sits in.

    A bare integer under a thousand cannot be a year, so what makes it ambiguous is not
    its shape but its company: alone it is as likely a footnote marker. Biogen writes
    "we completed the sale of our rights to BYOOVIZ. (3) Other includes FUMADERM", and
    that 3 read as three million dollars of a product with no row in the table at all.

    Inside a row it is unambiguous, and refusing it cost every product a filer reports
    below a billion without a separator, which is most of Merck's table: "BRIDION 469
    429 9 %" could not be read. So this is used only by the two branches that require a
    percentage to close the row, and never for a number standing by itself.
    """
    number, raw, has_sign = value
    if has_sign:
        return False
    return number > 0 and ("," in raw or "." in raw or " " in raw or number < 1000)


def parse(text: str, brands: list, company_revenue: float | None = None) -> dict:
    """{brand: revenue} for the products the table names, in filing units.

    ``brands`` is what the company is known to sell, so a name that is not a product of
    this company is never read as one. ``company_revenue`` bounds the result: a product
    cannot earn more than the company did, and a table that says otherwise was not a
    revenue table.
    """
    # A long revenue table crosses several candidate windows: AbbVie's runs to twenty
    # products and the window is four thousand characters, so keeping only the richest
    # window returned four of them and dropped Humira. The windows are merged instead,
    # richest first, so the window that most looks like the revenue table settles any
    # product two of them disagree on and the rest can only add what it missed.
    merged: dict = {}
    per_window = []
    for start, end in table_regions(text or ""):
        found = _parse_window(re.sub(r"\s+", " ", text[start:end]), brands,
                              company_revenue)
        if found:
            per_window.append(found)
    for found in sorted(per_window, key=len, reverse=True):
        for brand, value in found.items():
            merged.setdefault(brand, value)

    # The parts cannot exceed the whole. A merged set that does has picked up a table
    # that was not revenue, or counted a grouping and its members, so it is refused
    # rather than half-trusted.
    if company_revenue and sum(merged.values()) > company_revenue:
        return max(per_window, key=len) if per_window else {}
    return merged


# A filer that reports each product by geography puts a label between the name and its
# first number, so "Skyrizi United States $ 15,202" defeats a pattern expecting the
# figure to follow the name. AbbVie lays out every product that way, three rows deep:
# the United States, then International, then a Total carrying the worldwide figure. The
# first number after the name is the domestic one and reading it understates the product
# by a third, so the Total row is what this looks for.
_GEOGRAPHY = re.compile(
    r"\s*(?:united states|u\.?s\.?|domestic|international|rest of (?:the )?world|"
    r"outside (?:the )?u\.?s\.?|ex-u\.?s\.?|worldwide)\b", re.I)

# How far past a product name its Total row can sit. Three geography rows with three
# year columns and four percentage columns each run to roughly this.
_GEOGRAPHY_SPAN = 420

# One number as a filer writes it, including a negative percentage whose sign sits
# outside its bracket: AbbVie writes "(49.5) %", and a token that closed at the bracket
# left the percent behind, so the figure read as a fourth money column and the row was
# refused for having no percentage to close it.
# The closing bracket can fall either side of the percent sign, and Regeneron puts it
# after: "(52 %)". Without the second, the cell ended at "(52 " and the row lost the
# percentage that proves it, so every fall Regeneron reports was unreadable.
_CELL = r"\(?[-+]?\$?\s*[\d,.]+\s*\)?\s*%?\s*\)?(?:\s+|$)"

_TOTAL_ROW = re.compile(r"\btotal\b[\s®™*†‡:]*" + f"((?:{_CELL}){{1,8}})", re.I)


def geographic_row(window: str, at: int, brands: list, spaced: bool = None):
    """The worldwide figure for a product broken out by geography, or None.

    ``at`` is where the product name ends. The Total has to appear before the next
    product does, or a product with no total of its own would collect the next one's.
    """
    span = window[at:at + _GEOGRAPHY_SPAN]
    if not _GEOGRAPHY.match(span):
        return None
    # Where the next product starts, so one row cannot borrow another's total.
    limit = len(span)
    lower = span.lower()
    for other in brands:
        if not other or len(other) < 4:
            continue
        found = lower.find(other.lower(), 1)
        if found > 0:
            limit = min(limit, found)
    # The row is matched against the whole span and then checked to have begun before
    # the next product, rather than searched inside a truncated span. Cutting the text
    # first sliced the last column mid-number: Humira's total ended "(49.5) " with the
    # percent sign beyond the cut, which then read as a fourth money column and the row
    # was refused for having no percentage to close it.
    match = _TOTAL_ROW.search(span)
    if not match or match.start() >= limit:
        return None
    return read_row(match.group(1), spaced)


_GROUP_JOIN = re.compile(r"(?:/|,|\band)\s*$", re.I)


def _in_a_printed_group(window: str, at: int) -> bool:
    """Whether the name at ``at`` is joined to the name before it."""
    return bool(_GROUP_JOIN.search(window[max(0, at - 6):at]))


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
            + f"((?:{_CELL}){{1,8}})",
            re.I)
        # A brand printed as a member of a group is not a row of its own. Merck heads
        # a line "KEYTRUDA/KEYTRUDA QLEX 8,366", "GARDASIL/GARDASIL 9 1,169", "JANUVIA/
        # JANUMET 2,544" and "PROQUAD, M-M-R II and VARIVAX 2,451"; the first name is
        # never followed by a figure and was never read, but the last one is, so Keytruda
        # Qlex was booked the pair, Gardasil 9 the pair and Varivax the trio. A name that
        # follows a slash, a comma or "and" belongs to the group, and the group's figure
        # belongs to no single product.
        match = next((m for m in pattern.finditer(window)
                      if not _in_a_printed_group(window, m.start())), None)
        if match:
            value = read_row(match.group(1), spaced)
        else:
            # The name may be followed by a geography label rather than a figure.
            plain = re.compile(re.escape(brand) + r"[\s®™*†‡]*", re.I).search(window)
            value = (geographic_row(window, plain.end(), brands, spaced)
                     if plain else None)
        if value is None:
            continue
        value *= multiplier
        if company_revenue and value > company_revenue:
            continue                  # not a revenue table, whatever else it is
        out[brand] = value
    return out


# --- reading a table whose products are not known in advance --------------------------

# Labels a revenue table carries that are not products: the subtotals, the geography
# rows and the catch-alls. A discovered name has to be refused against this list, because
# unlike the brand-matched path there is no external check that a row is a drug.
_NOT_A_PRODUCT = (
    "total", "net revenue", "net product", "net sales", "revenues", "revenue",
    "product sales", "other", "collaboration", "royalt", "license", "grant",
    "milestone", "united states", "international", "domestic", "worldwide",
    "rest of world", "outside", "ex-us", "subtotal", "combined", "aggregate",
    "therapies", "franchise", "segment", "cost of", "expense", "income", "margin",
    "year ended", "months ended", "in millions", "in thousands", "change", "amounts",
    # Expense schedules are laid out exactly like revenue tables and balance the same
    # way, so their rows are named out explicitly as well as caught by the total.
    "payroll", "benefits", "compensation", "research and", "development",
    "administrative", "clinical trial", "salary", "profit share", "discovery",
    "early stage", "late stage", "as compared", "due to", "impairment", "amortization",
    "amortisation", "depreciation", "interest", "tax", "restructuring",
    # A row named after who paid rather than what was sold. Caribou disclosed one headed
    # "related party" and it became an asset.
    "related party", "party", "partner", "affiliate", "joint venture",
)

# A product label is short and starts with a letter. Four words is the ceiling: "Nebulized
# Tyvaso" and "Botox Therapeutic" are products, a sentence is not.
# The comma belongs in a label. Without it Sarepta's closing line "Products, net" broke
# at the punctuation and was captured as "net" alone, which no total marker recognises,
# so the rows had nothing to be checked against and a correctly read table was discarded.
_ROW = re.compile(r"([A-Za-z][A-Za-z0-9®™\u2019',\-\./ ]{2,40}?)\s"
                  + f"((?:{_CELL}){{1,8}})")
_MAX_LABEL_WORDS = 4

# How closely the discovered products must sum to the total the table states. Exact
# agreement is what proves the table was read correctly rather than assumed, and it is
# the whole reason this can be trusted without a known product list. Half a percent
# allows for a filer rounding its own subtotal.
_SUM_TOLERANCE = 0.005

# The total row has to say it is a total of revenue. An expense schedule balances exactly
# as well as a revenue table and is laid out identically, so arithmetic alone cannot tell
# them apart: this found Neurocrine's payroll and Alnylam's research and development
# instead of their products. A filer names the line "Total net product sales" or "Total
# revenues", and never "Total revenues" for a cost.
# "Products, net" is a revenue total though it says neither revenue nor sales, which is
# how Sarepta closes its table. The cost test below is what keeps "Total product costs"
# out, so naming a product is enough here.
_REVENUE_TOTAL = re.compile(r"\b(?:revenue|revenues|sales|products?)\b", re.I)

# How a filer marks the line that everything above adds up to. Not always the word
# "total": Sarepta closes its table with "Products, net", and a detector looking only
# for "total" never found the line the rows were supposed to sum to, so the table was
# discarded although it had been read correctly.
_TOTAL_MARKER = re.compile(
    r"\btotal\b|\bproducts?,?\s+net\b|\bnet\s+product\b|\brevenues?,?\s+net\b", re.I)

# A filer that splits each product by region labels the rows "EYLEA - U.S" and
# "Libtayo - ROW". Those are one product each, reported twice, and the region has to come
# off before the two halves can be added or the drug identified.
_REGION_SUFFIX = re.compile(
    r"\s*[-\u2013:]\s*(?:u\.?s\.?a?|row|rest of world|international|ex-?u\.?s\.?|"
    r"outside the u\.?s\.?|domestic|worldwide|global|europe|japan)\.?\s*$", re.I)


def strip_region(label: str) -> str:
    """A product label with any trailing region marker removed."""
    text = (label or "").strip()
    for _ in range(2):
        stripped = _REGION_SUFFIX.sub("", text).strip()
        if stripped == text:
            break
        text = stripped
    return text
_COST_TOTAL = re.compile(r"\b(?:expense|cost|costs|operating|spend)\b", re.I)


def _plausible_label(label: str) -> bool:
    text = label.strip(" .:;$").strip()
    if len(text) < 4 or len(text.split()) > _MAX_LABEL_WORDS:
        return False
    low = text.lower()
    if any(term in low for term in _NOT_A_PRODUCT):
        return False
    # A label that is mostly digits is a year or a footnote marker, not a drug.
    return sum(c.isalpha() for c in text) >= 4


def discover(text: str, company_revenue: float | None = None) -> dict:
    """{product: revenue} read from a revenue table without knowing the products.

    The brand-matched path cannot help a company whose marketed products are not on
    file, which is most of the mid-caps: Alnylam, Neurocrine and BioMarin hold only
    pipeline rows derived from trials, so there is no name to search a table for. This
    reads the table structurally instead and takes the labels it finds.

    What makes that safe is arithmetic rather than a vocabulary. A revenue table prints
    its own total, so the rows are accepted only when they sum to it: Neurocrine's
    Ingrezza, Crenessity and Other come to 2,833.9 against a stated total net product
    sales of 2,833.9. A table that does not balance was either misread or was never a
    revenue table, and BioMarin prints a patent-expiry table keyed by the same product
    names whose columns are years. Refusing anything that does not add up rejects it
    without needing to know what it was.
    """
    best: dict = {}
    for start, end in table_regions(text or ""):
        window = re.sub(r"\s+", " ", text[start:end])
        multiplier = scale(window)
        spaced = not _COMMA_THOUSANDS.search(window)

        # Rows are walked in order and the sum is tested at each total, against
        # everything seen since the start of the window. A table ends at its total, and
        # the prose after it parses as rows too: "compared to 2024." reads as money
        # because the sentence's full stop looks like a decimal point. Sweeping the
        # whole window into one sum therefore never balanced. Stopping at each total
        # also handles a filer who prints a franchise subtotal before the grand one.
        products: dict = {}
        residual = 0.0
        for match in _ROW.finditer(window):
            label, run = match.group(1), match.group(2)
            value = read_row(run, spaced)
            if value is None:
                continue
            value *= multiplier
            if _TOTAL_MARKER.search(label):
                balances = products and abs(
                    sum(products.values()) + residual - value) <= max(
                        1.0, value * _SUM_TOLERANCE)
                names_revenue = (_REVENUE_TOTAL.search(label)
                                 and not _COST_TOTAL.search(label))
                if balances and names_revenue and len(products) > len(best):
                    best = dict(products)
                continue
            if company_revenue and value > company_revenue:
                continue
            if _plausible_label(label):
                # The regions of one product are added together, so a filer reporting
                # Eylea in the United States and Eylea in the rest of the world yields
                # one worldwide figure rather than two half products.
                name = strip_region(label.strip(" .:;$"))
                products[name] = products.get(name, 0.0) + value
            else:
                # A row that reads as money and is not a product still belongs to the
                # total. Neurocrine's table is Ingrezza, Crenessity and a 19m "Other",
                # and leaving that out left the sum short of the stated total, which
                # failed the check and threw away a table read correctly.
                residual += value
    return best


MDNA_SOURCE = "mdna_10k"
DISCOVERED_SOURCE = "mdna_10k_discovered"

# Words shared by half the company names in the universe, which would otherwise make
# every label look like a counterparty.
_CORPORATE_WORDS = {
    "inc", "corp", "corporation", "company", "plc", "ltd", "limited", "holdings",
    "group", "therapeutics", "pharmaceuticals", "pharma", "biosciences", "bio",
    "sciences", "medicines", "laboratories", "labs", "health", "healthcare", "the",
    "and", "nv", "sa", "ag", "as", "aktiengesellschaft", "biopharma",
}


def _asset_for(conn, company_id: int, label: str):
    """The asset a discovered revenue label belongs to, creating one if need be.

    Matching first, on a normalised name against this company's brands, generics and
    codes, so a product already on file gains its revenue rather than a second row.
    Where nothing matches the label is taken as a product name and an asset is created:
    the company printed it in its own revenue table, which is better evidence of a
    marketed product than anything else here has.
    """
    import approval_dates

    key = approval_dates.normalise(label)
    if len(key) < 4:
        return None
    for row in conn.execute(
        "SELECT id, brand_name, generic_name, internal_code FROM assets"
        "  WHERE owner_company_id = ?", (company_id,)):
        for name in (row["brand_name"], row["generic_name"], row["internal_code"]):
            other = approval_dates.normalise(name)
            if other and len(other) >= 4 and (other == key
                                              or (len(other) >= 7 and other in key)
                                              or (len(key) >= 7 and key in other)):
                return row["id"]
    # Creating an asset is the risky half of this, so it takes the strongest evidence
    # the label can offer: a single word. A drug brand is one word, and a multi-word
    # label is as likely to be a counterparty or a franchise. Arcturus discloses a row
    # headed "CSL Seqirus", its vaccine partner, which became a 66m product; guarding
    # against known company names could not catch it, because CSL is not in this
    # universe. A multi-word label can still match a product already on file above,
    # where the match itself is the evidence, and only creation is refused here.
    words = [w for w in re.split(r"[^A-Za-z0-9]+", label.strip()) if w]
    if len(words) != 1 or len(words[0]) < 4 or not words[0][0].isalpha():
        return None

    # And not a counterparty. Regeneron splits its revenue by collaborator, so its table
    # has rows headed "Sanofi" and "Bayer" carrying 5.9bn and 1.4bn. Both are single
    # words and both would have become drugs.
    tokens = {t for t in re.split(r"[^A-Za-z]+", label.lower()) if len(t) >= 3}
    for row in conn.execute("SELECT name FROM companies WHERE id != ?", (company_id,)):
        other = {t for t in re.split(r"[^A-Za-z]+", (row["name"] or "").lower())
                 if len(t) >= 3 and t not in _CORPORATE_WORDS}
        if other & tokens:
            return None

    conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, is_marketed, notes)"
        " VALUES (?, ?, 1, 'named in the revenue by product table of a 10-K')",
        (company_id, label.strip()))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


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

            # Nothing matched by name, so read the table structurally instead. This is
            # the only route for a company whose marketed products are not on file:
            # Neurocrine and Alnylam hold pipeline rows derived from trials and no brand
            # at all, so there was never a name to search their table for.
            discovered = 0
            if not found:
                for label, value in discover(
                        section["text"], total["value"] if total else None).items():
                    asset_id = _asset_for(conn, company["id"], label)
                    if asset_id is None:
                        continue
                    brands[label] = asset_id
                    found[label] = value
                    discovered += 1

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
