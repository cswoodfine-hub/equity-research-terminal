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
    got = FP.filer_productivity(conn, 1, {}, {}, switches={}, funded={}, bought={})
    # rd_filed is what was read off the filings; rd is that carried to the full
    # window, which a two-year fixture exercises but min_rd_years excludes from the pool.
    assert got["rd_filed"] == pytest.approx(19122e6 + 17938e6) and got["rd_years"] == 2
    assert got["rate"] == pytest.approx(
        1443e6 / ((19122e6 + 17938e6) / 2 * FP.COHORT_YEARS))


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
    assert whole["rd_filed"] == pytest.approx(24000e6)
    # Two years of segment R&D carried to the window the rate is measured over.
    assert whole["rate"] == pytest.approx(5155e6 / (24000e6 / 2 * FP.COHORT_YEARS))
    assert "all 2 years" in whole["rd_basis"]
    part = FP.filer_productivity(conn, 1, {}, {}, segment={"JNJ": {2024: (12000e6, "USD")}})
    assert part["rd_filed"] == pytest.approx(30000e6) and "not reported for 2023" in part["rd_basis"]
    assert FP.filer_productivity(conn, 1, {}, {}, segment={})["rd_basis"] is None


def test_a_52_week_year_is_matched_to_the_year_it_falls_in():
    assert FP._fiscal_year_of("2016-01-03") == 2015
    assert FP._fiscal_year_of("2017-12-31") == 2017
    assert FP._fiscal_year_of("2025-06-30") == 2025


def test_a_line_that_buys_no_launches_is_left_out_of_the_future_pipeline(tmp_path,
                                                                      monkeypatch):
    import db
    import forecast_view as V
    seen = {}

    def fake_simulate(book_rd, rate, *args, **kwargs):
        seen["book_rd"] = dict(book_rd)
        return {"value": 1.0, "flows": [], "first_launch_year": 2030, "cohorts": 0,
                "replacement": None, "renewal": None, "credited_share": None}
    monkeypatch.setattr(FP, "simulate", fake_simulate)
    monkeypatch.setattr(FP, "pooled", lambda db_path=None: {"rate": 0.3, "filers": [], "n": 0, "credibility": {}})
    monkeypatch.setattr(V, "_launch_record", lambda *a, **k: {"history_rd": {}, "launched": set()})
    row = {"revenue": 100.0, "cogs": 20.0, "sga": 20.0, "rd": 15.0, "other": 0.0, "ebit": 45.0, "tax": 5.0}
    drug = {"asset_id": 1, "pnl_share": [row], "dcf_years": [2026], "wacc": 0.08}
    medtech = {"line": "MedTech", "buys_launches": False, "pnl_share": [dict(row, rd=40.0)],
               "dcf_years": [2026], "wacc": 0.08}
    path = str(tmp_path / "fp.db")
    db.init(path)
    V._future_pipeline(path, [drug, medtech], "2025-12-31", "JNJ")
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


def test_launches_are_held_to_the_room_the_book_leaves():
    free = _sim(ratios={**RATIOS, "rd": 0.0})
    held = _sim(ratios={**RATIOS, "rd": 0.0}, room={y: 12.0 for y in range(2026, 2086)})
    rev = {f["year"]: f["revenue"] for f in held["flows"]}
    assert rev[2034] == pytest.approx(12.0) and rev[2046] == pytest.approx(12.0)
    assert rev[2050] == pytest.approx(30.0 * 0.75 * 0.8 ** 4)     # the tail fits again
    assert held["capped_from"] == 2034 and 0 < held["capped_share"] < 1
    assert held["value"] < free["value"]
    assert free["capped_from"] is None and free["capped_share"] == 0.0


def test_revenue_past_the_room_buys_no_next_generation():
    free = _sim()
    held = _sim(room={y: 10.0 for y in range(2026, 2086)})
    assert max(f["revenue"] for f in held["flows"]) <= 10.0 + 1e-9
    assert held["replacement"] < free["replacement"]


def test_the_book_is_carried_past_its_forecast_the_way_its_terminal_value_is():
    years = list(range(2026, 2036))
    parts = [
        {"revenue": {2026: 100.0, 2027: 100.0}, "loe_year": None, "growth": 0.0},
        {"revenue": {2026: 50.0, 2027: 40.0}, "loe_year": 2026, "loe_in_base": False},
        {"revenue": {2026: 20.0, 2027: 20.0}, "loe_year": 2029, "loe_in_base": False},
        {"revenue": {2026: 10.0, 2027: 10.0}, "loe_year": 2024, "loe_in_base": True},
    ]
    got = FP.book_revenue(parts, years, erosion_year1=0.5, erosion_decay=0.2)
    assert got[2027] == pytest.approx(170.0)
    assert got[2028] == pytest.approx(100.0 + 40.0 * 0.8 + 20.0 + 10.0)
    assert got[2029] == pytest.approx(100.0 + 40.0 * 0.64 + 20.0 + 10.0)
    assert got[2030] == pytest.approx(100.0 + 40.0 * 0.8 ** 3 + 10.0 + 10.0)
    assert got[2031] == pytest.approx(100.0 + 40.0 * 0.8 ** 4 + 8.0 + 10.0)


def test_the_room_is_the_books_best_year_less_what_it_sells():
    space, peak, year = FP.room({2026: 80.0, 2027: 100.0, 2028: 90.0, 2029: 60.0})
    assert (peak, year) == (100.0, 2027)
    assert space == {2026: 20.0, 2027: 0.0, 2028: 10.0, 2029: 40.0}
    grown, _, _ = FP.room({2026: 100.0, 2027: 50.0}, long_run_growth=0.1)
    assert grown[2027] == pytest.approx(60.0)


