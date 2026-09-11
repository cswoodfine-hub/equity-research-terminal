"""The balance sheet is one date: every stock line is read on the cash line's date."""

import db
import cashflow


def _company(tmp_path, rows):
    path = str(tmp_path / "cf.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'INCY', 'Incyte')")
    for metric, ptype, fy, end, value in rows:
        conn.execute("INSERT INTO financials (company_id, metric, period_type,"
                     " fiscal_year, period_end, value, unit) VALUES (1, ?, ?, ?, ?, ?, 'USD')",
                     (metric, ptype, fy, end, value))
    conn.commit(); conn.close()
    return path


def test_a_stale_debt_row_is_not_netted_against_this_years_cash(tmp_path):
    """Incyte's latest TotalDebt row was a 2018 figure of 19bn. On a 2026 balance
    sheet with no debt line, net debt is left empty rather than guessed, the rule
    every ratio here follows, and the basis names the missing line."""
    path = _company(tmp_path, [
        ("Revenues", "FY", 2025, "2025-12-31", 1000e6),
        ("CashAndEquivalents", "instant", 2026, "2026-03-31", 3461e6),
        ("ShortTermInvestments", "instant", 2024, "2024-09-30", 467e6),
        ("TotalDebt", "instant", 2018, "2018-12-31", 19094e6)])
    got = cashflow.build_cashflow(path, "INCY")
    assert got["net_debt"] is None
    assert got["inputs"]["balance_sheet_as_of"] == "2026-03-31"
    assert got["inputs"]["cash"] == 3461e6
    assert got["inputs"]["cash_lines"] == ["CashAndEquivalents"]   # the 2024 line is not this sheet
    assert got["inputs"]["total_debt"] is None
    assert got["inputs"]["debt_basis"].startswith("no debt line filed")


def test_debt_within_a_year_of_the_cash_date_still_counts(tmp_path):
    path = _company(tmp_path, [
        ("Revenues", "FY", 2025, "2025-12-31", 1000e6),
        ("CashAndEquivalents", "instant", 2026, "2026-06-30", 500e6),
        ("ShortTermInvestments", "instant", 2026, "2026-06-30", 100e6),
        ("TotalDebt", "instant", 2025, "2025-12-31", 900e6)])
    got = cashflow.build_cashflow(path, "INCY")
    assert got["net_debt"] == 300e6
    assert got["inputs"]["debt_as_of"] == "2025-12-31"
    assert got["inputs"]["debt_basis"] == "filed"
