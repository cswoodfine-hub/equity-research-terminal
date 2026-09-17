"""The launches the modelled book's R&D buys, valued from what R&D has bought."""

import pytest

import future_pipeline as FP

RATIOS = {"cogs": 0.2, "sga": 0.3, "rd": 0.2, "other": 0.0, "tax": 0.2}


def _sim(**over):
    args = dict(book_rd={2026: 100.0}, rate=0.3, lag=8, life=12, erosion_year1=0.25,
                erosion_decay=0.2, ratios=RATIOS, discount=0.08, base_year=2025,
                horizon=60)
    args.update(over)
    return FP.simulate(**args)


def test_a_years_spend_buys_a_cohort_after_the_lag_at_the_rate():
    got = _sim(ratios={**RATIOS, "rd": 0.0})           # no reinvestment, one cohort
    rev = {f["year"]: f["revenue"] for f in got["flows"]}
    assert rev[2033] == 0.0 and rev[2034] == pytest.approx(30.0)
    assert rev[2045] == pytest.approx(30.0)                  # twelve years at the rate
    assert rev[2046] == pytest.approx(30.0 * 0.75)          # the year-one drop
    assert rev[2047] == pytest.approx(30.0 * 0.75 * 0.8)    # then decay
    assert got["first_launch_year"] == 2034 and got["cohorts"] == 1


def test_the_launches_own_rd_buys_the_next_generation():
    one = _sim(ratios={**RATIOS, "rd": 0.0})
    renewed = _sim()
    assert renewed["cohorts"] > one["cohorts"]
    assert renewed["replacement"] > 0
    rev = {f["year"]: f["revenue"] for f in renewed["flows"]}
    assert rev[2042] > rev[2034]          # 2034 revenue's R&D arrives as launches in 2042


def test_value_is_the_discounted_after_tax_margin_on_that_revenue():
    got = _sim(ratios={**RATIOS, "rd": 0.0}, horizon=10)    # 2026-2035: two launch years
    ebit = 30.0 * (1 - 0.2 - 0.3)
    assert got["value"] == pytest.approx(ebit * 0.8 / 1.08 ** 8.5
                                         + ebit * 0.8 / 1.08 ** 9.5)


def test_nothing_spent_is_nothing_bought():
    got = _sim(book_rd={})
    assert got["value"] == 0.0 and got["first_launch_year"] is None
    assert got["replacement"] is None


def test_defaults_cite_every_row():
    rows = FP.defaults()
    assert {"lag_years", "horizon_years", "min_rd_years", "min_revenue_musd"} <= set(rows)
    assert all(r["source"] for r in rows.values())
    assert rows["lag_years"]["value"] == 8


def test_credibility_trusts_many_launches_more_than_one():
    """Two filers differ by far more than their noise: each earns weight on its own
    rate, and the one resting on more launches earns more."""
    filers = [
        {"rate": 1.0, "rd": 100.0, "launch_revenues": [20.0, 25.0, 30.0, 25.0]},
        {"rate": 0.2, "rd": 100.0, "launch_revenues": [4.0, 5.0, 6.0, 5.0]},
        {"rate": 0.5, "rd": 100.0, "launch_revenues": [5.0] * 10},
    ]
    got = FP.credibility(filers)
    assert got["k"] is not None and got["tau2"] > 0
    few, _ = FP.blend(1.0, 2, 0.4, got["k"])
    many, _ = FP.blend(1.0, 20, 0.4, got["k"])
    assert 0.4 < few < many < 1.0
    assert FP.blend(1.0, 20, 0.4, got["k"])[1] == pytest.approx(20 / (20 + got["k"]))


def test_filers_no_more_different_than_their_noise_all_take_the_pool():
    """One launch each at wildly different sizes: the spread is all noise."""
    filers = [{"rate": r, "rd": 100.0, "launch_revenues": [r * 100.0, r * 100.0 * 9]}
              for r in (0.3, 0.31, 0.29)]
    got = FP.credibility(filers)
    assert got["k"] is None
    assert FP.blend(0.31, 5, 0.3, got["k"]) == (0.3, 0.0)


def test_no_launch_record_takes_the_pool():
    assert FP.blend(None, 0, 0.3, 5.0) == (0.3, 0.0)
    assert FP.blend(0.9, 0, 0.3, 5.0) == (0.3, 0.0)


def test_renewal_is_rate_times_rd_times_a_launch_lifetime():
    assert FP.renewal(0.3, 0.2, 12, 0.25, 0.2) == pytest.approx(0.3 * 0.2 * (12 + 3.75))


def test_a_compounding_franchise_is_held_to_the_long_run_growth():
    """Vertex's shape: a high rate on a high R&D ratio compounds without a cap and the
    value then rests on the horizon. Capped at zero long-run growth it replaces itself,
    and the horizon stops mattering."""
    heavy = {**RATIOS, "rd": 0.32}
    free40 = _sim(rate=0.51, ratios=heavy, horizon=40)["value"]
    free100 = _sim(rate=0.51, ratios=heavy, horizon=100)["value"]
    assert free100 > free40 * 1.5
    capped = _sim(rate=0.51, ratios=heavy, horizon=100, long_run_growth=0.0)
    assert capped["credited_share"] == pytest.approx(1.0 / capped["renewal"])
    assert capped["value"] < free100
    capped40 = _sim(rate=0.51, ratios=heavy, horizon=40, long_run_growth=0.0)["value"]
    assert capped["value"] < capped40 * 1.3


