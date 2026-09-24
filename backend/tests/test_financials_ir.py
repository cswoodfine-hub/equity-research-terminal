"""Roche's own financial data workbook: parsing it, and refusing it when it stops tying.

The fixture is Roche's real published workbook with the sheets this reads and their columns
kept, so the test fails when Roche moves a row rather than when a hand-written sample drifts
from the source. No network.
"""

import pathlib

import db
import openpyxl
import roche
import seed
from fetchers.financials_ir import FinancialsIrFetcher

_FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
_BOOK = _FIX / "roche_group_financial_data.xlsx"


def _sheets():
    book = openpyxl.load_workbook(_BOOK, data_only=True)
    return {
        "income": roche.cells(book[roche.INCOME_SHEET]),
        "balance": roche.cells(book[roche.BALANCE_SHEET]),
        "products": roche.cells(book[roche.PRODUCT_SHEET]),
        "sales": roche.cells(book["Group Sales CHF"]),
    }


# --- the header, where the trap is -----------------------------------------
def test_a_year_column_is_the_first_occurrence_not_the_last():
    """The header carries "Year 2025" twice, once over millions of francs and once over a
    block of growth percentages. Taking the last match read the group's sales as 1."""
    header = _sheets()["income"][0]
    assert roche.year_columns(header) == {2026: 11, 2025: 12}


def test_a_sales_sheet_heads_its_year_with_a_bare_number():
    """The product sheet writes 2025, not "Year 2025", and repeats it for growth rates."""
    header = _sheets()["products"][1]
    assert roche.sales_year_columns(header) == {2025: 4, 2026: 8}


# --- the statement ---------------------------------------------------------
def test_income_statement_parses_to_the_published_figures():
    records = roche.parse_income(_sheets()["income"])
    got = {r["metric"]: r["value"] for r in records if r["fiscal_year"] == 2025}
    assert got["Revenues"] == 61_516_000_000            # Pharma 47,669 + Diagnostics 13,847
    assert got["CostOfRevenue"] == 16_645_000_000       # stored positive, sheet says -16,645
    assert got["ResearchAndDevelopmentExpense"] == 13_352_000_000
    assert got["SellingGeneralAndAdministrative"] == 15_161_000_000
    assert got["OperatingIncomeLoss"] == 18_476_000_000
    assert got["IncomeBeforeTax"] == 16_973_000_000
    assert got["IncomeTaxExpense"] == 3_174_000_000
    assert got["NetIncomeLoss"] == 13_799_000_000
    assert got["NetIncomeAttributableToParent"] == 12_880_000_000
    assert got["EarningsPerShareDiluted"] == 16.04


def test_the_first_label_wins_where_the_sheet_repeats_one():
    """"Amortisation of intangible assets" appears four times and "IFRS operating profit"
    twice. R&D is the IFRS charge of 13,352, not the 12,832 core figure below it."""
    records = roche.parse_income(_sheets()["income"])
    rd = [r for r in records
          if r["metric"] == "ResearchAndDevelopmentExpense" and r["fiscal_year"] == 2025]
    assert len(rd) == 1 and rd[0]["value"] == 13_352_000_000


def test_shares_come_from_attributable_earnings_over_the_per_share_figure():
    """Roche publishes the per-share figure and not the count, and the count is what a
    market capitalisation needs. 12,880 / 16.04 is 803.0 million."""
    shares = roche.shares_from(roche.parse_income(_sheets()["income"]))
    assert round(shares[2025] / 1e6, 1) == 803.0


def test_balance_sheet_keeps_year_ends_and_adds_the_two_debt_maturities():
    records = roche.parse_balance(_sheets()["balance"])
    assert {r["period_end"] for r in records} == {"2025-12-31", "2024-12-31"}
    debt = {r["fiscal_year"]: r["value"] for r in records if r["metric"] == "TotalDebt"}
    assert debt[2025] == 27_430_000_000 + 4_206_000_000
    assert debt[2024] == 30_722_000_000 + 3_932_000_000
    equity = {r["fiscal_year"]: r["value"] for r in records
              if r["metric"] == "StockholdersEquity"}
    assert equity[2025] == 37_880_000_000


