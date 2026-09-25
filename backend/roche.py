"""Roche's own financial data workbook, the statement a non-SEC filer still publishes.

Roche and Bayer are in this book's universe and neither files with the SEC, so
``financials_edgar`` cannot reach them and neither carried a single financial row. That is
not a small gap: Roche has 101 assets, 46 of them marketed, and without a cost structure,
a tax rate, a debt weight or a share count none of them can be valued at all, however well
its uptake is researched.

Roche publishes the answer itself. Its investor relations site carries a "Finance
Information Tool" whose first download is a workbook of group financial data, meant for
exactly this, free and without a login:

    https://assets.roche.com/f/176343/x/bb0cb9f7bc/roche-group-financial-data.xlsx

It holds the IFRS income statement, the consolidated balance sheet, and per-product sales
both globally and split by region, half-yearly and by full year. That last sheet is better
than what most SEC filers disclose, which give a handful of named products and a residual.

This is the pure half: a loaded workbook in, records out. The download and the database
write live in ``fetchers/financials_ir.py``.

THE SHEET IS A HUMAN DOCUMENT AND IS READ AS ONE. Three things about it decide this parser.

A label is not unique. "Amortisation of intangible assets" appears four times, once under
cost of sales, once under research and development and twice in the cash reconciliation,
and "IFRS operating profit" appears twice because the sheet restates it to start the
below-the-line block. So a wanted label takes the FIRST row that carries it, in document
order, which is the statement's own order.

A year appears twice in the header. Columns 11 and 12 are "Year 2026" and "Year 2025" in
millions of francs; columns 21 and 22 repeat the years for a block of growth percentages.
Taking the last match reads 16.04 as though it were the group's sales. Only the first
occurrence of each year is a money column.

A cost is negative. The sheet writes cost of sales as -16,645 the way a statement does,
while this book stores every charge positive, as the EDGAR fetcher does from us-gaap. The
sign is flipped on the way in, per metric, rather than by taking an absolute value, so a
line that legitimately changes sign is not silently made positive.

WHAT MAKES IT SAFE TO PARSE A SPREADSHEET AT ALL. Every subtotal in the sheet is the sum of
the lines above it, so the parse checks itself: cost of sales against its six components,
selling and administration against its four, operating profit against the whole block, and
net income against profit before taxes less tax. ``reconcile`` returns what failed, and the
fetcher refuses to write a year that does not tie rather than storing a figure it cannot
stand behind. When Roche moves a row, that is how it will be found.
"""

from __future__ import annotations

import re

SOURCE_URL = ("https://assets.roche.com/f/176343/x/bb0cb9f7bc/"
              "roche-group-financial-data.xlsx")
CURRENCY = "CHF"
INCOME_SHEET = "Group IFRS CHF"
BALANCE_SHEET = "Group Balance Sheet"
PRODUCT_SHEET = "P Sales Regions CHF"

MILLION = 1_000_000.0

# A "Year 2025" header, as distinct from the "H1 2025" and "Q1 2025" columns beside it.
_YEAR_HEADER = re.compile(r"^Year\s+(\d{4})$")

# The statement's own labels, mapped to the metric vocabulary the rest of the book already
# uses (see the EDGAR fetcher). ``negate`` is True where the sheet writes the line as a
# charge and this book stores charges positive.
INCOME_METRICS = (
    ("Sales 3rd", "Revenues", False),
    ("Cost of sales", "CostOfRevenue", True),
    ("Research and development", "ResearchAndDevelopmentExpense", True),
    ("Selling, general and administration", "SellingGeneralAndAdministrative", True),
    ("Other operating income and expense", "OtherOperatingIncome", False),
    ("Other revenue", "OtherRevenue", False),
    ("IFRS operating profit", "OperatingIncomeLoss", False),
    ("Financing costs", "FinancingCosts", True),
    ("IFRS profit before taxes", "IncomeBeforeTax", False),
    ("Income taxes", "IncomeTaxExpense", True),
    ("IFRS net income", "NetIncomeLoss", False),
    ("Roche shareholders", "NetIncomeAttributableToParent", False),
    ("Non-controlling interests", "NetIncomeAttributableToNci", False),
    ("Investments in property, plant and equipment", "CapitalExpenditure", True),
    ("Operating free cash flow", "OperatingFreeCashFlow", False),
    ("Free cash flow", "FreeCashFlow", False),
)

