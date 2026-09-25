"""Bayer's annual report tables: parsing them, and refusing them when they stop tying.

The fixture is Bayer's real published workbook for 2025, cut to the six sheets the reader
uses and otherwise untouched, so the test fails when Bayer moves a row rather than when a
hand-written sample drifts from the source. No network.
"""

import datetime as dt
import io
import pathlib
import urllib.error

import bayer
import db
import openpyxl
import refresh
import seed
from fetchers.financials_esef import FinancialsEsefFetcher
from fetchers.financials_ir import FinancialsIrFetcher

_FIX = pathlib.Path(__file__).resolve().parent / "fixtures"
_BOOK = _FIX / "bayer_annual_report_tables.xlsx"


def _book():
    return openpyxl.load_workbook(_BOOK, data_only=True)


def _sheet(name):
    return bayer.cells(_book()[name])


def _by_metric(records, year=2025):
    return {r["metric"]: r["value"] for r in records if r["fiscal_year"] == year}


# --- the labels ------------------------------------------------------------------
def test_a_label_loses_its_footnote_and_its_trademark_sign():
    assert bayer.clean("EBIT1") == "EBIT"
    assert bayer.clean("CT Fluid Delivery2") == "CT Fluid Delivery"
    assert bayer.clean("Mirena™/Kyleena™/Jaydess™") == "Mirena/Kyleena/Jaydess"
    assert bayer.clean("attributable to Bayer\xa0AG stockholders") == \
        "attributable to Bayer AG stockholders"
    # A year is not a footnote, and a quarter is not a year.
    assert bayer.clean("Q4 2025") == "Q4 2025"
    assert bayer.year_columns(["€ million", "Q4 2024", "Q4 2025", "Reported",
                               "Fx & p adj.", "2024", "2025"]) == {2024: 5, 2025: 6}


# --- the income statement ----------------------------------------------------------
def test_income_statement_parses_to_the_published_figures():
    got = _by_metric(bayer.parse_income(_sheet(bayer.INCOME_SHEET)))
    assert got["Revenues"] == 45_575_000_000
    assert got["CostOfRevenue"] == 18_797_000_000          # stored positive
    assert got["ResearchAndDevelopmentExpense"] == 5_769_000_000
    # Selling 12,549 and general administration 2,160 are one line in the book.
    assert got["SellingGeneralAndAdministrative"] == 14_709_000_000
    assert got["OtherOperatingExpense"] == 9_179_000_000    # mostly litigation, in 2025
    assert got["OperatingIncomeLoss"] == -1_077_000_000
    assert got["IncomeTaxExpense"] == 466_000_000
    assert got["NetIncomeLoss"] == -3_595_000_000
    assert got["NetIncomeAttributableToParent"] == -3_620_000_000
    assert got["EarningsPerShareDiluted"] == -3.68


def test_the_statement_reconciles_as_published():
    assert bayer.reconcile_income(_sheet(bayer.INCOME_SHEET)) == []
    assert bayer.reconcile_balance(_sheet(bayer.BALANCE_SHEET)) == []
    assert bayer.reconcile_cashflow(_sheet(bayer.CASHFLOW_SHEET)) == []


def test_a_moved_income_line_is_refused():
    rows = [list(r) for r in _sheet(bayer.INCOME_SHEET)]
    for row in rows:
        if bayer.clean(row[0]) == "Cost of goods sold":
            row[3] = -17_000                 # the 2025 column
    problems = bayer.reconcile_income(rows)
    assert problems and "gross profit" in problems[0]


# --- the statement of financial position ----------------------------------------------
def test_a_repeated_label_is_read_inside_its_own_section():
    """"Financial liabilities" appears under noncurrent and current liabilities. Read across
    the sheet, the first would be taken twice or the second never, so debt is the two
    together only when each is looked up inside its own block."""
    records = bayer.parse_balance(_sheet(bayer.BALANCE_SHEET))
    debt = {r["fiscal_year"]: r["value"] for r in records if r["metric"] == "TotalDebt"}
    assert debt[2025] == (31_833 + 5_746) * 1_000_000
    assert debt[2024] == (35_498 + 5_313) * 1_000_000
    got = _by_metric(records)
    # Total equity carries the minority, as ifrs-full Equity does for a 20-F filer.
    assert got["StockholdersEquity"] == 26_063_000_000
    assert got["TotalCurrentAssets"] == 32_911_000_000       # an unlabelled subtotal row
    assert got["Liabilities"] == (45_893 + 32_585) * 1_000_000
    assert {r["period_end"] for r in records} == {"2024-12-31", "2025-12-31"}


def test_a_moved_balance_line_is_refused():
    rows = [list(r) for r in _sheet(bayer.BALANCE_SHEET)]
    seen = 0
    for row in rows:
        if bayer.clean(row[0]) == "Financial liabilities":
            seen += 1
            if seen == 2:
                row[3] = 1_000               # the current one, 2025
    problems = bayer.reconcile_balance(rows)
    assert problems and "current liabilities" in problems[0]


# --- the cash flow statement ------------------------------------------------------------
def test_cash_flow_outflows_are_stored_positive_and_interest_sits_under_financing():
    got = _by_metric(bayer.parse_cashflow(_sheet(bayer.CASHFLOW_SHEET)))
    assert got["CashFlowOperating"] == 5_930_000_000
    assert got["CapitalExpenditure"] == 2_487_000_000
    assert got["DividendsPaid"] == 127_000_000
    # Bayer books interest paid in financing, so free cash flow is already struck before it
    # and interest_addback has nothing to add back.
    assert got["InterestPaidFinancing"] == 1_698_000_000
    assert "InterestPaidOperating" not in got
    assert got["ReceivablesCashEffect"] == -852_000_000       # already a cash effect
    # Depreciation is added back with impairment as one line, so it is not written at all.
    assert not any(m.startswith("Depreciation") for m in got)


