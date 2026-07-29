"""Cash runway for clinical-stage biotech.

Every test here corresponds to a way the first version of this was wrong on live data.
Runway is the number a reader acts on, so a wrong one is worse than none: a four-month
runway on a company that has twelve reads as a going-concern alarm.
"""

import pytest

import db
import runway


def _company(conn, ticker, name="Test Bio"):
    conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (ticker, name))
    return conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]


def _fin(conn, cid, metric, value, period_end, period_type="instant",
         fiscal_year=None, fiscal_period=None):
    conn.execute(
        "INSERT INTO financials (company_id, metric, value, period_end, period_type,"
        "  fiscal_year, fiscal_period, unit) VALUES (?, ?, ?, ?, ?, ?, ?, 'USD')",
        (cid, metric, value, period_end, period_type, fiscal_year, fiscal_period))


@pytest.fixture()
def path(tmp_path):
    p = str(tmp_path / "t.db")
    db.init(p)
    return p


# --- the stage split -----------------------------------------------------------------

def test_a_company_with_inventory_is_commercial(path):
    conn = db.get_connection(path)
    cid = _company(conn, "BIG")
    _fin(conn, cid, "Inventory", 5e8, "2026-03-31")
    conn.commit()
    assert runway.stage(conn, cid) == runway.COMMERCIAL
    conn.close()


def test_a_company_with_neither_inventory_nor_cogs_is_clinical(path):
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 1e8, "2026-03-31")
    conn.commit()
    assert runway.stage(conn, cid) == runway.CLINICAL
    conn.close()


def test_no_financials_at_all_is_unknown_not_clinical(path):
    """Roche and Bayer file nothing with the SEC. Reading that silence as a company with
    no product would be badly wrong about two of the largest drugmakers alive."""
    conn = db.get_connection(path)
    cid = _company(conn, "ROG", "Roche")
    conn.commit()
    assert runway.stage(conn, cid) == runway.UNKNOWN
    conn.close()


# --- liquidity -----------------------------------------------------------------------

def test_marketable_securities_count_as_cash(path):
    """The bug that mattered most. A biotech parks its runway in marketable securities,
    so reading the cash line alone put Intellia at 135m against a real 517m, and its
    runway at four months against seventeen."""
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 135e6, "2026-03-31")
    _fin(conn, cid, "ShortTermInvestments", 241e6, "2026-03-31")
    _fin(conn, cid, "LongTermInvestments", 141e6, "2026-03-31")
    conn.commit()
    money = runway.liquidity(conn, cid)
    conn.close()
    assert money["cash"] == pytest.approx(517e6)
    assert money["includes_investments"]
    assert money["cash_only"] == pytest.approx(135e6)


def test_investments_are_read_at_the_cash_date(path):
    """Two dates added together is not a balance sheet."""
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 100e6, "2026-03-31")
    _fin(conn, cid, "ShortTermInvestments", 900e6, "2024-12-31")   # a stale period
    conn.commit()
    money = runway.liquidity(conn, cid)
    conn.close()
    assert money["cash"] == pytest.approx(100e6)
    assert not money["includes_investments"]


# --- burn ----------------------------------------------------------------------------

def test_burn_is_trailing_twelve_months_not_an_annualised_quarter(path):
    """EDGAR states cash flow cumulatively from the start of the year. Annualising the
    latest partial turns one heavy quarter into a year of it."""
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashFlowOperating", -345e6, "2025-12-31", "FY", 2025, "12M")
    _fin(conn, cid, "CashFlowOperating", -104e6, "2025-03-31", "Q", 2025, "3M")
    _fin(conn, cid, "CashFlowOperating", -128e6, "2026-03-31", "Q", 2026, "3M")
    conn.commit()
    burn = runway.trailing_burn(conn, cid)
    conn.close()
    # -345 + 104 - 128, not -128 * 4
    assert burn["burn"] == pytest.approx(-369e6)
    assert "trailing twelve months" in burn["basis"]