# Diluted earnings per share sits under its own heading, labelled by the entity it is for.
EPS_LABEL = "Group (CHF)"
EPS_METRIC = "EarningsPerShareDiluted"

BALANCE_METRICS = (
    ("Total assets", "Assets", False),
    ("Total liabilities", "Liabilities", True),
    ("Total net assets", "StockholdersEquity", False),
    ("Long-term debt", "LongTermDebt", True),
    ("Short-term debt", "ShortTermDebt", True),
    ("Inventories", "Inventory", False),
    ("Accounts receivable", "AccountsReceivable", False),
    ("Accounts payable", "AccountsPayable", True),
    ("Cash and cash equivalents", "CashAndEquivalents", False),
    ("Marketable securities", "ShortTermInvestments", False),
    ("Goodwill", "Goodwill", False),
    ("Intangible assets", "IntangibleAssets", False),
    ("Property, plant and equipment", "PropertyPlantAndEquipmentNet", False),
    ("Total current assets", "TotalCurrentAssets", False),
    ("Total current liabilities", "TotalCurrentLiabilities", True),
)

# The components each subtotal must equal, so a moved row is caught rather than stored.
_RECONCILE = (
    ("Cost of sales",
     ("Manufacturing cost of goods sold and period costs", "Royalty expenses",
      "Collaboration and profit-sharing agreements", "Amortisation of intangible assets",
      "Impairment of property, plant and equipment and right-of-use assets",
      "Impairment of intangible assets")),
    ("Selling, general and administration",
     ("Marketing and distribution", "Administration", "Business taxes and capital taxes",
      "Other general items - Selling, general and administration")),
)

# How far two figures that should be equal may sit apart. The sheet is whole millions, so
# a rounded subtotal can differ from the sum of its rounded parts by a franc or two.
TOLERANCE_M = 3.0


def cells(worksheet) -> list[list]:
    """A worksheet as a list of rows of values. Read once, because a read-only sheet
    cannot be iterated twice and the second pass comes back empty."""
    return [[cell.value for cell in row] for row in worksheet.iter_rows()]


def year_columns(header: list) -> dict:
    """{year: column index} for the full-year money columns.

    Only the first occurrence of a year counts. The header repeats the years further right
    for a block of growth percentages, and reading those gives a group with sales of 1.
    """
    out: dict[int, int] = {}
    for index, value in enumerate(header):
        if not isinstance(value, str):
            continue
        match = _YEAR_HEADER.match(value.strip())
        if match and int(match.group(1)) not in out:
            out[int(match.group(1))] = index
    return out


def sales_year_columns(header: list) -> dict:
    """{year: column index} for a sales sheet, which heads its full-year column with a bare
    year rather than "Year 2025".

    Same first-occurrence rule and the same reason: the sheet repeats the years further
    right for a block of growth rates, so the last match reads Ocrevus' 4% growth as CHF
    4 million of sales. A header can be the number 2025 or the text "2025" depending on how
    the cell was typed, so both are read.
    """
    out: dict[int, int] = {}
    for index, value in enumerate(header):
        year = None
        if isinstance(value, int) and 1990 <= value <= 2100:
            year = value
        elif isinstance(value, str):
            text = value.strip()
            if re.fullmatch(r"\d{4}", text) and 1990 <= int(text) <= 2100:
                year = int(text)
            else:
                match = _YEAR_HEADER.match(text)
                year = int(match.group(1)) if match else None
        if year is not None and year not in out:
            out[year] = index
    return out


def _label(row: list) -> str:
    value = row[0] if row else None
    return value.strip() if isinstance(value, str) else ""


def _first(rows: list[list], label: str) -> list | None:
    """The first row carrying this label, which is the statement's own order."""
    for row in rows:
        if _label(row) == label:
            return row
    return None


def _number(value):
    return float(value) if isinstance(value, (int, float)) else None