# --- the products ---------------------------------------------------------
def test_only_the_year_to_date_block_is_read():
    """The sheet repeats all 26 products below with quarterly figures, where Ocrevus reads
    1,820 rather than 7,010. Reading both gave every product two annual figures."""
    sheets = _sheets()
    products = roche.parse_products(sheets["products"])
    ocrevus = [r for r in products if r["product"] == "Ocrevus" and r["fiscal_year"] == 2025]
    assert len(ocrevus) == 5                       # global plus four regions, once
    assert next(r["value"] for r in ocrevus if r["region"] is None) == 7_010_000_000
    assert next(r["value"] for r in ocrevus if r["region"] == "United States") == 4_874_000_000


def test_the_products_sum_to_the_division_and_that_is_the_check():
    sheets = _sheets()
    products = roche.parse_products(sheets["products"])
    division = roche.division_sales(sheets["sales"])
    assert division[2025] == 47_669_000_000
    assert roche.reconcile_products(products, division) == []
    globals_2025 = [r for r in products
                    if r["region"] is None and r["fiscal_year"] == 2025]
    assert sum(r["value"] for r in globals_2025) == 47_669_000_000
    assert len(globals_2025) == 26


def test_reading_the_quarterly_block_too_would_be_caught():
    """The guard that matters: if the block break is ever missed, the products stop summing
    to the division and nothing is written."""
    sheets = _sheets()
    division = roche.division_sales(sheets["sales"])
    both_blocks = []
    years = roche.sales_year_columns(sheets["products"][1])
    product = None
    for row in sheets["products"]:
        label = row[0].strip() if isinstance(row[0], str) else ""
        if not label or label.lower().startswith("pharma products"):
            continue
        if not label.lower().startswith("thereof"):
            product = label
            for year, column in years.items():
                value = row[column] if column < len(row) else None
                if isinstance(value, (int, float)):
                    both_blocks.append({"product": product, "region": None,
                                        "fiscal_year": year,
                                        "value": value * roche.MILLION})
    problems = roche.reconcile_products(both_blocks, division)
    assert problems and "47,669" in problems[0]


# --- the statement reconciliation -----------------------------------------
def test_the_statement_reconciles_as_published():
    assert roche.reconcile(_sheets()["income"]) == []


def test_a_moved_subtotal_is_refused_rather_than_stored():
    """A spreadsheet is a human document and Roche will move a row in it. A figure that is
    wrong is worse than one that is missing, because the missing one shows in the view."""
    rows = [list(r) for r in _sheets()["income"]]
    for row in rows:
        if isinstance(row[0], str) and row[0].strip() == "Cost of sales":
            row[12] = -99_999            # the year 2025 money column
            break
    problems = roche.reconcile(rows)
    assert problems and "Cost of sales" in problems[0]


# --- the write ------------------------------------------------------------
def _seeded(tmp_path):
    path = tmp_path / "ir.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    company = conn.execute("SELECT id FROM companies WHERE ticker='ROG'").fetchone()
    for brand in ("Ocrevus", "Hemlibra", "Vabysmo"):
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, ?, 1)", (company["id"], brand))
    conn.commit()
    conn.close()
    return path