def test_a_launch_a_partner_funded_is_not_in_the_filers_record(tmp_path):
    import db
    path = str(tmp_path / "pf.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'REGN', 'Regeneron')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Dupixent', 1), (2, 1, 'Libtayo', 1)")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date, application_number) VALUES"
                 " (1, 'US', 'FDA', '2017-03-28', 'BLA761055'), (2, 'US', 'FDA', '2018-09-28', 'BLA761097')")
    for aid, value in ((1, 5884.0e6), (2, 1452.2e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source) VALUES (?, 2025, 'FY', ?, 'USD', 't')", (aid, value))
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                 " VALUES (1, 'ResearchAndDevelopmentExpense', 'FY', 2024, '2024-12-31', 5000e6, 'USD')")
    conn.commit()
    both = FP.filer_productivity(conn, 1, {}, {}, segment={}, switches={}, funded={})
    assert both["fresh_revenue"] == pytest.approx(7336.2e6) and both["launch_count"] == 2
    own = FP.filer_productivity(conn, 1, {}, {}, segment={}, switches={}, funded={("REGN", "dupixent"): "Sanofi"})
    assert own["fresh_revenue"] == pytest.approx(1452.2e6) and own["launch_count"] == 1
    assert own["partner_funded"] == [{"name": "Dupixent", "approved": "2017-03-28", "revenue": 5884.0e6, "partner": "Sanofi"}]


def test_rd_already_spent_buys_the_launches_before_the_lag_runs_out():
    ahead = _sim(ratios={**RATIOS, "rd": 0.0})
    spent = _sim(ratios={**RATIOS, "rd": 0.0}, history_rd={2019: 50.0, 2025: 60.0, 2010: 999.0})
    rev = {f["year"]: f["revenue"] for f in spent["flows"]}
    assert rev[2026] == 0.0 and rev[2027] == pytest.approx(15.0)     # 2019 spend, 8y lag
    assert rev[2033] == pytest.approx(15.0 + 18.0)                  # 2025 spend arrives
    assert rev[2034] == pytest.approx(15.0 + 18.0 + 30.0)           # the book's own
    assert spent["history_cohorts"] == 2 and spent["value"] > ahead["value"]


def test_launches_the_book_names_come_off_what_the_cohorts_earn():
    spent = dict(ratios={**RATIOS, "rd": 0.0}, history_rd={2019: 50.0})
    named = _sim(**spent, named={2027: 10.0, 2028: 40.0})
    rev = {f["year"]: f["revenue"] for f in named["flows"]}
    assert rev[2027] == pytest.approx(5.0) and rev[2028] == 0.0 and rev[2029] == pytest.approx(15.0)
    assert named["named_overlap"] == pytest.approx(10.0 + 15.0)


def test_rd_history_reads_the_net_figure_and_the_medicines_segment(tmp_path):
    import db
    path = str(tmp_path / "rh.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'JNJ', 'Johnson & Johnson')")
    rows = [("ResearchAndDevelopmentExpense", 2018, "2018-12-30", 10800e6),
            ("ResearchAndDevelopmentExpense", 2019, "2019-12-29", 11400e6),
            ("ResearchLessExpensedIprd", 2019, "2019-12-29", 11000e6),
            ("ResearchAndDevelopmentExpense", 2021, "2021-01-03", 12200e6),
            ("ResearchAndDevelopmentExpense", 2017, "2017-12-31", 9000e6)]
    for metric, year, end, value in rows:
        conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                     " VALUES (1, ?, 'FY', ?, ?, ?, 'USD')", (metric, year, end, value))
    conn.commit()
    got = FP.rd_history(conn, 1, 2018, 2020, segment={"JNJ": {2018: (8000e6, "USD")}})
    assert got == {2018: 8000.0, 2019: 11000.0, 2020: 12200.0}


def test_a_named_launch_does_not_come_off_the_forecasts_own_cohorts():
    free = _sim(ratios={**RATIOS, "rd": 0.0})
    named = _sim(ratios={**RATIOS, "rd": 0.0}, named={y: 100.0 for y in range(2026, 2086)})
    assert named["value"] == pytest.approx(free["value"]) and named["named_overlap"] == 0.0


def test_a_launch_that_came_with_a_company_is_not_the_filers_research(tmp_path):
    import db
    path = str(tmp_path / "acq.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed) VALUES (1, 1, 'Tepezza', 1), (2, 1, 'Imdelltra', 1)")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date, application_number) VALUES"
                 " (1, 'US', 'FDA', '2020-01-21', 'BLA761143'), (2, 'US', 'FDA', '2024-05-16', 'BLA761344')")
    for aid, value in ((1, 1900.0e6), (2, 630.0e6)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit, source) VALUES (?, 2025, 'FY', ?, 'USD', 't')", (aid, value))
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year, period_end, value, unit)"
                 " VALUES (1, 'ResearchAndDevelopmentExpense', 'FY', 2024, '2024-12-31', 5000e6, 'USD')")
    conn.commit()
    both = FP.filer_productivity(conn, 1, {}, {}, segment={}, switches={}, funded={}, bought={})
    assert both["fresh_revenue"] == pytest.approx(2530.0e6) and both["launch_count"] == 2
    own = FP.filer_productivity(conn, 1, {}, {}, segment={}, switches={}, funded={},
                                bought={("AMGN", "tepezza"): "Horizon Therapeutics"})
    assert own["fresh_revenue"] == pytest.approx(630.0e6) and own["launch_count"] == 1
    assert own["acquired"] == [{"name": "Tepezza", "approved": "2020-01-21",
                                "revenue": 1900.0e6,
                                "acquired_from": "Horizon Therapeutics"}]