def parse_income(rows: list[list]) -> list[dict]:
    """One record per metric per full year, in units of francs."""
    years = year_columns(rows[0] if rows else [])
    out = []
    for label, metric, negate in INCOME_METRICS:
        row = _first(rows, label)
        if row is None:
            continue
        for year, column in sorted(years.items()):
            raw = _number(row[column]) if column < len(row) else None
            if raw is None:
                continue                    # a year Roche has not reported yet
            out.append({
                "metric": metric, "fiscal_year": year,
                "value": (-raw if negate else raw) * MILLION,
                "unit": CURRENCY, "label": label,
            })
    eps = _first(rows, EPS_LABEL)
    if eps is not None:
        for year, column in sorted(years.items()):
            raw = _number(eps[column]) if column < len(eps) else None
            if raw is not None:
                out.append({"metric": EPS_METRIC, "fiscal_year": year, "value": raw,
                            "unit": f"{CURRENCY}/shares", "label": EPS_LABEL})
    return out


def balance_dates(rows: list[list]) -> dict:
    """{column index: 'YYYY-MM-DD'} for the balance sheet's own column headings.

    The sheet heads its columns with a day and a year on two rows, "31 December" over
    2025. openpyxl reads the year as a number, so a 2025 comes back as 2025 and is
    formatted, not parsed.
    """
    day_row = next((row for row in rows
                    if any(isinstance(c, str) and "December" in c for c in row)), None)
    if day_row is None:
        return {}
    year_row = rows[rows.index(day_row) + 1] if rows.index(day_row) + 1 < len(rows) else []
    months = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
              "July": 7, "August": 8, "September": 9, "October": 10, "November": 11,
              "December": 12}
    out = {}
    for index, value in enumerate(day_row):
        if not isinstance(value, str):
            continue
        match = re.match(r"^(\d{1,2})\s+([A-Za-z]+)$", value.strip())
        if not match or match.group(2) not in months:
            continue
        year = year_row[index] if index < len(year_row) else None
        if not isinstance(year, (int, float)):
            continue
        out[index] = f"{int(year):04d}-{months[match.group(2)]:02d}-{int(match.group(1)):02d}"
    return out


def parse_balance(rows: list[list]) -> list[dict]:
    """One record per metric per balance sheet date, in units of francs.

    Only the year ends are kept. A half-year balance sheet is a real figure and is not
    what a debt weight or a working capital ratio in this book is built from, and mixing
    the two under one fiscal year would make which one was stored depend on column order.
    """
    dates = {index: date for index, date in balance_dates(rows).items()
             if date.endswith("-12-31")}
    out = []
    for label, metric, negate in BALANCE_METRICS:
        row = _first(rows, label)
        if row is None:
            continue
        for index, date in sorted(dates.items()):
            raw = _number(row[index]) if index < len(row) else None
            if raw is None:
                continue
            out.append({"metric": metric, "fiscal_year": int(date[:4]),
                        "period_end": date,
                        "value": (-raw if negate else raw) * MILLION,
                        "unit": CURRENCY, "label": label})
    # The book asks for one debt figure, and the sheet splits it by maturity.
    by_year: dict[int, dict] = {}
    for record in out:
        if record["metric"] in ("LongTermDebt", "ShortTermDebt"):
            held = by_year.setdefault(record["fiscal_year"],
                                      {"period_end": record["period_end"], "total": 0.0})
            held["total"] += record["value"]
    for year, held in sorted(by_year.items()):
        out.append({"metric": "TotalDebt", "fiscal_year": year,
                    "period_end": held["period_end"], "value": held["total"],
                    "unit": CURRENCY, "label": "Long-term debt plus short-term debt"})
    return out


def parse_products(rows: list[list]) -> list[dict]:
    """Per-product sales for each full year, global and by region.

    The sheet lists a product and then indents its regions beneath it as "thereof United
    States", so a region belongs to the last product seen.

    IT CARRIES TWO BLOCKS AND ONLY THE FIRST IS A YEAR. Rows 2 to 131 are year-to-date, so
    their "2025" column is the full year and the 26 products in it sum to 47,669, which is
    the Pharmaceuticals Division's 2025 sales exactly. After three blank rows the same 26
    products repeat with quarterly figures, where Ocrevus reads 1,820 rather than 7,010.
    Reading both blocks double counted the division by 25% and gave every product two
    different annual figures. So the parse stops at the first blank row after it has started.
    """
    years = sales_year_columns(rows[1] if len(rows) > 1 else [])
    if not years:
        years = sales_year_columns(rows[0] if rows else [])
    out, product, started = [], None, False
    for row in rows:
        label = _label(row)
        if label.lower().startswith("pharma products"):
            continue
        if not label:
            if started:
                break                  # the quarterly block begins here
            continue
        thereof = label.lower().startswith("thereof")
        region = label.split(None, 1)[1].strip() if thereof and " " in label else None
        if not thereof:
            product, region = label, None
        if product is None:
            continue
        for year, column in sorted(years.items()):
            value = _number(row[column]) if column < len(row) else None
            if value is None:
                continue
            started = True
            out.append({"product": product, "region": region, "fiscal_year": year,
                        "value": value * MILLION, "unit": CURRENCY})
    return out


