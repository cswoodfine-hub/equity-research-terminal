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
