"""Fair value across lenses: revenue against guidance, comparables, and the markers."""

import math

import pytest

import breakpoints as B
import db
import fair_value as F


def _company(tmp_path, close=300.0, guidance=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = str(tmp_path / "fv.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Repatha', 1)")
    rows = [("therapy_mode", None, "marketed", "approved and selling"),
            ("base_revenue", 3000, None, "Amgen 10-K (0000318154-26-000010)"),
            ("revenue_growth_pct", 0.10, None, "Amgen 10-Q (0000318154-26-000126)"),
            ("terminal_growth_pct", 0.0, None, "convention: faded to flat"),
            ("forecast_start_year", 2026, None, "the year after the last reported full year"),
            ("forecast_years", 10, None, "convention"),
            ("wacc", 0.08, None, "judgement"), ("pos", 1.0, None, "approved and selling"),
            ("cogs_pct", 0.3, None, "filed lines"), ("sga_pct", 0.2, None, "filed lines"),
            ("rd_pct", 0.1, None, "filed lines"), ("tax_rate", 0.15, None, "filed lines")]
    import assumptions
    assumptions.save(conn, 1, [{"key": k, "value": v, "text_value": t, "source": s}
                               for k, v, t, s in rows])
    for metric, value in (("Revenues", 3000e6), ("WeightedAverageDilutedShares", 100e6)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, ?, 'FY', 2025, '2025-12-31', ?, 'USD')", (metric, value))
    for metric, value in (("CashAndEquivalents", 1000e6), ("TotalDebt", 3000e6)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, ?, 'instant', 2025, '2025-12-31', ?, 'USD')", (metric, value))
    conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source) VALUES (1, '2025-06-30', 250, '1d', 't')")
    conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source) VALUES (1, '2025-12-31', ?, '1d', 't')", (close,))
    for metric, period, value, low, high in (guidance or []):
        conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value, low, high, currency, source, as_of, note)"
                     " VALUES (1, ?, ?, ?, ?, ?, 'USD', 'guidance', '2025-12-01', 'q')",
                     (metric, period, value, low, high))
    for period, eps in (("FY2025", 20.0), ("FY2026", 24.0)):
        conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value, currency, source, as_of)"
                     " VALUES (1, 'EPS', ?, ?, 'USD', 'nasdaq', '2025-12-01')", (period, eps))
    conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value, low, high, currency, source, as_of, note)"
                 " VALUES (1, 'PriceTarget', '12M', 320, 280, 400, 'USD', 'nasdaq', '2025-12-01', '3 buy')")
    conn.commit()
    conn.close()
    return path


def test_quartiles_need_four_values():
    assert F._quartiles([1, 2, 3]) is None
    assert F._quartiles([1, 2, 3, 4, 5]) == (2, 3, 4)
    assert F._quartiles([1, None, 2, float("nan"), 3, 4]) is not None


def test_growth_guidance_is_applied_to_the_prior_year_and_says_so(tmp_path):
    path = _company(tmp_path, guidance=[("RevenueGrowth", "FY2026", 4.0, 3.0, 5.0)])
    conn = db.get_connection(path)
    got = F.guidance(conn, 1, 2026, 3000e6, "USD")
    conn.close()
    assert (got["low"], got["mid"], got["high"]) == pytest.approx((3090, 3120, 3150))
    assert "growth of 3% to 5%" in got["basis"]


def test_guidance_in_another_currency_is_not_read_against_the_book(tmp_path):
    path = _company(tmp_path, guidance=[("Revenue", "FY2026", 3300e6, None, None)])
    conn = db.get_connection(path)
    assert F.guidance(conn, 1, 2026, 3000e6, "DKK") is None
    assert F.guidance(conn, 1, 2026, 3000e6, "USD")["mid"] == pytest.approx(3300)
    conn.close()


def test_matching_revenue_to_guidance_moves_value_by_the_revenue_it_explains(tmp_path):
    # The book grows 3,000 to 3,300 in 2026; guidance says 3,630, ten percent higher.
    path = _company(tmp_path, guidance=[("Revenue", "FY2026", 3630e6, 3465e6, 3795e6)])
    book = B.Book(path, "AMGN")
    split = F.revenue_split(book)
    assert split["ok"] and split["modelled"]["total"] == pytest.approx(3300)
    assert split["gap_pct"] == pytest.approx(0.10)
    assert split["matched_low"] < split["matched_equity"] < split["matched_high"]
    # One marketed product with no costs that move off revenue: the value scales with it.
    enterprise = book.equity - book.per_share(book.net_cash)
    assert split["matched_equity"] - book.per_share(book.net_cash) == pytest.approx(enterprise * 1.1, rel=1e-6)
    assert split["explained_by_revenue"] == pytest.approx(split["matched_equity"] - book.equity)
    assert split["left_for_conventions"] == pytest.approx(book.close - split["matched_equity"])


def test_no_guidance_is_a_reason_not_a_number(tmp_path):
    split = F.revenue_split(B.Book(_company(tmp_path), "AMGN"))
    assert split == {"ok": False, "reason": "no FY2026 revenue guidance on file"}


def test_next_twelve_months_eps_weights_the_two_years():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE consensus_estimates (company_id, metric, period, value, source, as_of)")
    conn.executemany("INSERT INTO consensus_estimates VALUES (1, 'EPS', ?, ?, 'nasdaq', '2026-09-01')",
                     [("FY2026", 36.53), ("FY2027", 46.16)])
    got = F._ntm_eps(conn, 1, "2026-09-16")
    weight = 106 / 365.0
    assert got["weight_this_year"] == pytest.approx(weight)
    assert got["value"] == pytest.approx(36.53 * weight + 46.16 * (1 - weight))


def test_comps_value_the_company_at_its_peers_quartiles(tmp_path):
    book = B.Book(_company(tmp_path), "AMGN")
    own = F._metrics(book)
    peers = [{"ticker": t, "pe_ntm": pe, "ev_sales": evs}
             for t, pe, evs in (("A", 10, 2), ("B", 12, 3), ("C", 14, 4), ("D", 16, 5), ("E", 18, 6))]
    lenses = {l["key"]: l for l in F.comps(book, peers + [{"ticker": "AMGN", "pe_ntm": 99, "ev_sales": 99}])}
    assert lenses["pe_ntm"]["mid"] == pytest.approx(14 * own["eps_ntm"])
    assert lenses["pe_ntm"]["peers"] == 5
    assert lenses["ev_sales"]["low"] == pytest.approx(3 * own["revenue_ps"] + own["net_cash_ps"])


def test_the_company_view_carries_its_lenses_with_bases(tmp_path):
    path = _company(tmp_path, guidance=[("Revenue", "FY2026", 3630e6, 3465e6, 3795e6)])
    got = F.company(path, "AMGN", peers=[])
    keys = [l["key"] for l in got["lenses"]]
    assert keys == ["sotp_wacc", "sotp_guidance", "targets", "range"]
    wacc = got["lenses"][0]
    assert wacc["mid"] == pytest.approx(got["equity_per_share"])
    assert wacc["low"] < wacc["mid"] < wacc["high"]
    assert (got["lenses"][2]["low"], got["lenses"][2]["high"]) == (280, 400)
    assert (got["lenses"][3]["low"], got["lenses"][3]["high"]) == (250, 300)
    assert all(l["basis"] for l in got["lenses"])
