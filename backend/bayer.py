"""Bayer's annual report tables, which it publishes as a workbook, read as its statements.

Bayer is not an SEC registrant, so EDGAR holds nothing for it, and until this module it
carried no financial row: no cost structure, no tax rate, no debt and no share count, so
none of its 59 marketed assets or its pipeline could be valued. The ESEF route built for it
cannot close that gap. filings.xbrl.org, the only free index of ESEF reports as xBRL-JSON,
held no German filer at all on 2026-09-25 (none for country DE, against 1,179 French and
2,204 Danish filings), because German reports are lodged with the Unternehmensregister and
the index is fed by the national registers that pass theirs on. Bayer's LEI resolves at
GLEIF to Bayer Aktiengesellschaft and the index answers with nothing.

Bayer publishes the answer itself. Its online annual report carries every table in it as
one workbook, free and without a login, at

    https://reports.bayer.com/annual-report-2025/en/_assets/downloads/entire-bayer-ar25.xlsx

It holds the consolidated income statement, statement of financial position and cash flow
statement, the Pharmaceuticals division's key data, its fifteen best-selling products, and
the share count behind core earnings per share. Each year's report has its own address, so
the reader tries the latest year first and falls back one.

This is the pure half, a loaded workbook in and records out, as ``roche.py`` is for Roche.
The download and the write are ``fetchers/financials_ir.py``.

WHAT IS DIFFERENT FROM ROCHE, AND DECIDES THE PARSER.

A label repeats between sections. The statement of financial position carries "Other
financial assets", "Other receivables" and "Deferred taxes" under both noncurrent and
current assets, and "Other provisions", "Financial liabilities" and "Other liabilities"
under both noncurrent and current liabilities. So a balance sheet label is looked up inside
its section, never across the sheet: the first "Financial liabilities" is the long-term
debt and the second is the short-term.

A subtotal has no label. Each section's total is a row of numbers with an empty first cell,
so it is found as the first unlabelled row after the section heading.

A label carries its footnote. "EBIT1" is EBIT with footnote 1, and "CT Fluid Delivery2" is
a product with footnote 2. A trademark sign follows every brand. Both are stripped before a
label is compared.

A cost is negative, as in any statement, and this book stores every charge positive, so the
sign is flipped per metric rather than by taking an absolute value.

WHAT MAKES IT SAFE. Every figure that has a total above it is checked against that total:
gross profit, EBIT, the financial result, income before and after tax and its split
between Bayer's stockholders and the minority; every section of the balance sheet and both
of its sides; operating, investing and financing cash flow and the year's movement in cash;
and the fifteen products against the table's own total. ``reconcile`` returns what failed
and the fetcher writes nothing for a workbook that does not tie.

WHAT THE WORKBOOK DOES NOT HOLD, AND IS NOT FILLED. Product sales by region: the division is
split by region and its products are not, so no asset carries a regional row. Depreciation
apart from impairment: the cash flow statement adds them back as one line, 8,783 in 2024 of
which most was impairment, so no depreciation metric is written rather than one a
replacement-capital-expenditure calculation would misread. Bayer's Crop Science and Consumer
Health divisions sit inside every group line, which is what a group statement is.
"""

from __future__ import annotations

import datetime as dt
import re

CURRENCY = "EUR"
MILLION = 1_000_000.0

URL_TEMPLATE = ("https://reports.bayer.com/annual-report-{year}/en/_assets/downloads/"
                "entire-bayer-ar{yy:02d}.xlsx")

INCOME_SHEET = "cfs-income-statement"
BALANCE_SHEET = "cfs-financial-position"
CASHFLOW_SHEET = "cfs-cash-flows"
PRODUCT_SHEET = "cmr-best-selling-pharm-products"
DIVISION_SHEET = "cmr-key-data-pharmaceuticals"
SHARES_SHEET = "cmr-core-earnings-per-share"
SHEETS = (INCOME_SHEET, BALANCE_SHEET, CASHFLOW_SHEET, PRODUCT_SHEET, DIVISION_SHEET,
          SHARES_SHEET)