# --- products and shares --------------------------------------------------------------
def test_the_fifteen_products_sum_to_the_table_and_families_stay_whole():
    products, total = bayer.parse_products(_sheet(bayer.PRODUCT_SHEET))
    division = bayer.division_sales(_sheet(bayer.DIVISION_SHEET))
    assert total[2025] == 15_185_000_000
    assert division[2025] == 17_829_000_000
    assert bayer.reconcile_products(products, total, division) == []
    names = {r["product"] for r in products if r["fiscal_year"] == 2025}
    assert len(names) == 15
    assert "Mirena/Kyleena/Jaydess" in names and "Kovaltry/Jivi" in names


def test_a_dropped_product_is_refused():
    products, total = bayer.parse_products(_sheet(bayer.PRODUCT_SHEET))
    short = [r for r in products if r["product"] != "Kerendia"]
    problems = bayer.reconcile_products(short, total, {})
    assert len(problems) == 2 and "15,185" in problems[1]     # both years, 2024 first


def test_the_share_count_is_the_stated_one_not_one_derived_from_a_loss():
    """Bayer states its weighted average share count beside core earnings per share, so
    nothing is derived. Derived from a two-decimal loss per share it would be 983.7mm, and
    in a year near break-even the quotient would be meaningless."""
    shares = bayer.shares(_sheet(bayer.SHARES_SHEET))
    assert shares[2025] == 982_420_000
    assert round(3_620 / 3.68, 1) == 983.7


# --- the source ----------------------------------------------------------------
def test_the_latest_report_is_tried_first_and_the_one_before_is_the_fall_back():
    urls = bayer.source_urls(dt.date(2026, 9, 25))
    assert urls[0].endswith("/annual-report-2025/en/_assets/downloads/entire-bayer-ar25.xlsx")
    assert urls[1].endswith("/annual-report-2024/en/_assets/downloads/entire-bayer-ar24.xlsx")


def test_a_report_not_yet_published_falls_back_to_the_one_before(monkeypatch):
    calls = []

    class _Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        return _Response(_BOOK.read_bytes())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    fetcher = FinancialsIrFetcher("BAYN", None)
    raw = fetcher.fetch()
    assert len(calls) == 2 and raw[0]["url"] == calls[1]
    assert any("not published yet" in note for note in fetcher._notes)


# --- the write -------------------------------------------------------------------
def _seeded(tmp_path):
    path = tmp_path / "bayer.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    company = conn.execute("SELECT id FROM companies WHERE ticker='BAYN'").fetchone()
    for brand in ("Nubeqa", "Kovaltry", "Jivi", "Gadavist", "Ultravist 150", "Mirena"):
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, ?, 1)", (company["id"], brand))
    conn.commit()
    conn.close()
    return path


def test_upsert_writes_statements_cash_flow_and_products(tmp_path):
    path = _seeded(tmp_path)
    fetcher = FinancialsIrFetcher("BAYN", path)
    result = fetcher.upsert(fetcher.normalise([{"bytes": _BOOK.read_bytes()}]))
    conn = db.get_connection(path)
    try:
        def metric(name):
            row = conn.execute(
                """SELECT f.value FROM financials f JOIN companies c ON c.id = f.company_id
                    WHERE c.ticker='BAYN' AND f.metric=? AND f.fiscal_year=2025""",
                (name,)).fetchone()
            return row["value"] if row else None
        assert metric("Revenues") == 45_575_000_000
        assert metric("CapitalExpenditure") == 2_487_000_000
        assert metric("WeightedAverageDilutedShares") == 982_420_000

        def revenue(brand):
            row = conn.execute(
                """SELECT r.value FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
                    WHERE a.brand_name=? AND r.fiscal_year=2025""", (brand,)).fetchone()
            return row["value"] if row else None
        assert revenue("Nubeqa") == 2_385_000_000
        # Gadovist is gadobutrol's name outside the US, where it is sold as Gadavist.
        assert revenue("Gadavist") == 415_000_000
        assert revenue("Ultravist 150") == 561_000_000
        # A family figure goes whole to the first brand the book carries, never split.
        assert revenue("Kovaltry") == 613_000_000
        assert revenue("Jivi") is None
        # Eylea and Xarelto are Bayer's sales outside the US of molecules the book holds
        # under Regeneron and Johnson & Johnson. They are reported, not attached to a row
        # that is someone else's.
        unmatched = next(note for note in result.notes if "matched no asset" in note)
        assert "Eylea" in unmatched and "Xarelto" in unmatched
    finally:
        conn.close()


def test_bayer_is_routed_to_its_workbook_not_to_the_esef_index(tmp_path):
    """filings.xbrl.org carried no German filer on 2026-09-25, so the ESEF route can only
    report an empty index for Bayer. The workbook is checked first."""
    path = tmp_path / "route.db"
    db.init(path)
    seed.load_companies(path)
    conn = db.get_connection(path)
    try:
        company = conn.execute("SELECT * FROM companies WHERE ticker='BAYN'").fetchone()
    finally:
        conn.close()
    kinds = {type(f) for f in refresh._company_fetchers(company, path)}
    assert FinancialsIrFetcher in kinds
    assert FinancialsEsefFetcher not in kinds

