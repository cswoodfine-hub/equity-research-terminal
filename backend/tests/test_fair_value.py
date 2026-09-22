"""Fair value across lenses: revenue against guidance, comparables, and the markers."""

import math

import pytest

import breakpoints as B
import db
import fair_value as F


def _company(tmp_path, close=300.0, guidance=None, fx_basis="reported"):
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
        # A growth guide draws a lens only where the release states a currency basis,
        # so the default here is the one a lens can be read from.
        conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value,"
                     " low, high, currency, source, as_of, note, fx_basis)"
                     " VALUES (1, ?, ?, ?, ?, ?, 'USD', 'guidance', '2025-12-01', 'q', ?)",
                     (metric, period, value, low, high, fx_basis))
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
    assert got["basis"] == ("growth of 3% to 5% on a reported basis, applied to "
                            "FY2025 reported revenue")


def test_growth_guidance_on_the_wrong_basis_is_withheld(tmp_path):
    """A rate guided at constant exchange rates cannot be applied to reported revenue,
    and a rate with no stated basis cannot be assumed onto one."""
    cer = _company(tmp_path / "cer", guidance=[("RevenueGrowth", "FY2026", 4.0, 3.0, 5.0)],
                   fx_basis="cer")
    conn = db.get_connection(cer)
    assert "constant exchange rates" in F.guidance(conn, 1, 2026, 3000e6, "USD")["reason"]
    conn.close()

    unstated = _company(tmp_path / "none",
                        guidance=[("RevenueGrowth", "FY2026", 4.0, 3.0, 5.0)],
                        fx_basis=None)
    conn = db.get_connection(unstated)
    assert "states no currency basis" in F.guidance(conn, 1, 2026, 3000e6, "USD")["reason"]
    conn.close()


def test_guidance_in_another_currency_is_not_read_against_the_book(tmp_path):
    path = _company(tmp_path, guidance=[("Revenue", "FY2026", 3300e6, None, None)])
    conn = db.get_connection(path)
    assert F.guidance(conn, 1, 2026, 3000e6, "DKK") == {"reason": "FY2026 guidance is in USD, the book in DKK"}
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


def test_the_company_view_carries_its_lenses_with_bases(tmp_path, monkeypatch):
    # Repatha grows 10% a year on a filed rate: its band's fade quartiles are 3 and 8 years.
    measured = {"bands": [{"band": (0.0, 0.10), "n": 9, "peaked": 6, "censored": 3,
                           "low": 3, "median": 5, "high": 8}]}
    monkeypatch.setattr(F.GA, "measure", lambda path=None: measured)
    monkeypatch.setattr(F, "precedents", lambda path=None: [])      # tested on its own below
    path = _company(tmp_path, guidance=[("Revenue", "FY2026", 3630e6, 3465e6, 3795e6)])
    got = F.company(path, "AMGN", peers=[])
    keys = [l["key"] for l in got["lenses"]]
    assert keys == ["sotp_wacc", "sotp_fade", "sotp_guidance", "targets", "range"]
    fade = got["lenses"][1]
    assert fade["products"] == 1 and fade["low"] < got["equity_per_share"] < fade["high"]
    wacc = got["lenses"][0]
    assert wacc["mid"] == pytest.approx(got["equity_per_share"])
    assert wacc["low"] < wacc["mid"] < wacc["high"]
    assert (got["lenses"][3]["low"], got["lenses"][3]["high"]) == (280, 400)
    assert (got["lenses"][4]["low"], got["lenses"][4]["high"]) == (250, 300)
    assert all(l["basis"] for l in got["lenses"])


def test_guidance_that_cannot_be_read_against_the_book_says_why(tmp_path):
    cases = (([("RevenueGrowth", "FY2026", None, None, None)], "FY2026 revenue guidance is stated in words, not a number"),
             ([("Revenue", "FY2026", None, None, None)], "the company gives no FY2026 revenue guidance"),
             ([("ProductSales", "FY2026", 5195e6, 5130e6, 5260e6)], "FY2026 guidance covers product sales only, not total revenue"))
    for i, (rows, reason) in enumerate(cases):
        path = _company(tmp_path / str(i), guidance=rows)
        assert F.revenue_split(B.Book(path, "AMGN")) == {"ok": False, "reason": reason}


def test_takeover_precedents_read_the_file_and_skip_small_targets(tmp_path):
    csv_path = tmp_path / "p.csv"
    csv_path.write_text(
        "# c\nacquirer,target,announced,offer_per_share_usd,equity_value_musd,enterprise_value_musd,ev_basis,"
        "target_cash_musd,target_debt_musd,balance_sheet_date,revenue_fy_musd,revenue_fy_year,revenue_ttm_musd,"
        "ttm_end,premium_pct,accessions,quotes,note\n"
        "A,T1,2020-01-01,1,,40000,stated,,,,10000,2019,,,,a,q,\n"
        "A,T2,2020-01-01,1,30000,,computed,2000,4000,2019-12-31,5000,2019,,,,a,q,\n"
        "A,T3,2020-01-01,1,,24000,stated,,,,4000,2019,,,,a,q,\n"
        "A,T4,2020-01-01,1,,50000,stated,,,,5000,2019,,,,a,q,\n"
        "A,T5,2020-01-01,1,,9000,stated,,,,300,2019,,,,a,q,\n"
        "A,T6,2020-01-01,1,20000,,computed,,,,2000,2019,,,,a,q,\n"
        "A,T7,2020-01-01,1,,8000,stated,,,,900,2019,1600,2019-09-30,,a,q,\n")
    deals = F.precedents(csv_path)
    assert [d["target"] for d in deals] == ["T1", "T2", "T3", "T4", "T5", "T7"]
    assert deals[-1]["revenue_musd"] == 1600             # trailing twelve months win
    assert deals[1]["ev_musd"] == 32000 and deals[1]["multiple"] == pytest.approx(6.4)
    book = B.Book(_company(tmp_path / "c"), "AMGN")
    got = F.takeover(book, deals)
    own = F._metrics(book)
    assert got["deals"] == 5                         # T5's 300mm of revenue is left out
    assert got["peer_quartiles"] == pytest.approx((5.0, 6.0, 6.4))   # multiples 4, 5, 6, 6.4, 10
    assert got["mid"] == pytest.approx(6.0 * own["revenue_ps"] + own["net_cash_ps"])