def test_a_franchise_that_runs_down_is_not_capped():
    got = _sim(rate=0.1, long_run_growth=0.0)
    assert got["renewal"] < 1 and got["credited_share"] == 1.0
    assert got["value"] == pytest.approx(_sim(rate=0.1)["value"])


def test_rd_is_read_net_of_in_process_rd_expensed_inside_it(tmp_path):
    """A year with a net R&D figure on file reads it; a year without reads R&D as filed."""
    import db
    path = str(tmp_path / "fp.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'MRK', 'Merck')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Winrevair', 1)")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date, application_number)"
                 " VALUES (1, 'US', 'FDA', '2024-03-26', 'BLA761363')")
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source)"
                 " VALUES (1, 2025, 'FY', 1443e6, 'USD', 't')")
    for fy, rd in ((2023, 30531e6), (2024, 17938e6)):
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, 'ResearchAndDevelopmentExpense', 'FY', ?, ?, ?, 'USD')", (fy, f"{fy}-12-31", rd))
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                 " VALUES (1, 'ResearchLessExpensedIprd', 'FY', 2023, '2023-12-31', 19122e6, 'USD')")
    conn.commit()
    got = FP.filer_productivity(conn, 1, {}, {})
    assert got["rd"] == pytest.approx(19122e6 + 17938e6) and got["rd_years"] == 2
    assert got["rate"] == pytest.approx(1443e6 / (19122e6 + 17938e6))


def _filer(tmp_path, years):
    import db
    path = str(tmp_path / "fp.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'JNJ', 'Johnson & Johnson')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Tremfya', 1)")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date, application_number)"
                 " VALUES (1, 'US', 'FDA', '2017-07-13', 'BLA761061')")
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source)"
                 " VALUES (1, 2025, 'FY', 5155e6, 'USD', 't')")
    for fy in years:
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, 'ResearchAndDevelopmentExpense', 'FY', ?, ?, 15000e6, 'USD')", (fy, f"{fy}-12-31"))
    conn.commit()
    return conn


def test_the_medicines_segments_rd_is_the_denominator_only_for_a_whole_window(tmp_path):
    conn = _filer(tmp_path, (2023, 2024))
    whole = FP.filer_productivity(conn, 1, {}, {}, segment={"JNJ": {2023: (12000e6, "USD"), 2024: (12000e6, "USD")}})
    assert whole["rd"] == pytest.approx(24000e6) and whole["rate"] == pytest.approx(5155e6 / 24000e6)
    assert "all 2 years" in whole["rd_basis"]
    part = FP.filer_productivity(conn, 1, {}, {}, segment={"JNJ": {2024: (12000e6, "USD")}})
    assert part["rd"] == pytest.approx(30000e6) and "not reported for 2023" in part["rd_basis"]
    assert FP.filer_productivity(conn, 1, {}, {}, segment={})["rd_basis"] is None


def test_a_52_week_year_is_matched_to_the_year_it_falls_in():
    assert FP._fiscal_year_of("2016-01-03") == 2015
    assert FP._fiscal_year_of("2017-12-31") == 2017
    assert FP._fiscal_year_of("2025-06-30") == 2025


def test_a_line_that_buys_no_launches_is_left_out_of_the_future_pipeline(monkeypatch):
    import forecast_view as V
    seen = {}

    def fake_simulate(book_rd, rate, *args, **kwargs):
        seen["book_rd"] = dict(book_rd)
        return {"value": 1.0, "flows": [], "first_launch_year": 2030, "cohorts": 0,
                "replacement": None, "renewal": None, "credited_share": None}
    monkeypatch.setattr(FP, "simulate", fake_simulate)
    monkeypatch.setattr(FP, "pooled", lambda db_path=None: {"rate": 0.3, "filers": [], "n": 0, "credibility": {}})
    row = {"revenue": 100.0, "cogs": 20.0, "sga": 20.0, "rd": 15.0, "other": 0.0, "ebit": 45.0, "tax": 5.0}
    drug = {"asset_id": 1, "pnl_share": [row], "dcf_years": [2026], "wacc": 0.08}
    medtech = {"line": "MedTech", "buys_launches": False, "pnl_share": [dict(row, rd=40.0)],
               "dcf_years": [2026], "wacc": 0.08}
    V._future_pipeline(None, [drug, medtech], "2025-12-31", "JNJ")
    assert seen["book_rd"] == {2026: 15.0}


def test_a_switch_form_is_dated_from_the_form_it_replaces(tmp_path):
    import db
    path = str(tmp_path / "sw.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'REGN', 'Regeneron')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Eylea', 1), (2, 1, 'Eylea Hd', 1)")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date, application_number) VALUES"
                 " (1, 'US', 'FDA', '2011-11-18', 'BLA125387'), (2, 'US', 'FDA', '2023-08-18', 'BLA125387s')")
    for aid, value in ((1, 2747.8e6), (2, 1636.9e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source) VALUES (?, 2025, 'FY', ?, 'USD', 't')", (aid, value))
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                 " VALUES (1, 'ResearchAndDevelopmentExpense', 'FY', 2024, '2024-12-31', 5000e6, 'USD')")
    conn.commit()
    counted = FP.filer_productivity(conn, 1, {}, {}, segment={}, switches={})
    assert counted["fresh_revenue"] == pytest.approx(1636.9e6)
    switched = FP.filer_productivity(conn, 1, {}, {}, segment={}, switches={("REGN", "eylea hd"): "Eylea"})
    assert switched["fresh_revenue"] == 0.0
    assert switched["switch_forms"] == [{"name": "Eylea Hd", "approved": "2023-08-18", "dated_from": "Eylea", "parent_approved": "2011-11-18"}]