NOTE = "Bayer annual report workbook, all tables"

# How far two figures that should be equal may sit apart. The sheets are whole millions,
# so a total can differ from the sum of its rounded parts by a euro million or two.
TOLERANCE_M = 3.0

# The statement's own labels, mapped to the metric vocabulary the rest of the book uses.
# ``negate`` is True where the sheet writes the line as a charge and the book stores
# charges positive. Selling and administration are two lines here and one in the book.
INCOME_METRICS = (
    ("Net sales", "Revenues", False),
    ("Cost of goods sold", "CostOfRevenue", True),
    ("Gross profit", "GrossProfit", False),
    ("Research and development expenses", "ResearchAndDevelopmentExpense", True),
    ("Other operating income", "OtherOperatingIncome", False),
    ("Other operating expenses", "OtherOperatingExpense", True),
    ("EBIT", "OperatingIncomeLoss", False),
    ("Income before income taxes", "IncomeBeforeTax", False),
    ("Income taxes", "IncomeTaxExpense", True),
    ("Income after income taxes", "NetIncomeLoss", False),
    ("of which attributable to noncontrolling interest", "NetIncomeAttributableToNci", False),
    ("of which attributable to Bayer AG stockholders (net income)",
     "NetIncomeAttributableToParent", False),
    ("Diluted", "EarningsPerShareDiluted", False),
)
SGA_LABELS = ("Selling expenses", "General administration expenses")

# (section heading, label, metric). Liabilities are written positive in this sheet already.
BALANCE_METRICS = (
    ("Noncurrent assets", "Goodwill", "Goodwill"),
    ("Noncurrent assets", "Other intangible assets", "IntangibleAssets"),
    ("Noncurrent assets", "Property, plant and equipment", "PropertyPlantAndEquipmentNet"),
    ("Current assets", "Inventories", "Inventory"),
    ("Current assets", "Trade accounts receivable", "AccountsReceivable"),
    ("Current assets", "Cash and cash equivalents", "CashAndEquivalents"),
    ("Current liabilities", "Trade accounts payable", "AccountsPayable"),
)
SECTIONS = ("Noncurrent assets", "Current assets", "Equity", "Noncurrent liabilities",
            "Current liabilities")

CASHFLOW_METRICS = (
    ("Net cash provided by (used in) operating activities", "CashFlowOperating", False),
    # Bayer states additions to plant and to intangible assets as one outflow. The book's
    # line is plant alone where a filer splits them; this one does not.
    ("Cash outflows for additions to property, plant, equipment and intangible assets",
     "CapitalExpenditure", True),
    ("Net cash provided by (used in) investing activities", "CashFlowInvesting", False),
    ("Net cash provided by (used in) financing activities", "CashFlowFinancing", False),
    ("Dividend payments", "DividendsPaid", True),
    ("Interest paid including interest-rate swaps", "InterestPaidFinancing", True),
    # Each is already the cash effect: a fall in inventories is cash in.
    ("Decrease (increase) in inventories", "InventoriesCashEffect", False),
    ("Decrease (increase) in trade accounts receivable", "ReceivablesCashEffect", False),
    ("(Decrease) increase in trade accounts payable", "PayablesCashEffect", False),
)
# Each total and the rows that make it, in the statement's order: (total, first, last).
_CASHFLOW_BLOCKS = (
    ("Net cash provided by (used in) operating activities",
     "Income after income taxes", "Changes in other working capital, other noncash items"),
    ("Net cash provided by (used in) investing activities",
     "Cash outflows for additions to property, plant, equipment and intangible assets",
     "Cash inflows from (outflows for) current financial assets"),
    ("Net cash provided by (used in) financing activities",
     "Cash outflows to acquire Bayer AG shares (BayShare)",
     "Cash outflows for the purchase of additional interests in subsidiaries"),
)

