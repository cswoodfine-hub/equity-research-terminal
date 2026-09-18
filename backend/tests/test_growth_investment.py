"""What the growth a forecast carries costs in capital."""

import pytest

import db
import forecast
import growth_investment as GI

MM = 1e6


def _company(conn, cid, ticker, years, revenue, capex, depreciation, receivables=0.0):
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)", (cid, ticker, ticker))
    for i, year in enumerate(years):
        for metric, value in (("Revenues", revenue[i]), ("CapitalExpenditure", capex[i]),
                              ("Depreciation", depreciation[i]),
                              ("ReceivablesCashEffect", receivables)):
            conn.execute(
                "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
                " unit, fiscal_year) VALUES (?, ?, 'FY', ?, ?, 'USD', ?)",
                (cid, f"{year}-12-31", metric, value * MM, year))


def _db(tmp_path):
    path = str(tmp_path / "gi.db")
    db.init(path)
    return db.get_connection(path)


def test_a_filers_growth_investment_is_capex_above_depreciation_plus_the_build(tmp_path):
    conn = _db(tmp_path)
    years = list(range(2011, 2016))
    _company(conn, 1, "LLY", years, [100, 120, 140, 160, 200], [30] * 5, [10] * 5, receivables=-5.0)
    conn.commit()
    got = GI.filer(conn, 1, first=2012, last=2015)
    assert got["capex_gap"] == pytest.approx(80 * MM)     # four years at 20
    assert got["wc_build"] == pytest.approx(20 * MM)      # four years at 5
    assert got["added"] == pytest.approx(100 * MM)        # 200 against 100
    assert got["intensity"] == pytest.approx(1.0)
    conn.close()


def test_a_filer_whose_revenue_fell_sets_no_rate(tmp_path):
    conn = _db(tmp_path)
    _company(conn, 1, "PFE", list(range(2011, 2016)), [200, 190, 180, 170, 160], [30] * 5, [10] * 5)
    conn.commit()
    got = GI.filer(conn, 1, first=2012, last=2015)
    assert got["intensity"] is None and got["reason"] == "revenue fell over the window"
    conn.close()


def test_the_pool_is_weighted_by_the_revenue_each_filer_added(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(GI.IA, "WINDOWS", {"AAA": (2023, 2025), "BBB": (2023, 2025)})
    years = list(range(2011, 2016))
    _company(conn, 1, "AAA", years, [100, 120, 140, 160, 200], [30] * 5, [10] * 5)   # 0.8 on 100
    _company(conn, 2, "BBB", years, [100, 200, 300, 400, 500], [30] * 5, [10] * 5)   # 0.2 on 400
    conn.commit()
    pool = GI.pooled(conn, refresh=True)
    assert pool["capex"] == pytest.approx(160 / 500)      # both filers' gap over both filers' growth
    assert pool["working_capital"] == pytest.approx(0.0)
    assert pool["counted"] == 2
    conn.close()


def test_a_charge_that_still_carries_full_capex_takes_the_build_alone(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(GI, "pooled", lambda conn, refresh=False: {
        "intensity": 0.5, "capex": 0.3, "working_capital": 0.2, "counted": 13, "added": 1e11})
    both = GI.for_company(conn, "LLY", "Restated at replacement capex: ... Restated without working capital build: ...")
    build_only = GI.for_company(conn, "PFE", "Checked at replacement capex: no plant depreciation. Restated without working capital build: ...")
    neither = GI.for_company(conn, "XXX", "Checked at replacement capex. Checked without working capital build.")
    assert both["value"] == pytest.approx(0.5)
    assert build_only["value"] == pytest.approx(0.2)
    assert neither["value"] == 0.0
    conn.close()


def test_the_engine_charges_it_on_revenue_added_and_not_on_revenue():
    scalars = {"cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1, "tax_rate": 0.0,
               "other_costs_pct": 0.0}
    rows = forecast.fcff([100.0, 150.0, 150.0, 120.0], [0, 0, 0, 0], scalars, "marketed",
                         opening=100.0, growth_investment=0.5)
    assert [r["growth_investment"] for r in rows] == [0.0, 25.0, 0.0, 0.0]
    assert rows[0]["fcff"] == pytest.approx(50.0)          # nothing added, nothing charged
    assert rows[1]["fcff"] == pytest.approx(75.0 - 25.0)   # half of the 50 it added
    assert rows[3]["fcff"] == pytest.approx(60.0)          # a fall is not a credit


def test_a_product_may_state_its_own_share():
    scalars = {"cogs_pct": 0.0, "sga_pct": 0.0, "rd_pct": 0.0, "tax_rate": 0.0,
               "other_costs_pct": 0.0, "growth_investment_pct": 0.0}
    rows = forecast.fcff([100.0, 200.0], [0, 0], scalars, "marketed", opening=100.0,
                         growth_investment=0.5)
    assert [r["growth_investment"] for r in rows] == [0.0, 0.0]


def test_the_rebuild_reads_the_books_own_ratios_not_one_products(tmp_path):
    """A company that costs its segments apart has no single product ratio to read."""
    import charge_floor
    path = str(tmp_path / "cf.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'JNJ', 'J&J')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Drug', 1), (2, 1, 'Device', 1)")
    for aid, revenue in ((1, 9000.0), (2, 1000.0)):
        conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value, unit,"
                     " source) VALUES (?, 2025, 'FY', ?, 'USD', 't')", (aid, revenue * MM))
    for aid, cogs in ((1, 0.25), (2, 0.45)):
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                     " VALUES (?, 'US', 'base', 'cogs_pct', ?)", (aid, cogs))
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                     " VALUES (?, 'US', 'base', 'sga_pct', 0.2)", (aid,))
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value)"
                     " VALUES (?, 'US', 'base', 'rd_pct', 0.1)", (aid,))
    conn.commit()
    got = charge_floor._weighted(conn, 1)
    assert got["cogs_pct"] == pytest.approx(0.25 * 0.9 + 0.45 * 0.1)
    assert got["sga_pct"] == pytest.approx(0.2)
    conn.close()


def test_other_revenues_are_read_for_the_filers_that_report_them(tmp_path):
    import charge_floor
    path = tmp_path / "other.csv"
    path.write_text("# a comment\nticker,fiscal_year,other_revenues_mm,unit,accession,quote\n"
                    "SNY,2025,3090,EUR,acc,\"quote\"\nSNY,2024,3205,EUR,acc,\"quote\"\n",
                    encoding="utf-8")
    assert charge_floor.other_revenues("SNY", path) == {2025: 3090 * MM, 2024: 3205 * MM}
    assert charge_floor.other_revenues("LLY", path) == {}
    assert charge_floor.extra_unit("SNY", path) == "EUR"