def test_upsert_writes_statements_product_revenue_and_regions(tmp_path):
    path = _seeded(tmp_path)
    fetcher = FinancialsIrFetcher("ROG", path)
    rows = fetcher.normalise([{"bytes": _BOOK.read_bytes()}])
    result = fetcher.upsert(rows)
    conn = db.get_connection(path)
    try:
        revenue = conn.execute(
            """SELECT f.value FROM financials f JOIN companies c ON c.id = f.company_id
                WHERE c.ticker='ROG' AND f.metric='Revenues' AND f.fiscal_year=2025"""
        ).fetchone()
        assert revenue["value"] == 61_516_000_000
        ocrevus = conn.execute(
            """SELECT r.value FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
                WHERE a.brand_name='Ocrevus' AND r.fiscal_year=2025"""
        ).fetchone()
        assert ocrevus["value"] == 7_010_000_000
        us = conn.execute(
            """SELECT r.value, r.region FROM asset_revenue_regions r
                 JOIN assets a ON a.id = r.asset_id
                WHERE a.brand_name='Ocrevus' AND r.fiscal_year=2025 AND r.region='US'"""
        ).fetchone()
        assert us["value"] == 4_874_000_000
        # Only the three seeded brands match, and the rest are reported rather than dropped
        # silently, because an unmatched product is revenue the book does not hold.
        assert any("matched no asset" in note for note in result.notes)
    finally:
        conn.close()


def test_upsert_is_idempotent(tmp_path):
    path = _seeded(tmp_path)
    fetcher = FinancialsIrFetcher("ROG", path)
    rows = fetcher.normalise([{"bytes": _BOOK.read_bytes()}])
    fetcher.upsert(rows)
    fetcher.upsert(rows)
    conn = db.get_connection(path)
    try:
        assert conn.execute(
            """SELECT COUNT(*) FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
                WHERE a.brand_name='Ocrevus'""").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_share_count_is_written_under_the_name_the_book_reads(tmp_path):
    """forecast_view._diluted_shares looks for WeightedAverageDilutedShares and otherwise
    falls back to group net income over earnings per share. For Roche that fallback is wrong
    by the non-controlling interest, 13,799 / 16.04 = 860.3mm against the true 803.0mm,
    because the per-share figure is struck on the 12,880mm attributable to shareholders.
    Roche is the only filer in this universe with a material minority."""
    path = _seeded(tmp_path)
    fetcher = FinancialsIrFetcher("ROG", path)
    fetcher.upsert(fetcher.normalise([{"bytes": _BOOK.read_bytes()}]))
    conn = db.get_connection(path)
    try:
        row = conn.execute(
            """SELECT f.value FROM financials f JOIN companies c ON c.id = f.company_id
                WHERE c.ticker='ROG' AND f.metric='WeightedAverageDilutedShares'
                  AND f.fiscal_year=2025""").fetchone()
        assert round(row["value"] / 1e6, 1) == 803.0
        # The fallback would have given 860.3mm, so the wrong branch is visibly different.
        assert round(13_799_000_000 / 16.04 / 1e6, 1) == 860.3
        # The reader takes this branch rather than the fallback, which is the whole point.
        # It then divides by the depositary ratio and the franc rate, neither of which this
        # temporary database carries, so the divisor itself is checked against the live book.
        company = conn.execute("SELECT id FROM companies WHERE ticker='ROG'").fetchone()
        assert conn.execute(
            """SELECT COUNT(*) FROM financials f JOIN companies c ON c.id = f.company_id
                WHERE c.ticker='ROG' AND f.metric='WeightedAverageDilutedShares'"""
        ).fetchone()[0] >= 1
    finally:
        conn.close()


def test_the_published_growth_rate_is_read_from_the_second_year_block():
    """The workbook carries only the current year, so there is no prior-year figure to
    derive growth from. Roche publishes the rate beside the money, at a second occurrence of
    the same year header."""
    sheets = _sheets()
    assert roche.growth_year_columns(sheets["products"][1]) == {2025: 13, 2026: 17}
    growth = {r["product"]: r["growth"] for r in roche.parse_product_growth(sheets["products"])
              if r["fiscal_year"] == 2025}
    assert growth["Ocrevus"] == 0.04
    assert growth["Phesgo"] == 0.40
    assert growth["Herceptin"] == -0.26
    # Itovebi launched in October 2024, so Roche publishes no rate for it and none is made up.
    assert "Itovebi" not in growth