# A product line whose name in the table is not the brand the book carries. Gadovist is
# gadobutrol's name outside the US, where it is sold as Gadavist; Ultravist is carried at
# the strength its US label is listed under.
PRODUCT_ALIASES = {
    "gadovist product family": "gadavist",
    "ultravist": "ultravist 150",
}

_BALANCE_DATE = re.compile(r"^Dec\. 31, (\d{4})$")
_FOOTNOTE = re.compile(r"(?<=[A-Za-z)])\d{1,2}$")


# --- the source ------------------------------------------------------------
def source_urls(today: dt.date | None = None) -> list[str]:
    """The workbook addresses to try, newest report first.

    Each annual report has its own address and is published in March, so for most of a
    year the latest report is the previous year's and before it is out the one before.
    """
    year = (today or dt.date.today()).year
    return [URL_TEMPLATE.format(year=y, yy=y % 100) for y in (year - 1, year - 2)]


# --- reading a sheet --------------------------------------------------------
def cells(worksheet) -> list[list]:
    return [[cell.value for cell in row] for row in worksheet.iter_rows()]


def clean(value) -> str:
    """A label as the book compares it: no trademark sign, no footnote marker, one space."""
    if not isinstance(value, str):
        return ""
    text = value.replace("\xa0", " ").replace("™", "")
    text = re.sub(r"\s+", " ", text).strip()
    return _FOOTNOTE.sub("", text).strip()


