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


def test_the_medicines_segment_file_covers_the_window_its_newest_year_opens():
    """A year missing from the window sends Johnson & Johnson's rate back to company R&D,
    MedTech's included, silently. When the window grew from ten years to twelve, 2013 and
    2014 were missing and the rate read 0.191 on company R&D where its medicines R&D gives
    0.244."""
    for ticker, years in FP.medicines_rd().items():
        newest = max(years)
        wanted = set(range(newest - FP.COHORT_YEARS, newest))
        assert wanted <= set(years), (ticker, sorted(wanted - set(years)))


def test_a_52_week_year_is_matched_to_the_year_it_falls_in():
    # The rule is the parser's now, shared by everything that reads a year off a date.
    import statements
    assert statements.fiscal_year_of("2016-01-03") == 2015
    assert statements.fiscal_year_of("2017-12-31") == 2017
    assert statements.fiscal_year_of("2025-06-30") == 2025


def _not_a_medicine_trial(tmp_path, monkeypatch, ticker, rd_segment):
    """The future pipeline's spend and book for a drug beside a line that sells no
    medicine, with the filer's launch rate measured on segment or company R&D."""
    import db
    import forecast_view as V
    seen = {}

    def fake_simulate(book_rd, rate, *args, **kwargs):
        seen["book_rd"] = dict(book_rd)
        seen["ratios"] = args[4]
        seen["book"] = dict(kwargs.get("book") or {})
        return {"value": 1.0, "flows": [], "first_launch_year": 2030, "cohorts": 0,
                "replacement": None, "renewal": None, "credited_share": None}
    filer = {"ticker": ticker, "rate": 0.3, "blended": 0.3, "launch_count": 5,
             "credibility": 0.5, "counted": True, "rd_segment": rd_segment}
    monkeypatch.setattr(FP, "simulate", fake_simulate)
    monkeypatch.setattr(FP, "pooled", lambda db_path=None: {"rate": 0.3, "filers": [filer], "n": 1, "credibility": {}})
    monkeypatch.setattr(V, "_launch_record", lambda *a, **k: {"history_rd": {}, "launched": set()})
    row = {"revenue": 100.0, "cogs": 20.0, "sga": 20.0, "rd": 15.0, "other": 0.0, "ebit": 45.0, "tax": 5.0}
    drug = {"asset_id": 1, "pnl_share": [row], "dcf_years": [2026], "wacc": 0.08}
    other = {"line": "Other", "buys_launches": False,
             "pnl_share": [dict(row, revenue=50.0, cogs=40.0, rd=10.0)],
             "dcf_years": [2026], "wacc": 0.08}
    path = str(tmp_path / f"fp_{ticker}.db")
    db.init(path)
    V._future_pipeline(path, [drug, other], "2025-12-31", ticker)
    return seen


def test_a_line_that_buys_no_launches_is_left_out_of_the_future_pipeline(tmp_path,
                                                                      monkeypatch):
    # Johnson & Johnson's rate divides by its medicines segment's R&D, so MedTech's R&D
    # is outside it and buys nothing: the drug's R&D alone, in its forecast and on its
    # tail past it.
    seen = _not_a_medicine_trial(tmp_path, monkeypatch, "JNJ", True)
    assert seen["book_rd"][2026] == 15.0
    assert set(seen["book_rd"].values()) == {15.0}


def test_a_line_that_sells_no_medicine_still_spends_the_rd_the_rate_divides_by(
        tmp_path, monkeypatch):
    """Biogen's rate divides by the company's whole R&D, the share its Ocrevus royalty is
    charged included, so that R&D buys launches. The royalty's revenue stays out of the
    book the launches refill, and its margins out of what they are charged."""
    seen = _not_a_medicine_trial(tmp_path, monkeypatch, "BIIB", False)
    assert seen["book_rd"][2026] == pytest.approx(15.0 + 10.0)
    assert seen["book_rd"][2030] == pytest.approx(15.0 + 10.0)     # both tails, flat
    assert seen["book"][2026] == pytest.approx(100.0)
    assert seen["ratios"]["cogs"] == pytest.approx(0.20)
    assert seen["ratios"]["rd"] == pytest.approx(0.15)