def growth_year_columns(header: list) -> dict:
    """{year: column index} for the SECOND block on a sales sheet, the growth rates.

    The sheet puts money under 2025 at column 4 and the CHF growth rate for the same year
    under 2025 again at column 13. The workbook only ever carries the current year and the
    part-year after it, so a prior-year figure to compute growth from does not exist in it:
    the published rate is the only route, and it is a published figure rather than a
    derived one, which is better evidence than a subtraction would be.
    """
    seen: dict[int, list[int]] = {}
    for index, value in enumerate(header):
        year = None
        if isinstance(value, int) and 1990 <= value <= 2100:
            year = value
        elif isinstance(value, str):
            text = value.strip()
            if re.fullmatch(r"\d{4}", text) and 1990 <= int(text) <= 2100:
                year = int(text)
        if year is not None:
            seen.setdefault(year, []).append(index)
    return {year: columns[1] for year, columns in seen.items() if len(columns) > 1}


def parse_product_growth(rows: list[list]) -> list[dict]:
    """Each product's published annual growth rate in reported francs.

    Same two-block shape as the sales, and the same stop: only the year-to-date block is a
    year. A rate of exactly zero is kept, because a product that did not grow is a fact and
    dropping it would leave the seed to guess.
    """
    years = growth_year_columns(rows[1] if len(rows) > 1 else [])
    out, product, started = [], None, False
    for row in rows:
        label = _label(row)
        if label.lower().startswith("pharma products"):
            continue
        if not label:
            if started:
                break
            continue
        if label.lower().startswith("thereof"):
            continue                       # a region's growth is not asked for here
        product = label
        for year, column in sorted(years.items()):
            value = _number(row[column]) if column < len(row) else None
            if value is None:
                continue
            started = True
            out.append({"product": product, "fiscal_year": year, "growth": value})
    return out


def division_sales(rows: list[list], division: str = "Pharmaceuticals Division") -> dict:
    """{year: sales} for a division, from the group sales sheet, in units of francs."""
    years = sales_year_columns(rows[1] if len(rows) > 1 else [])
    row = next((r for r in rows if _label(r).startswith(division)), None)
    if row is None:
        return {}
    out = {}
    for year, column in sorted(years.items()):
        value = _number(row[column]) if column < len(row) else None
        if value is not None:
            out[year] = value * MILLION
    return out


def reconcile_products(products: list[dict], division: dict) -> list[str]:
    """What does not tie between the per-product lines and the division total.

    This is the check that catches the two-block trap, because reading the quarterly block
    as well made the products sum to 59,783 against a division of 47,669. It also catches a
    product Roche adds or renames, since "Other Products" is a residual and the sum only
    holds when every named line is counted once.
    """
    problems = []
    for year, total in sorted(division.items()):
        summed = sum(r["value"] for r in products
                     if r["region"] is None and r["fiscal_year"] == year)
        if not summed:
            continue
        if abs(summed - total) > TOLERANCE_M * MILLION:
            problems.append(
                f"{year} per-product sales sum to {summed / MILLION:,.0f} against the "
                f"division's {total / MILLION:,.0f}, {(summed - total) / MILLION:,.0f} apart")
    return problems