def _number(value):
    """A money cell. Bayer writes an en dash for nil, and a nil is a zero in a sum."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip() in ("–", "-", "—"):
        return 0.0
    return None


def header(rows: list[list]) -> list:
    """The column header, the row whose first cell is the unit."""
    for row in rows:
        if clean(row[0] if row else None) == "€ million":
            return row
    return []


def year_columns(head: list) -> dict:
    """{year: column} for full-year money columns, headed with a bare year.

    First occurrence only. A quarter is headed "Q4 2025" and is not a bare year.
    """
    out: dict[int, int] = {}
    for index, value in enumerate(head):
        year = None
        if isinstance(value, int) and 1990 <= value <= 2100:
            year = value
        elif isinstance(value, str) and re.fullmatch(r"\d{4}", value.strip()):
            year = int(value.strip())
        if year is not None and year not in out:
            out[year] = index
    return out


def balance_columns(head: list) -> dict:
    """{column: 'YYYY-12-31'} for a statement of financial position."""
    out = {}
    for index, value in enumerate(head):
        match = _BALANCE_DATE.match(clean(value)) if isinstance(value, str) else None
        if match:
            out[index] = f"{match.group(1)}-12-31"
    return out


def _first(rows: list[list], label: str, start: int = 0, stop: int | None = None):
    for row in rows[start:stop]:
        if clean(row[0] if row else None) == label:
            return row
    return None


def _value(row, column):
    return _number(row[column]) if row is not None and column < len(row) else None


# --- the income statement ---------------------------------------------------
def parse_income(rows: list[list]) -> list[dict]:
    years = year_columns(header(rows))
    out = []
    for label, metric, negate in INCOME_METRICS:
        row = _first(rows, label)
        for year, column in sorted(years.items()):
            raw = _value(row, column)
            if raw is None:
                continue
            per_share = metric == "EarningsPerShareDiluted"
            out.append({"metric": metric, "fiscal_year": year,
                        "value": raw if per_share else (-raw if negate else raw) * MILLION,
                        "unit": f"{CURRENCY}/shares" if per_share else CURRENCY,
                        "label": label})
    parts = [_first(rows, label) for label in SGA_LABELS]
    if all(part is not None for part in parts):
        for year, column in sorted(years.items()):
            values = [_value(part, column) for part in parts]
            if None in values:
                continue
            out.append({"metric": "SellingGeneralAndAdministrative", "fiscal_year": year,
                        "value": -sum(values) * MILLION, "unit": CURRENCY,
                        "label": " plus ".join(SGA_LABELS)})
    return out


def _ties(problems, year, name, whole, parts):
    if whole is None or any(p is None for p in parts):
        problems.append(f"{year} {name}: a line it is built from is missing")
        return
    if abs(whole - sum(parts)) > TOLERANCE_M:
        problems.append(f"{year} {name} is {whole:,.0f} against {sum(parts):,.0f} from "
                        f"its lines, {whole - sum(parts):,.0f} apart")


def reconcile_income(rows: list[list]) -> list[str]:
    years = year_columns(header(rows))
    if not years:
        return ["the income statement has no year columns"]
    get = lambda label, column: _value(_first(rows, label), column)
    problems: list[str] = []
    for year, c in sorted(years.items()):
        _ties(problems, year, "gross profit", get("Gross profit", c),
              [get("Net sales", c), get("Cost of goods sold", c)])
        _ties(problems, year, "EBIT", get("EBIT", c),
              [get("Gross profit", c), get("Selling expenses", c),
               get("Research and development expenses", c),
               get("General administration expenses", c),
               get("Other operating income", c), get("Other operating expenses", c)])
        _ties(problems, year, "financial result", get("Financial result", c),
              [get("Equity-method income (loss)", c), get("Financial income", c),
               get("Financial expenses", c)])
        _ties(problems, year, "income before income taxes",
              get("Income before income taxes", c),
              [get("EBIT", c), get("Financial result", c)])
        _ties(problems, year, "income after income taxes",
              get("Income after income taxes", c),
              [get("Income before income taxes", c), get("Income taxes", c)])
        _ties(problems, year, "the split of income after taxes",
              get("Income after income taxes", c),
              [get("of which attributable to noncontrolling interest", c),
               get("of which attributable to Bayer AG stockholders (net income)", c)])
    return problems


# --- the statement of financial position ------------------------------------
def sections(rows: list[list]) -> dict:
    """{heading: (first row, total row)} for each block of the balance sheet.

    A block runs from its heading to its total, the first row after the heading with no
    label and a number in it.
    """
    out = {}
    for heading in SECTIONS:
        start = next((i for i, row in enumerate(rows)
                      if clean(row[0] if row else None) == heading), None)
        if start is None:
            continue
        total = next((i for i in range(start + 1, len(rows))
                      if not clean(rows[i][0] if rows[i] else None)
                      and any(_number(v) is not None for v in rows[i][1:])), None)
        if total is not None:
            out[heading] = (start + 1, total)
    return out


def parse_balance(rows: list[list]) -> list[dict]:
    dates = balance_columns(header(rows))
    blocks = sections(rows)
    out = []

    def add(metric, column, value, label):
        if value is not None:
            out.append({"metric": metric, "fiscal_year": int(dates[column][:4]),
                        "period_end": dates[column], "value": value * MILLION,
                        "unit": CURRENCY, "label": label})

    for heading, label, metric in BALANCE_METRICS:
        if heading not in blocks:
            continue
        first, last = blocks[heading]
        row = _first(rows, label, first, last)
        for column in dates:
            add(metric, column, _value(row, column), f"{label} ({heading.lower()})")
    total_assets = _first(rows, "Total assets")
    for column in dates:
        add("Assets", column, _value(total_assets, column), "Total assets")
        for heading, metric in (("Current assets", "TotalCurrentAssets"),
                                ("Current liabilities", "TotalCurrentLiabilities"),
                                ("Equity", "StockholdersEquity")):
            if heading in blocks:
                add(metric, column, _value(rows[blocks[heading][1]], column),
                    f"{heading} total, including the noncontrolling interest"
                    if heading == "Equity" else f"{heading} total")
        liabilities = [_value(rows[blocks[h][1]], column)
                       for h in ("Noncurrent liabilities", "Current liabilities")
                       if h in blocks]
        if len(liabilities) == 2 and None not in liabilities:
            add("Liabilities", column, sum(liabilities),
                "Noncurrent plus current liabilities")
        # The book asks for one debt figure and the sheet splits it by maturity, under the
        # same label in two sections.
        debt = []
        for heading in ("Noncurrent liabilities", "Current liabilities"):
            if heading in blocks:
                debt.append(_value(_first(rows, "Financial liabilities", *blocks[heading]),
                                   column))
        if len(debt) == 2 and None not in debt:
            add("TotalDebt", column, sum(debt),
                "Financial liabilities, noncurrent plus current")
    return out


def reconcile_balance(rows: list[list]) -> list[str]:
    dates = balance_columns(header(rows))
    blocks = sections(rows)
    problems = [f"the balance sheet no longer carries {h!r}" for h in SECTIONS
                if h not in blocks]
    if problems or not dates:
        return problems or ["the balance sheet has no year-end columns"]
    for column, date in sorted(dates.items()):
        totals = {}
        for heading, (first, last) in blocks.items():
            lines = [_value(row, column) for row in rows[first:last]
                     if clean(row[0] if row else None)
                     and _value(row, column) is not None
                     # A subtotal inside a block is a line of its own lines, not another.
                     and not clean(row[0]).startswith("Equity attributable to Bayer")]
            whole = _value(rows[last], column)
            totals[heading] = whole
            if heading == "Equity":
                lines = [_value(_first(rows, label, first, last), column) for label in
                         ("Equity attributable to Bayer AG stockholders",
                          "Equity attributable to noncontrolling interest")]
            _ties(problems, date, heading.lower(), whole, lines)
        assets = _value(_first(rows, "Total assets"), column)
        _ties(problems, date, "total assets", assets,
              [totals["Noncurrent assets"], totals["Current assets"]])
        _ties(problems, date, "total equity and liabilities",
              _value(_first(rows, "Total equity and liabilities"), column),
              [totals["Equity"], totals["Noncurrent liabilities"],
               totals["Current liabilities"]])
        if assets is not None:
            _ties(problems, date, "the two sides of the balance sheet", assets,
                  [_value(_first(rows, "Total equity and liabilities"), column)])
    return problems


# --- the cash flow statement -------------------------------------------------
def parse_cashflow(rows: list[list]) -> list[dict]:
    years = year_columns(header(rows))
    out = []
    for label, metric, negate in CASHFLOW_METRICS:
        row = _first(rows, label)
        for year, column in sorted(years.items()):
            raw = _value(row, column)
            if raw is None:
                continue
            out.append({"metric": metric, "fiscal_year": year,
                        "value": (-raw if negate else raw) * MILLION, "unit": CURRENCY,
                        "label": label})
    return out


def _index(rows, label):
    return next((i for i, row in enumerate(rows)
                 if clean(row[0] if row else None) == label), None)


def reconcile_cashflow(rows: list[list]) -> list[str]:
    years = year_columns(header(rows))
    if not years:
        return ["the cash flow statement has no year columns"]
    problems: list[str] = []
    for total, first, last in _CASHFLOW_BLOCKS:
        at = [_index(rows, name) for name in (total, first, last)]
        if None in at:
            problems.append(f"the cash flow statement no longer carries {total!r} "
                            f"with the lines it is built from")
            continue
        for year, c in sorted(years.items()):
            _ties(problems, year, total.lower(), _value(rows[at[0]], c),
                  [_value(row, c) or 0.0 for row in rows[at[1]:at[2] + 1]])
    for year, c in sorted(years.items()):
        _ties(problems, year, "the change in cash from business activities",
              _value(_first(rows, "Change in cash and cash equivalents due to business "
                                  "activities"), c),
              [_value(_first(rows, total), c) for total, _, _ in _CASHFLOW_BLOCKS])
    start = _index(rows, "Cash and cash equivalents at beginning of year")
    end = _index(rows, "Cash and cash equivalents at end of year")
    if start is None or end is None:
        problems.append("the cash flow statement no longer carries the cash balances")
        return problems
    for year, c in sorted(years.items()):
        _ties(problems, year, "the year's movement in cash", _value(rows[end], c),
              [_value(row, c) or 0.0 for row in rows[start:end]
               if clean(row[0] if row else None) != ""]
              + [_value(_first(rows, "Change in cash and cash equivalents due to "
                                     "business activities"), c) or 0.0])
    return problems


# --- products and the share count --------------------------------------------
def parse_products(rows: list[list]) -> tuple[list[dict], dict]:
    """The best-selling products for each full year, and the table's own total."""
    years = year_columns(header(rows))
    head = header(rows)
    begin = next((i for i, row in enumerate(rows) if row is head), None)
    out, total = [], {}
    if begin is None:
        return out, total
    for row in rows[begin + 1:]:
        label = clean(row[0] if row else None)
        if not label:
            continue
        if label == "Total best-selling products":
            total = {y: _value(row, c) * MILLION for y, c in years.items()
                     if _value(row, c) is not None}
            break
        for year, column in sorted(years.items()):
            value = _value(row, column)
            if value is not None:
                out.append({"product": label, "region": None, "fiscal_year": year,
                            "value": value * MILLION, "unit": CURRENCY})
    return out, total


