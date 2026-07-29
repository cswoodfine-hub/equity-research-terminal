"""R&D productivity, and the metrics the free data cannot carry.

The interesting tests here are the refusals. Every number on this panel is a ratio, and
a ratio computed over a denominator that is partly not what it claims to be looks
authoritative and is wrong. The revenue table stores what a filing disaggregates, which
includes grants, royalties and segment labels, so the guard on coverage is doing more
work than the arithmetic is.
"""

import datetime as dt

import pytest

import db
import productivity


TODAY = dt.date(2026, 7, 29)


def _co(conn, ticker, name="Test Pharma"):
    conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (ticker, name))
    return conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]


def _asset(conn, cid, brand, marketed=1):
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, ?, ?)", (cid, brand, marketed))
    return conn.execute("SELECT id FROM assets WHERE brand_name = ?", (brand,)).fetchone()[0]


def _revenue(conn, asset_id, value, year=2025, unit="USD"):
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, value, unit,"
                 "  source) VALUES (?, ?, ?, ?, 'test')", (asset_id, year, value, unit))


def _approval(conn, asset_id, date):
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                 "  application_number, source) VALUES (?, 'US', 'FDA', ?, 'X', 'test')",
                 (asset_id, date))


def _commercial(conn, cid):
    """Inventory is what marks a company as selling something."""
    conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                 "  period_type, unit) VALUES (?, 'Inventory', 1e8, '2025-12-31',"
                 "  'instant', 'USD')", (cid,))


@pytest.fixture()
def path(tmp_path):
    p = str(tmp_path / "t.db")
    db.init(p)
    return p


def test_freshness_is_revenue_from_recent_approvals(path):
    conn = db.get_connection(path)
    cid = _co(conn, "AAA")
    _commercial(conn, cid)
    new = _asset(conn, cid, "NewDrug")
    old = _asset(conn, cid, "OldDrug")
    _approval(conn, new, "2024-03-01")
    _approval(conn, old, "2009-05-01")
    _revenue(conn, new, 750e6)
    _revenue(conn, old, 250e6)
    conn.commit()
    conn.close()
    row = productivity.build(path, today=TODAY)[0]
    assert row["fresh_share"] == pytest.approx(0.75)
    assert row["fresh_coverage"] == pytest.approx(1.0)


def test_a_non_product_revenue_line_is_excluded_not_counted_as_old(path):
    """Moderna's revenue rows are "Grant", "License And Royalty" and "COVID 19". None is
    a drug and none can carry an approval date, and dividing by them reported a company
    whose entire business post-dates 2021 as earning nothing from recent approvals."""
    conn = db.get_connection(path)
    cid = _co(conn, "BBB")
    _commercial(conn, cid)
    drug = _asset(conn, cid, "RecentDrug")
    grant = _asset(conn, cid, "Grant", marketed=0)
    _approval(conn, drug, "2023-01-01")
    _revenue(conn, drug, 900e6)
    _revenue(conn, grant, 100e6)
    conn.commit()
    conn.close()
    row = productivity.build(path, today=TODAY)[0]
    # The grant leaves the base entirely rather than sitting in it as an undatable
    # drug, so coverage is full and the share is not dragged down by it.
    assert row["fresh_share"] == pytest.approx(1.0)
    assert row["fresh_coverage"] == pytest.approx(1.0)
    assert row["non_product_revenue"] == pytest.approx(100e6)


def test_freshness_is_refused_when_too_little_revenue_maps_to_a_drug(path):
    """A share computed on 28% of the revenue says more about the extractor than about
    the company, so it is not reported at all."""
    conn = db.get_connection(path)
    cid = _co(conn, "CCC")
    _commercial(conn, cid)
    drug = _asset(conn, cid, "OneDrug")
    # A franchise label is real product revenue whose drug the filing did not name. It
    # stays in the base and cannot be dated, which is exactly what should push coverage
    # below the line and withhold the figure.
    franchise = _asset(conn, cid, "Shingles", marketed=1)
    _approval(conn, drug, "2024-01-01")
    _revenue(conn, drug, 200e6)
    _revenue(conn, franchise, 800e6)
    conn.commit()
    conn.close()
    row = productivity.build(path, today=TODAY)[0]
    assert row["fresh_share"] is None
    assert "20%" in row["fresh_reason"]


def test_no_product_revenue_reports_a_reason_not_a_zero(path):
    conn = db.get_connection(path)
    cid = _co(conn, "DDD")
    _commercial(conn, cid)
    conn.commit()
    conn.close()
    row = productivity.build(path, today=TODAY)[0]
    assert row["fresh_share"] is None
    assert row["fresh_reason"] == "no product revenue on file"


def test_foreign_currency_revenue_is_converted(path):
    """Novo reports in kroner. Left unconverted it showed 224bn of revenue against
    Lilly's 65bn and would have ranked the universe by exchange rate."""
    conn = db.get_connection(path)
    cid = _co(conn, "EEE")
    _commercial(conn, cid)
    drug = _asset(conn, cid, "KroneDrug")
    _approval(conn, drug, "2024-01-01")
    _revenue(conn, drug, 700e6, unit="DKK")
    conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of, source)"
                 " VALUES ('DKK', 'USD', 0.15, '2026-07-01', 'test')")
    conn.commit()
    conn.close()
    row = productivity.build(path, today=TODAY)[0]
    assert row["dated_revenue"] == pytest.approx(105e6)


def test_clinical_stage_companies_are_excluded(path):
    """With no product revenue there is no freshness to measure and no approvals to
    divide by. Those companies are read on the runway view instead."""
    conn = db.get_connection(path)
    _co(conn, "BIO")          # no inventory, so clinical-stage
    conn.commit()
    conn.close()
    assert productivity.build(path, today=TODAY) == []