def test_a_pipeline_products_whole_row_is_taken_at_its_probability_once(tmp_path,
                                                                         monkeypatch):
    """Revenue, R&D and every cost on a pipeline line are expected values, risked once.

    The marketed line counts in full. The pipeline line at 40% puts 40 of revenue into
    the book, not 16 (risked twice), and 8 of R&D into what buys the launches, not 20
    (unrisked), so the R&D ratio the launches are charged is 23 over 140.
    """
    import db
    import forecast_view as V
    seen = {}

    def fake_simulate(book_rd, rate, *args, **kwargs):
        seen["book_rd"] = dict(book_rd)
        return {"value": 1.0, "flows": [], "first_launch_year": 2030, "cohorts": 0,
                "replacement": None, "renewal": None, "credited_share": None}
    real_book_revenue = FP.book_revenue

    def spy_book_revenue(parts, *args, **kwargs):
        # The first call is the book; later ones carry each part's tail for its R&D.
        seen.setdefault("book_parts", [dict(p["revenue"]) for p in parts])
        return real_book_revenue(parts, *args, **kwargs)
    monkeypatch.setattr(FP, "simulate", fake_simulate)
    monkeypatch.setattr(FP, "book_revenue", spy_book_revenue)
    monkeypatch.setattr(FP, "pooled", lambda db_path=None: {"rate": 0.3, "filers": [], "n": 0, "credibility": {}})
    monkeypatch.setattr(V, "_launch_record", lambda *a, **k: {"history_rd": {}, "launched": set()})
    marketed = {"asset_id": 1, "pos": None, "dcf_years": [2026], "wacc": 0.08,
                "pnl_share": [{"revenue": 100.0, "cogs": 20.0, "sga": 20.0, "rd": 15.0,
                               "other": 0.0, "ebit": 45.0, "tax": 5.0}]}
    pipeline = {"asset_id": 2, "pos": 0.4, "dcf_years": [2026], "wacc": 0.08,
                "pnl_share": [{"revenue": 100.0, "cogs": 20.0, "sga": 20.0, "rd": 20.0,
                               "other": 0.0, "ebit": 40.0, "tax": 4.0}]}
    path = str(tmp_path / "fp.db")
    db.init(path)
    got = V._future_pipeline(path, [marketed, pipeline], "2025-12-31", "JNJ")
    assert seen["book_rd"][2026] == pytest.approx(15.0 + 8.0)
    # Past the forecast each part's tail charges R&D at its own final-year ratio, risked.
    assert seen["book_rd"][2030] == pytest.approx(100.0 * 0.15 + 40.0 * 0.20)
    assert seen["book_parts"][0] == pytest.approx({2026: 100.0})
    assert seen["book_parts"][1] == pytest.approx({2026: 40.0})
    assert got["ratios"]["rd"] == pytest.approx(23.0 / 140.0)
    assert got["ratios"]["cogs"] == pytest.approx(28.0 / 140.0)
    assert got["ratios"]["tax"] == pytest.approx((5.0 + 1.6) / (45.0 + 16.0))
    # The caller's rows are not touched: the break-points engine reuses them per trial.
    assert pipeline["pnl_share"][0]["rd"] == 20.0


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


def test_the_book_carries_a_product_past_its_forecast_on_its_own_terminal_path():
    import forecast as F
    tail = {"end": 2030, "growth": 0.0, "year1_pct": 0.59, "decay_pct": 0.34,
            "late_decay_pct": None, "late_from_year": None,
            "parts": [[0.7, 2032, False], [0.3, None, True]]}
    part = {"revenue": {2029: 90.0, 2030: 100.0}, "loe_year": 2032, "loe_in_base": False,
            "growth": 0.0, "tail": tail}
    years = list(range(2029, 2040))
    got = FP.book_revenue([part], years, 0.2, 0.2)
    us = F.terminal_path(0.0, 2030, 2032, False, 0.59, 0.34, None, None, years)
    for y in range(2031, 2040):
        assert got[y] == pytest.approx(100.0 * (0.7 * us[y] + 0.3))
    # Its own erosion, not the curated default: the year after the cliff is 41% of 70.
    assert got[2033] == pytest.approx(70.0 * 0.41 + 30.0)
    # No terminal value taken: nothing past the forecast.
    assert FP.book_revenue([dict(part, tail=None)], years, 0.2, 0.2)[2031] == 0.0
    # A company line with no tail key keeps the older rule.
    legacy = {k: v for k, v in part.items() if k != "tail"}
    assert FP.book_revenue([legacy], years, 0.2, 0.2)[2033] == pytest.approx(100.0 * 0.8)


def test_the_room_never_falls_when_the_book_rises():
    book = {2026: 100.0, 2027: 120.0, 2028: 140.0, 2029: 150.0, 2030: 145.0, 2031: 130.0,
            2032: 110.0, 2033: 100.0}

    def old(b, g):
        py = max(b, key=lambda y: (b[y], -y))
        return {y: max(0.0, b[py] * (1 + g) ** max(0, y - py) - b[y]) for y in b}

    # One peak: exactly the rule it replaces.
    assert FP.room(book, 0.02)[0] == pytest.approx(old(book, 0.02))
    # A later year lifted just past the peak moved the old peak year and cut the cap for
    # every year after it; the cap now only rises with the book.
    for year in book:
        for lift in (0.5, 5.0, 20.0):
            higher = {**book, year: book[year] + lift}
            before = {y: FP.room(book, 0.02)[0][y] + book[y] for y in book}
            after = {y: FP.room(higher, 0.02)[0][y] + higher[y] for y in book}
            assert all(after[y] >= before[y] - 1e-9 for y in book), (year, lift)
    flip = {**book, 2031: 151.0}
    assert old(flip, 0.02)[2033] + 100.0 < old(book, 0.02)[2033] + 100.0
    assert FP.room(flip, 0.02)[0][2033] + 100.0 >= FP.room(book, 0.02)[0][2033] + 100.0


def test_the_launches_and_the_book_are_charged_growth_capital_once_on_their_sum():
    # A book that rises, peaks and falls, its forecast five years long, the room binding:
    # the launches fill what the book leaves.
    years = list(range(2026, 2046))
    book = {y: v for y, v in zip(years, [100, 110, 130, 150, 140, 90, 60, 50, 45, 42]
                                 + [40] * 10)}
    charged = {y: max(0.0, book[y] - book[y - 1]) for y in years[1:5]}
    room, _, _ = FP.room(book, 0.02)
    got = _sim(book_rd={y: 50.0 for y in years}, room=room, growth_investment=0.5,
               book=book, book_charged=charged, horizon=20, base_year=2025)
    flows = {f["year"]: f for f in got["flows"]}
    combined = {y: book[y] + flows[y]["revenue"] for y in years}
    for y in years[1:]:
        company = 0.5 * charged.get(y, 0.0) + flows[y]["growth_investment"]
        assert company == pytest.approx(0.5 * max(0.0, combined[y] - combined[y - 1])), y
    # The years the launches refill the fall are charged only the company's own growth.
    assert flows[2031]["growth_investment"] == pytest.approx(
        0.5 * max(0.0, combined[2031] - combined[2030]))