def division_sales(rows: list[list]) -> dict:
    years = year_columns(header(rows))
    row = _first(rows, "Sales")
    return {y: _value(row, c) * MILLION for y, c in years.items()
            if _value(row, c) is not None}


def reconcile_products(products: list[dict], total: dict, division: dict) -> list[str]:
    if not total:
        return ["the product table no longer carries its total"]
    problems = []
    for year, whole in sorted(total.items()):
        summed = sum(r["value"] for r in products if r["fiscal_year"] == year)
        if abs(summed - whole) > TOLERANCE_M * MILLION:
            problems.append(f"{year} best-selling products sum to {summed / MILLION:,.0f} "
                            f"against the table's {whole / MILLION:,.0f}")
        if year in division and whole > division[year] + TOLERANCE_M * MILLION:
            problems.append(f"{year} best-selling products of {whole / MILLION:,.0f} exceed "
                            f"the division's sales of {division[year] / MILLION:,.0f}")
    return problems


def shares(rows: list[list]) -> dict:
    """{year: weighted average share count}, as stated beside core earnings per share.

    Bayer has no dilutive instrument outstanding, so its diluted earnings per share equal
    its basic ones and this count is the diluted count too.
    """
    years = year_columns(header(rows))
    row = _first(rows, "Weighted average number of shares")
    return {y: _value(row, c) * MILLION for y, c in years.items()
            if _value(row, c) is not None}