def test_rd_per_approval_is_none_without_approvals(path):
    """Dividing by zero approvals is not an infinitely unproductive company."""
    conn = db.get_connection(path)
    cid = _co(conn, "FFF")
    _commercial(conn, cid)
    conn.execute("INSERT INTO financials (company_id, metric, value, period_end,"
                 "  period_type, fiscal_year, unit) VALUES (?,"
                 "  'ResearchAndDevelopmentExpense', 1e9, '2025-12-31', 'FY', 2025, 'USD')",
                 (cid,))
    conn.commit()
    conn.close()
    row = productivity.build(path, today=TODAY)[0]
    assert row["approvals_window"] == 0
    assert row["rd_per_approval"] is None


def test_ranking_puts_the_unmeasurable_last(path):
    """A company whose freshness cannot be computed is not the least productive one."""
    conn = db.get_connection(path)
    good = _co(conn, "GOOD")
    _commercial(conn, good)
    a = _asset(conn, good, "G1")
    _approval(conn, a, "2024-01-01")
    _revenue(conn, a, 1e9)
    blank = _co(conn, "BLANK")
    _commercial(conn, blank)
    conn.commit()
    conn.close()
    assert [r["ticker"] for r in productivity.build(path, today=TODAY)] == ["GOOD", "BLANK"]


# --- the two composite scores ---------------------------------------------------------

def _scored(**kw):
    """A row shaped like build() output, with every scorecard input present."""
    base = {"ticker": "AAA", "name": "A", "fresh_share": 0.2, "approvals_window": 5,
            "late_share": 0.4, "revenue_growth": 0.05, "net_margin": 0.2}
    return {**base, **kw}


def _comps(*tickers, growth=0.05, margin=0.2):
    return [{"ticker": t, "revenue_growth": growth, "net_margin": margin}
            for t in tickers]


def test_scores_are_relative_to_the_companies_on_the_chart(tmp_path):
    """Standardising over every company the build returned let a micro-cap posting
    2,900% growth set the scale, which pushed Lilly's 45% to the group mean and
    collapsed the plotted names into a smudge at the origin."""
    p = str(tmp_path / "t.db")
    db.init(p)
    rows = [
        _scored(ticker="HIGH", revenue_growth=0.45),
        _scored(ticker="MID", revenue_growth=0.05),
        _scored(ticker="LOW", revenue_growth=-0.05),
        # Present in the build and unplaceable, with an extreme value that must not
        # be allowed to set the scale for the three above.
        _scored(ticker="WILD", revenue_growth=29.0, fresh_share=None),
    ]
    comps = [{"ticker": r["ticker"], "revenue_growth": r["revenue_growth"],
              "net_margin": r["net_margin"]} for r in rows]
    placed = productivity.scorecard(p, today=TODAY, rows=rows, comps_rows=comps)
    by = {r["ticker"]: r for r in placed}
    assert set(by) == {"HIGH", "MID", "LOW"}
    assert by["HIGH"]["commercial_score"] > 0.5, "the outlier among peers must stand out"
    assert by["LOW"]["commercial_score"] < 0


def test_a_company_missing_an_input_is_not_placed(tmp_path):
    """A composite over whatever happened to be present would rank a company on two
    measures against another on five."""
    p = str(tmp_path / "t.db")
    db.init(p)
    rows = [_scored(ticker="FULL"), _scored(ticker="PART", late_share=None),
            _scored(ticker="OTHER")]
    placed = productivity.scorecard(p, today=TODAY, rows=rows,
                                    comps_rows=_comps("FULL", "PART", "OTHER"))
    assert {r["ticker"] for r in placed} == {"FULL", "OTHER"}


def test_quadrants_follow_the_two_scores(tmp_path):
    p = str(tmp_path / "t.db")
    db.init(p)
    rows = [
        _scored(ticker="BOTH", fresh_share=0.9, approvals_window=20, late_share=0.9),
        _scored(ticker="NEITHER", fresh_share=0.0, approvals_window=0, late_share=0.0),
    ]
    comps = [{"ticker": "BOTH", "revenue_growth": 0.5, "net_margin": 0.4},
             {"ticker": "NEITHER", "revenue_growth": -0.1, "net_margin": 0.05}]
    by = {r["ticker"]: r for r in
          productivity.scorecard(p, today=TODAY, rows=rows, comps_rows=comps)}
    assert by["BOTH"]["quadrant"] == "Both"
    assert by["NEITHER"]["quadrant"] == "Neither"


def test_a_z_score_is_clipped_so_one_company_cannot_flatten_the_rest(tmp_path):
    p = str(tmp_path / "t.db")
    db.init(p)
    rows = [_scored(ticker=f"C{i}", revenue_growth=0.05) for i in range(8)]
    rows.append(_scored(ticker="OUT", revenue_growth=50.0))
    comps = [{"ticker": r["ticker"], "revenue_growth": r["revenue_growth"],
              "net_margin": 0.2} for r in rows]
    by = {r["ticker"]: r for r in
          productivity.scorecard(p, today=TODAY, rows=rows, comps_rows=comps)}
    # 0.6 weight on a z clipped at 3.
    assert by["OUT"]["commercial_score"] <= 0.6 * productivity.Z_CLIP + 1e-9


def test_identical_companies_all_score_zero(tmp_path):
    """No spread means no ranking, and dividing by a zero standard deviation would
    otherwise raise rather than say so."""
    p = str(tmp_path / "t.db")
    db.init(p)
    rows = [_scored(ticker="A"), _scored(ticker="B")]
    placed = productivity.scorecard(p, today=TODAY, rows=rows,
                                    comps_rows=_comps("A", "B"))
    assert all(r["rd_score"] == 0 and r["commercial_score"] == 0 for r in placed)
