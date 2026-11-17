"""An asset's cash profile: the curve, the return and the payback, beside the value."""

import pathlib

import pytest

import cash_profile as C
import development as D

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def test_the_return_is_the_rate_at_which_the_flows_net_to_nil():
    # 100 out, 110 back a year later
    assert C.irr([(0.5, -100.0), (1.5, 110.0)]) == pytest.approx(0.10, abs=1e-6)
    # no outlay, or nothing back: no return to state
    assert C.irr([(0.5, 10.0), (1.5, 10.0)]) is None
    assert C.irr([(0.5, -10.0), (1.5, -10.0)]) is None
    assert C.irr([]) is None


def test_a_return_above_the_bracket_is_said_not_stated():
    flows = [(0.5, -1.0), (1.5, 1000.0)]            # a thousand-fold in a year
    assert C.irr(flows) is None and C.irr_above(flows)
    assert not C.irr_above([(0.5, -100.0), (1.5, 110.0)])
    assert not C.irr_above([(0.5, 10.0), (1.5, 10.0)])


def test_the_curve_the_trough_and_the_payback_year():
    years = [2026, 2027, 2028, 2029, 2030]
    case = C._case(years, outlay=[50.0, 30.0, 0.0, 0.0, 0.0],
                   cash=[0.0, 0.0, 40.0, 60.0, 80.0], terminal=0.0)
    assert case["net"] == [-50.0, -30.0, 40.0, 60.0, 80.0]
    assert case["cumulative"] == [-50.0, -80.0, -40.0, 20.0, 100.0]
    assert case["deepest"] == -80.0 and case["deepest_year"] == 2027
    assert case["payback_year"] == 2029
    assert case["irr"] is not None and case["irr"] > 0


def test_cash_that_never_goes_negative_has_no_trough_and_no_payback():
    case = C._case([2027, 2028], outlay=[0.0, 0.0], cash=[10.0, 12.0], terminal=5.0)
    assert case["deepest"] is None and case["payback_year"] is None and case["irr"] is None


def test_an_outlay_never_earned_back_inside_the_window_says_so():
    case = C._case([2026, 2027], outlay=[100.0, 0.0], cash=[0.0, 10.0], terminal=0.0)
    assert case["payback_year"] is None and case["deepest"] == -100.0


def test_the_terminal_value_counts_in_the_return_not_in_the_curve():
    years = [2026, 2027]
    without = C._case(years, [100.0, 0.0], [0.0, 60.0], terminal=0.0)
    with_tv = C._case(years, [100.0, 0.0], [0.0, 60.0], terminal=80.0)
    assert without["cumulative"] == with_tv["cumulative"]
    assert without["irr"] < 0 < with_tv["irr"]


def test_spend_is_laid_out_by_year_with_the_chance_each_stage_is_entered():
    import datetime as dt
    stages = [
        {"gate": "p3_to_nda", "label": "Phase 3 readout", "p": 0.6,
         "spend": [(120.0, dt.date(2026, 7, 1), dt.date(2027, 7, 1))]},
        {"gate": "nda_to_approval", "label": "FDA decision", "p": 0.9,
         "spend": [(2.6, dt.date(2028, 3, 1), dt.date(2028, 3, 1))]},
    ]
    got = D.spend_by_year(stages, to_ccy=1.0, keep=0.8)
    assert [s["p_enter"] for s in got] == [1.0, 0.6]
    first = got[0]["years"]
    assert set(first) == {2026, 2027}
    assert sum(first.values()) == pytest.approx(120.0 * 0.8)
    assert got[1]["years"] == {2028: pytest.approx(2.6 * 0.8)}
    # a stage whose cost cannot be read leaves the whole profile unread, never cheaper
    assert D.spend_by_year(stages + [{"unread": True, "p": 1.0, "spend": []}],
                           to_ccy=1.0, keep=1.0) is None


def test_the_profile_is_a_view_beside_the_value():
    """Nothing on the value path imports it, as nothing imports development."""
    for name in ("forecast", "assumptions", "forecast_view", "company_score", "breakpoints",
                 "fair_value"):
        source = (BACKEND / f"{name}.py").read_text()
        assert "import cash_profile" not in source, name
