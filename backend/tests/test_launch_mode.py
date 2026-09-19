"""A pipeline asset valued from a published peak and the average launch's climb."""

import pytest

import assumptions
import forecast

RAMP = [(0.0, 0.056), (0.25, 0.347), (0.5, 0.611), (0.75, 0.848), (1.0, 1.0)]


def test_revenue_climbs_to_the_peak_and_holds_there():
    got = forecast.launch_path(1000.0, 4, 8, RAMP)
    assert got[0] == pytest.approx(56.0)            # a launch year is a part year
    assert got[1] == pytest.approx(347.0)
    assert got[2] == pytest.approx(611.0)
    assert got[4] == pytest.approx(1000.0)
    assert got[5:] == [pytest.approx(1000.0)] * 3   # held, leaving LOE to take it down


def test_the_curve_is_interpolated_between_its_measured_points():
    got = forecast.launch_path(1000.0, 8, 9, RAMP)
    assert got[1] == pytest.approx(56.0 + (347.0 - 56.0) * 0.5)
    assert got[8] == pytest.approx(1000.0)


def test_a_missing_ramp_holds_at_the_peak_rather_than_guessing_a_shape():
    assert forecast.launch_path(500.0, 5, 3, []) == [500.0, 500.0, 500.0]


def test_the_mode_needs_a_peak_and_a_launch_year():
    scalars = {"therapy_mode": "launch", "cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1,
               "tax_rate": 0.2, "wacc": 0.08, "forecast_years": 12}
    with pytest.raises(forecast.ForecastError) as raised:
        forecast.build({"scalars": scalars, "indications": [], "loe": None, "actuals": []})
    missing = " ".join(raised.value.missing)
    assert "peak_revenue_musd" in missing and "forecast_start_year" in missing


def test_the_engine_builds_a_launch_from_its_peak():
    scalars = {"therapy_mode": "launch", "peak_revenue_musd": 2000.0,
               "forecast_start_year": 2028, "forecast_years": 14, "years_to_peak": 4,
               "cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1, "tax_rate": 0.2,
               "wacc": 0.08, "terminal_growth_pct": 0.0}
    got = forecast.build({"scalars": scalars, "indications": [], "loe": None, "actuals": [],
                          "launch_ramp": {"curve": RAMP, "products": 41, "years_to_peak": 9},
                          "is_marketed": False, "phase": "Phase 3",
                          "therapeutic_area": "Oncology",
                          "pos_by_area": assumptions.pos_by_area(),
                          "loe_defaults": assumptions.loe_defaults(),
                          "erosion_defaults": assumptions.erosion_defaults()})
    # Risked at oncology's own published rate, not the book's old single number.
    assert got["pos"] == pytest.approx(0.439)
    assert got["revenue"][0] == pytest.approx(112.0)
    assert max(got["revenue"]) == pytest.approx(2000.0)
    assert got["rnpv"] > 0
    assert any("launch mode" in n for n in got["notes"])
    # An unlaunched product with no date on file still loses exclusivity on the statute.
    assert got["loe_year"] is not None and got["loe_year"] > 2028


def test_the_measured_ramp_on_file_is_read():
    ramp = assumptions.launch_ramp()
    assert ramp["products"] >= 40 and ramp["years_to_peak"] == 9
    assert ramp["curve"][0][0] == 0.0 and ramp["curve"][-1] == (1.0, 1.0)
    assert 0.0 < ramp["curve"][0][1] < 0.1        # a part year at launch


def test_a_marketed_product_with_no_date_takes_the_statute_from_its_own_approval():
    """Sixty-six marketed products had no exclusivity on file and ran flat for ever.
    Novo's insulin aspart was approved in 2000, so the statute puts it long past."""
    scalars = {"therapy_mode": "marketed", "base_revenue": 1000.0,
               "revenue_growth_pct": -0.05, "terminal_growth_pct": 0.0,
               "forecast_start_year": 2026, "forecast_years": 12, "pos": 1.0,
               "cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1, "tax_rate": 0.2, "wacc": 0.08}
    inputs = {"scalars": scalars, "indications": [], "loe": None, "actuals": [],
              "is_marketed": True, "modality": "biologic",
              "loe_defaults": assumptions.loe_defaults(),
              "erosion_defaults": assumptions.erosion_defaults()}
    past = forecast.build({**inputs, "approval_year": 2000})
    assert past["loe_year"] == 2012
    assert "2000 approval" in (past["loe_basis"] or "")
    assert any("in the base" in n for n in past["notes"])      # not eroded twice
    ahead = forecast.build({**inputs, "approval_year": 2017})
    assert ahead["loe_year"] == 2029 and ahead["rnpv"] < past["rnpv"]
    # No approval year and already selling: nothing to date it from, as before.
    assert forecast.build({**inputs, "approval_year": None})["loe_year"] is None