def test_burn_falls_back_to_the_full_year_when_no_prior_partial(path):
    """Stale is better than an annualised quarter, and the basis says which it is."""
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashFlowOperating", -300e6, "2025-12-31", "FY", 2025, "12M")
    _fin(conn, cid, "CashFlowOperating", -100e6, "2026-03-31", "Q", 2026, "3M")
    conn.commit()
    burn = runway.trailing_burn(conn, cid)
    conn.close()
    assert burn["burn"] == pytest.approx(-300e6)
    assert burn["basis"] == "last full year"


# --- runway --------------------------------------------------------------------------

def test_runway_is_cash_over_monthly_burn(path):
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 120e6, "2026-03-31")
    _fin(conn, cid, "CashFlowOperating", -120e6, "2025-12-31", "FY", 2025, "12M")
    conn.commit()
    conn.close()
    row = runway.for_company(path, "BIO")
    assert row["runway_months"] == pytest.approx(12)


def test_a_cash_generative_company_has_no_runway_figure(path):
    """Dividing by a positive cash flow prints a negative month count, which reads like
    an emergency at a company that is not in one."""
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 120e6, "2026-03-31")
    _fin(conn, cid, "CashFlowOperating", 50e6, "2025-12-31", "FY", 2025, "12M")
    conn.commit()
    conn.close()
    assert runway.for_company(path, "BIO")["runway_months"] is None


def test_a_burn_offset_by_a_receipt_is_flagged(path):
    """Arrowhead burned 36m against 607m of R&D after a licensing deal, printing a
    runway of 49 years. The figure stands; the flag says not to read it as the rate."""
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 1784e6, "2026-03-31")
    _fin(conn, cid, "CashFlowOperating", -36e6, "2025-12-31", "FY", 2025, "12M")
    _fin(conn, cid, "ResearchAndDevelopmentExpense", 607e6, "2025-12-31", "FY", 2025, "12M")
    conn.commit()
    conn.close()
    row = runway.for_company(path, "BIO")
    assert row["burn_flattered"] is True
    assert row["runway_months"] is not None, "the figure is reported, not suppressed"


def test_a_normal_burn_is_not_flagged(path):
    conn = db.get_connection(path)
    cid = _company(conn, "BIO")
    _fin(conn, cid, "CashAndEquivalents", 300e6, "2026-03-31")
    _fin(conn, cid, "CashFlowOperating", -140e6, "2025-12-31", "FY", 2025, "12M")
    _fin(conn, cid, "ResearchAndDevelopmentExpense", 150e6, "2025-12-31", "FY", 2025, "12M")
    conn.commit()
    conn.close()
    assert runway.for_company(path, "BIO")["burn_flattered"] is False


def test_build_ranks_shortest_runway_first_and_sinks_the_unknowns(path):
    """Absence of data is not urgency. A company with no figure at the top of a risk
    ordered list reads as the most urgent one on it."""
    conn = db.get_connection(path)
    short = _company(conn, "SHORT")
    _fin(conn, short, "CashAndEquivalents", 10e6, "2026-03-31")
    _fin(conn, short, "CashFlowOperating", -120e6, "2025-12-31", "FY", 2025, "12M")
    long = _company(conn, "LONG")
    _fin(conn, long, "CashAndEquivalents", 500e6, "2026-03-31")
    _fin(conn, long, "CashFlowOperating", -100e6, "2025-12-31", "FY", 2025, "12M")
    blank = _company(conn, "BLANK")
    _fin(conn, blank, "CashAndEquivalents", 50e6, "2026-03-31")
    conn.commit()
    conn.close()
    order = [r["ticker"] for r in runway.build(path)]
    assert order == ["SHORT", "LONG", "BLANK"]


def test_build_excludes_commercial_companies(path):
    conn = db.get_connection(path)
    cid = _company(conn, "BIG")
    _fin(conn, cid, "Inventory", 5e8, "2026-03-31")
    _fin(conn, cid, "CashAndEquivalents", 10e6, "2026-03-31")
    _fin(conn, cid, "CashFlowOperating", -120e6, "2025-12-31", "FY", 2025, "12M")
    conn.commit()
    conn.close()
    assert [r["ticker"] for r in runway.build(path)] == []