# --- the whole book ------------------------------------------------------------
def read_book(book) -> tuple[list[dict], list[str]]:
    """Every record this workbook gives the book, and what failed. A statement that does
    not tie writes nothing, and products that do not tie write nothing."""
    missing = [name for name in SHEETS if name not in book.sheetnames]
    if missing:
        return [], [f"the workbook no longer carries {', '.join(missing)}, so nothing was "
                    f"written: check the sheet names in bayer.py"]
    income = cells(book[INCOME_SHEET])
    balance = cells(book[BALANCE_SHEET])
    cashflow = cells(book[CASHFLOW_SHEET])
    notes = reconcile_income(income) + reconcile_balance(balance) + reconcile_cashflow(cashflow)
    records: list[dict] = []
    if notes:
        notes.append("a Bayer statement did not tie, so no statement row was written")
    else:
        records += [{**r, "kind": "income"} for r in parse_income(income)]
        records += [{**r, "kind": "balance"} for r in parse_balance(balance)]
        records += [{**r, "kind": "cashflow"} for r in parse_cashflow(cashflow)]
        for year, count in sorted(shares(cells(book[SHARES_SHEET])).items()):
            records.append({"kind": "income", "metric": "WeightedAverageDilutedShares",
                            "fiscal_year": year, "value": count, "unit": "shares",
                            "label": "weighted average number of shares, core earnings "
                                     "per share table"})
    products, total = parse_products(cells(book[PRODUCT_SHEET]))
    product_notes = reconcile_products(products, total,
                                       division_sales(cells(book[DIVISION_SHEET])))
    if product_notes:
        notes += product_notes + ["the product table did not tie, so no product revenue "
                                  "was written"]
    else:
        records += [{**r, "kind": "product"} for r in products]
    return records, notes