def reconcile(rows: list[list]) -> list[str]:
    """What does not tie, in millions, per full year. Empty when the sheet parses clean."""
    years = year_columns(rows[0] if rows else [])
    problems = []
    for subtotal, components in _RECONCILE:
        head = _first(rows, subtotal)
        if head is None:
            problems.append(f"{subtotal!r}: the sheet no longer carries this row")
            continue
        parts = []
        for name in components:
            row = _first(rows, name)
            if row is None:
                problems.append(f"{subtotal!r}: component {name!r} is missing")
            else:
                parts.append(row)
        for year, column in sorted(years.items()):
            whole = _number(head[column]) if column < len(head) else None
            if whole is None:
                continue
            total = sum(_number(p[column]) or 0.0 for p in parts if column < len(p))
            if abs(whole - total) > TOLERANCE_M:
                problems.append(
                    f"{year} {subtotal!r} is {whole:,.0f} against {total:,.0f} from its "
                    f"{len(parts)} components, {whole - total:,.0f} apart")
    # Net income has to be profit before taxes less the tax charge.
    for year, column in sorted(years.items()):
        trio = [_first(rows, n) for n in ("IFRS profit before taxes", "Income taxes",
                                         "IFRS net income")]
        if any(row is None for row in trio):
            problems.append("the sheet no longer carries the tax block")
            break
        before, tax, net = (_number(row[column]) if column < len(row) else None
                            for row in trio)
        if None in (before, tax, net):
            continue
        if abs((before + tax) - net) > TOLERANCE_M:
            problems.append(f"{year} net income is {net:,.0f} against {before + tax:,.0f} "
                            f"from profit before taxes and tax")
    return problems


def shares_from(records: list[dict]) -> dict:
    """{year: diluted share count} from earnings attributable to shareholders over
    diluted earnings per share.

    Roche publishes the per-share figure and not the count, and the count is what a market
    capitalisation and therefore a debt weight needs. Attributable earnings are used rather
    than group net income because the per-share figure is struck on them, so dividing group
    income by it would carry the non-controlling interest into the share count.
    """
    attributable = {r["fiscal_year"]: r["value"] for r in records
                    if r["metric"] == "NetIncomeAttributableToParent"}
    eps = {r["fiscal_year"]: r["value"] for r in records
           if r["metric"] == EPS_METRIC and r["value"]}
    return {year: attributable[year] / eps[year] for year in sorted(attributable)
            if year in eps}


# --- the whole book ------------------------------------------------------------
SALES_SHEET = "Group Sales CHF"
DIVISION = "Pharmaceuticals Division"
NOTE = "Roche Finance Information Tool, group financial data workbook"


def source_urls(today=None) -> list[str]:
    """The workbook's address. Roche keeps one address and replaces the file behind it."""
    return [SOURCE_URL]


def read_book(book) -> tuple[list[dict], list[str]]:
    """Every record this workbook gives the book, and what failed. A statement that does
    not tie writes nothing, and products that do not sum to the division write nothing."""
    income = cells(book[INCOME_SHEET])
    balance = cells(book[BALANCE_SHEET])
    products = cells(book[PRODUCT_SHEET])
    sales = cells(book[SALES_SHEET])
    notes: list[str] = []

    problems = reconcile(income)
    if problems:
        notes.extend(problems)
        notes.append("the income statement did not tie, so no statement row was "
                     "written: check the sheet's labels against roche.py")
        statement = []
    else:
        statement = ([{**r, "kind": "income"} for r in parse_income(income)]
                     + [{**r, "kind": "balance"} for r in parse_balance(balance)])
        for year, count in shares_from(parse_income(income)).items():
            # The metric name the rest of the book reads. forecast_view._diluted_shares
            # looks for WeightedAverageDilutedShares first and otherwise falls back to
            # group net income over earnings per share, which for Roche is wrong by the
            # non-controlling interest: 13,799 / 16.04 is 860.3mm against the true
            # 803.0mm, because the per-share figure is struck on the 12,880mm
            # attributable to shareholders. Writing the count under the name the reader
            # already uses is what keeps that fallback off it.
            statement.append({
                "kind": "income", "metric": "WeightedAverageDilutedShares",
                "fiscal_year": year, "value": count, "unit": "shares",
                "label": "earnings attributable to shareholders over diluted "
                         "earnings per share"})

    product_rows = parse_products(products)
    product_problems = reconcile_products(product_rows, division_sales(sales, DIVISION))
    if product_problems:
        notes.extend(product_problems)
        notes.append("the per-product sales did not sum to the division, so no "
                     "product revenue was written")
        product_rows = []
    return statement + [{**r, "kind": "product"} for r in product_rows], notes
