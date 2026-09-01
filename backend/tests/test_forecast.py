"""The forecast engine, tested against the CASGEVY workbook's own computed values.

The milestone for Build 1 is reproducing CASGEVY_DCF_Model_v2.xlsx inside the terminal.
The targets below were read out of the workbook with data_only=True, so they are what the
spreadsheet itself computed, not a re-derivation: any drift between engine and reference
fails here first.
"""

import pytest

import forecast as F

# The workbook's hand-typed patient curves, revenue build row 6 and row 12.
SCD = {2024: 5, 2025: 45, 2026: 120, 2027: 200, 2028: 320, 2029: 450,
       2030: 550, 2031: 600, 2032: 550, 2033: 480, 2034: 400, 2035: 350}
TDT = {2024: 0, 2025: 19, 2026: 50, 2027: 80, 2028: 130, 2029: 180,
       2030: 220, 2031: 240, 2032: 220, 2033: 190, 2034: 160, 2035: 140}

SCALARS = {
    "therapy_mode": "one_time",
    "net_price_per_patient": 1.8, "cogs_per_patient": 0.75,
    "sga_pct": 0.20, "rd_pct": 0.10, "tax_rate": 0.15,
    "risk_free": 0.0437, "erp": 0.05, "beta": 1.15,
    "cost_of_debt": 0.055, "debt_weight": 0.05,
    "pos_regulatory": 1.0, "pos_launch": 1.0,
    "pos_reimbursement": 0.95, "pos_durability": 0.85,
    "terminal_growth": 0, "terminal_mode": "perpetuity",
    "economics_share": 0.6,
    "forecast_start_year": 2026, "forecast_years": 10,
}


def casgevy_inputs(**overrides):
    scalars = dict(SCALARS)
    scalars.update(overrides.pop("scalars", {}))
    inputs = {
        "scalars": scalars,
        "indications": [
            {"name": "Anemia, Sickle Cell", "scalars": {},
             "series": {"new_patients": dict(SCD)}},
            {"name": "beta-Thalassemia", "scalars": {},
             "series": {"new_patients": dict(TDT)}},
        ],
        "loe": {"year": 2035, "basis": "reference product exclusivity (12y)"},
        "actuals": [{"fiscal_year": 2025, "period": "FY", "value": 115.8},
                    {"fiscal_year": 2026, "period": "H1", "value": 76.4}],
    }
    inputs.update(overrides)
    return inputs


# --- the milestone: the workbook, reproduced --------------------------------

def test_the_workbook_revenue_series_is_reproduced_exactly():
    got = F.build(casgevy_inputs())
    assert got["years"] == list(range(2024, 2036))
    assert [round(v, 1) for v in got["revenue"]] == \
        [9.0, 115.2, 306.0, 504.0, 810.0, 1134.0, 1386.0, 1512.0,
         1386.0, 1206.0, 1008.0, 882.0]


def test_the_workbook_wacc_is_derived_from_its_capm_components():
    got = F.build(casgevy_inputs())
    assert got["wacc"] == pytest.approx(0.0984775, abs=1e-9)
    assert got["wacc_basis"] == "CAPM from components"


def test_the_workbook_composite_pos():
    got = F.build(casgevy_inputs())
    assert got["pos"] == pytest.approx(0.8075, abs=1e-9)
    assert got["pos_basis"] == "composite factors"


def test_the_workbook_valuation_to_the_dollar():
    """Base NPV 2,367.46; rNPV 1,911.72; PV of FCFFs 1,483.70; PV of terminal 883.76.
    All read from the workbook's own cells with data_only=True."""
    got = F.build(casgevy_inputs())
    assert got["pv_fcff"] == pytest.approx(1483.70, abs=0.5)
    assert got["terminal_pv"] == pytest.approx(883.76, abs=0.5)
    assert got["npv"] == pytest.approx(2367.46, abs=0.5)
    assert got["rnpv"] == pytest.approx(1911.72, abs=0.5)


def test_the_economics_split_matches_the_workbook():
    """Vertex 60% = 1,147.03 (row 43) and CRISPR 40% = 764.69 (row 44), both read from
    the workbook's own cached cells. An earlier read of this block was off by one row
    and called the CRISPR cell a stale cache; it never was, and this pins the truth."""
    got = F.build(casgevy_inputs())
    assert got["owner_rnpv"] == pytest.approx(1147.03, abs=0.5)
    assert got["partner_rnpv"] == pytest.approx(764.69, abs=0.5)


def test_calibration_prefers_the_filed_figure_to_the_workbook_estimate():
    """The workbook calibrated against a 95m estimate for 2025. The terminal holds the
    10-K figure, 115.8, and the model was within half a percent of it."""
    got = F.build(casgevy_inputs())
    fy = next(r for r in got["calibration"] if r["period"] == "FY")
    assert fy["reported"] == 115.8
    assert fy["variance_pct"] == pytest.approx(-0.0052, abs=0.001)
    assert any(r["period"] == "H1" for r in got["calibration"])


# --- the pool identity ------------------------------------------------------

def flat(_):
    return 0.05


def test_the_pool_never_goes_negative_and_nothing_treats_more_than_exists():
    series = F.derive_new_patients(pool=100, incidence=0,
                                   penetration=lambda i: 0.9, years=10)
    assert all(v >= 0 for v in series)
    assert sum(series) <= 100 + 1e-9


def test_the_tail_converges_on_the_incidence_run_rate():
    """The Zolgensma shape: a one-time therapy depletes its prevalent pool and then runs
    at incidence. The workbook draws that hump by hand; here it is arithmetic."""
    series = F.derive_new_patients(pool=10000, incidence=200,
                                   penetration=lambda i: 0.5, years=30)
    assert series[-1] == pytest.approx(0.5 * (200 / 0.5), rel=0.05)
    peak = max(series)
    assert series.index(peak) < 5 and series[-1] < peak / 3


def test_capacity_binds_when_it_is_lower_than_demand():
    series = F.derive_new_patients(pool=10000, incidence=0,
                                   penetration=lambda i: 0.5, years=3,
                                   capacity=[100, 100, None])
    assert series[0] == 100 and series[1] == 100
    assert series[2] > 100      # unconstrained year reverts to the funnel


def test_an_explicit_series_beats_the_derived_curve_and_both_are_returned():
    ind = {"name": "x",
           "scalars": {"prevalence": 1000, "eligible_pct": 0.5, "incidence": 10,
                       "penetration_peak_pct": 0.1, "ramp_midpoint_year": 2,
                       "ramp_steepness": 1.0},
           "series": {"new_patients": {2026: 7, 2027: 8}}}
    notes = []
    got = F.patients_for_indication(ind, [2026, 2027], notes)
    assert got["used"] == [7.0, 8.0]
    assert got["basis"] == "analyst series"
    assert got["derived"] is not None       # shown beside, never silently dropped


def test_derived_mode_without_incidence_reports_itself_unavailable():
    ind = {"name": "TDT", "scalars": {"prevalence": 3000, "eligible_pct": 0.5},
           "series": {}}
    notes = []
    got = F.patients_for_indication(ind, [2026], notes)
    assert got["used"] is None
    assert any("incidence" in n for n in notes)


# --- refusals: nothing is invented ------------------------------------------

def test_a_missing_required_assumption_is_refused_by_name():
    inputs = casgevy_inputs()
    del inputs["scalars"]["net_price_per_patient"]
    with pytest.raises(F.ForecastError) as err:
        F.build(inputs)
    assert "net_price_per_patient" in str(err.value)


def test_a_wacc_with_no_components_is_refused():
    inputs = casgevy_inputs()
    for key in ("risk_free", "erp", "beta", "cost_of_debt", "debt_weight"):
        del inputs["scalars"][key]
    with pytest.raises(F.ForecastError) as err:
        F.build(inputs)
    assert "wacc" in str(err.value)


def test_no_patient_series_at_all_is_refused():
    inputs = casgevy_inputs()
    for ind in inputs["indications"]:
        ind["series"] = {}
    with pytest.raises(F.ForecastError):
        F.build(inputs)


def test_pos_with_no_factors_no_value_and_no_phase_is_refused():
    inputs = casgevy_inputs()
    for key in ("pos_regulatory", "pos_launch", "pos_reimbursement", "pos_durability"):
        del inputs["scalars"][key]
    with pytest.raises(F.ForecastError) as err:
        F.build(inputs)
    assert "pos" in str(err.value)


def test_a_pipeline_asset_takes_the_curated_phase_ramp_and_says_so():
    inputs = casgevy_inputs(phase="Phase 3",
                            pos_defaults={"Phase 3": {"pos": 0.65, "source": "BIO"}})
    for key in ("pos_regulatory", "pos_launch", "pos_reimbursement", "pos_durability"):
        del inputs["scalars"][key]
    got = F.build(inputs)
    assert got["pos"] == 0.65
    assert "phase default" in got["pos_basis"] and "BIO" in got["pos_basis"]


# --- erosion ----------------------------------------------------------------

def test_erosion_starts_the_year_after_loe_and_decays_the_remainder():
    revenue = [100.0] * 5
    got = F.erode(revenue, [2030, 2031, 2032, 2033, 2034], loe_year=2031,
                  year1_pct=0.6, decay_pct=0.5)
    assert got[0] == 100 and got[1] == 100          # at or before LOE untouched
    assert got[2] == pytest.approx(40.0)            # year one: -60%
    assert got[3] == pytest.approx(20.0)            # then half the remainder
    assert got[4] == pytest.approx(10.0)


def test_an_loe_beyond_the_horizon_erodes_nothing_and_says_so():
    got = F.build(casgevy_inputs())
    assert got["revenue_after_loe"] == got["revenue"]
    assert any("no erosion applies" in n for n in got["notes"])


def test_an_loe_inside_the_horizon_cuts_the_valuation():
    base = F.build(casgevy_inputs())
    early = F.build(casgevy_inputs(
        scalars={"loe_year": 2030, "erosion_year1_pct": 0.6,
                 "erosion_decay_pct": 0.35}))
    assert early["loe_basis"] == "assumed"
    assert early["rnpv"] < base["rnpv"] * 0.8


def test_a_curated_erosion_default_carries_its_source():
    got = F.build(casgevy_inputs(
        scalars={"loe_year": 2030}, modality="small molecule",
        erosion_defaults={"small molecule": {
            "year1_pct": 0.6, "decay_pct": 0.35, "source": "FDA/ASPE"}}))
    assert "curated default" in got["erosion_basis"]
    assert "FDA/ASPE" in got["erosion_basis"]


# --- sensitivity ------------------------------------------------------------

def test_the_grid_moves_the_right_way_on_both_axes():
    grid = F.sensitivity(casgevy_inputs(), "wacc", [0.08, 0.10, 0.12],
                         "net_price_per_patient", [1.4, 1.8, 2.2])
    assert len(grid["grid"]) == 3 and len(grid["grid"][0]) == 3
    for row in grid["grid"]:                        # higher wacc, lower rnpv
        assert row[0] > row[1] > row[2]
    for i in range(3):                              # higher price, higher rnpv
        assert grid["grid"][0][i] < grid["grid"][1][i] < grid["grid"][2][i]


def test_a_cell_the_engine_refuses_is_none_not_a_guess():
    inputs = casgevy_inputs()
    grid = F.sensitivity(inputs, "wacc", [0.10], "therapy_mode", ["nonsense"])
    assert grid["grid"] == [[None]]


def test_the_loe_by_erosion_preset_spans_the_question_that_cannot_be_pinned():
    """The roadmap's mandate: neither the date nor the steepness can be evidenced, so
    the model's output here is a range, and the grid is the deliverable."""
    grid = F.sensitivity(
        casgevy_inputs(scalars={"erosion_decay_pct": 0.2}),
        "loe_year", [2030, 2032, 2034],
        "erosion_year1_pct", [0.25, 0.60])
    for row in grid["grid"]:                        # later LOE is worth more
        assert row[0] < row[1] < row[2]
    for i in range(3):                              # gentler year one is worth more
        assert grid["grid"][0][i] >= grid["grid"][1][i]


def test_incidence_passes_the_same_eligibility_filter_as_the_pool():
    """2,000 sickle cell births a year are not 2,000 patients with two crises a year
    aged twelve or more. Feeding raw births into the eligible pool overstated the inflow
    six-fold and the derived curve climbed forever instead of humping."""
    ind = {"name": "SCD",
           "scalars": {"prevalence": 100000, "eligible_pct": 0.16, "incidence": 2000,
                       "exus_multiple": 1.5, "penetration_peak_pct": 0.5,
                       "ramp_midpoint_year": 0, "ramp_steepness": 5.0},
           "series": {}}
    notes = []
    years = list(range(2024, 2074))
    got = F.patients_for_indication(ind, years, notes)
    # At a high, fast penetration the tail is the eligible inflow: 2000 x 16% x 2.5.
    assert got["derived"][-1] == pytest.approx(2000 * 0.16 * 2.5, rel=0.05)
    assert any("eligibility share" in n for n in notes)


# --- the what-if levers (forecast_view.whatif) -------------------------------

def test_whatif_levers(tmp_path):
    """Each slider is a real driver run through the same engine: volume scales revenue
    linearly, price moves it proportionally, WACC and PoS replace the derived values,
    and no overrides means no difference."""
    import db
    import assumptions as A
    import forecast_view as V
    path = str(tmp_path / "wi.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'VRTX', 'Vertex')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Casgevy', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Anemia, Sickle Cell')")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 1.8), ("cogs_per_patient", 0.75),
        ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15),
        ("wacc", 0.10), ("pos", 0.8), ("forecast_start_year", 2026),
        ("forecast_years", 3))]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    for year, patients in ((2026, 100), (2027, 200), (2028, 300)):
        rows.append({"key": "new_patients", "indication_id": 1, "year": year,
                     "value": patients, "source": "t"})
    A.save(conn, 1, rows)
    conn.commit(); conn.close()

    same = V.whatif(path, "VRTX", 1)
    assert same["base"]["rnpv"] == same["varied"]["rnpv"]

    volume = V.whatif(path, "VRTX", 1, volume=0.5)
    assert volume["varied"]["revenue"] == pytest.approx(
        [v * 0.5 for v in volume["base"]["revenue"]])

    price = V.whatif(path, "VRTX", 1, price=0.9)
    assert price["varied"]["revenue"] == pytest.approx(
        [v * 0.5 for v in price["base"]["revenue"]])

    rate = V.whatif(path, "VRTX", 1, wacc=0.20)
    assert rate["varied"]["rnpv"] < rate["base"]["rnpv"]
    assert rate["varied"]["wacc"] == 0.20

    pos = V.whatif(path, "VRTX", 1, pos=0.4)
    assert pos["varied"]["rnpv"] == pytest.approx(pos["base"]["rnpv"] * 0.5)

    assert V.whatif(path, "LLY", 1) is None       # another company's asset


def test_a_stated_pos_outranks_the_factors_it_inherits():
    """A bear scenario writes one pos row of 0.65 and inherits the base factors beside
    it. The row means exactly that number, and must not lose to the inheritance."""
    inputs = casgevy_inputs(scalars={"pos": 0.65})
    got = F.build(inputs)
    assert got["pos"] == 0.65
    assert got["pos_basis"] == "stated"


# --- chronic accumulation --------------------------------------------------
# Both modes ran the same revenue line, and the pool identity that fed it computes new
# starts while depleting a prevalent pool. That is a one-time therapy's shape, and it
# understated every year after the first for a drug people take every week.

def test_the_stock_accumulates_when_nobody_stops():
    assert F.treated_stock([10] * 5, 0.0) == [10, 20, 30, 40, 50]


def test_the_stock_settles_where_starts_meet_departures():
    # 10 a year against half the stock leaving converges on 20, which is 10 / 0.5.
    stock = F.treated_stock([10] * 40, 0.5)
    assert abs(stock[-1] - 20.0) < 1e-6


def test_total_discontinuation_is_the_old_behaviour():
    """At 1.0 nobody carries over, so the stock is the year's new starts. That is exactly
    what chronic mode did before it had an accumulation of its own."""
    assert F.treated_stock([7, 9, 4], 1.0) == [7, 9, 4]


def test_an_opening_stock_separates_a_launch_from_a_product_already_selling():
    assert F.treated_stock([10] * 2, 0.2, opening=100) == [90.0, 82.0]
    assert F.treated_stock([10] * 2, 0.2) == [10.0, 18.0]


def _chronic(**overrides):
    scalars = {"therapy_mode": "chronic", "net_price_per_patient": 0.01,
               "wacc": 0.10, "forecast_start_year": 2027, "forecast_years": 5,
               "cogs_pct": 0.2, "sga_pct": 0.2, "rd_pct": 0.1, "tax_rate": 0.2,
               "pos": 1.0, "discontinuation_pct": 0.25}
    scalars.update(overrides)
    return {"scalars": scalars,
            "indications": [{"name": "X", "scalars": {},
                             "series": {"new_patients": {y: 100 for y in range(2027, 2032)}}}]}


def test_chronic_revenue_is_the_stock_not_the_starts():
    built = F.build(_chronic())
    starts = built["patients"]["total"]
    treated = built["patients"]["treated"]
    assert starts == [100] * 5
    # 100 starts a year at 25% attrition builds a stock that is larger every year.
    assert treated[0] == 100 and treated[1] == 175.0
    assert built["revenue"][1] > built["revenue"][0]
    # And revenue meets the stock, not the starts.
    assert abs(built["revenue"][1] - treated[1] * 0.01) < 1e-9


def test_chronic_without_a_discontinuation_rate_refuses_to_guess():
    try:
        F.build(_chronic(discontinuation_pct=None))
    except F.ForecastError as exc:
        assert any("discontinuation_pct" in m for m in exc.missing)
    else:
        raise AssertionError("chronic mode invented a persistence rate")


def test_a_one_time_therapy_is_untouched_by_any_of_this():
    """Casgevy is billed once. Its patients and its treated series are the same, and no
    discontinuation rate is asked for."""
    built = F.build({
        "scalars": {"therapy_mode": "one_time", "net_price_per_patient": 1.8,
                    "wacc": 0.10, "forecast_start_year": 2027, "forecast_years": 3,
                    "cogs_per_patient": 0.1, "sga_pct": 0.2, "rd_pct": 0.1,
                    "tax_rate": 0.2, "pos": 1.0},
        "indications": [{"name": "X", "scalars": {},
                         "series": {"new_patients": {2027: 10, 2028: 20, 2029: 30}}}]})
    assert built["patients"]["treated"] == built["patients"]["total"] == [10, 20, 30]
    assert built["revenue"] == [18.0, 36.0, 54.0]


# --- marketed products -----------------------------------------------------
# Nobody rebuilds the patient funnel for a drug already selling ten billion a year. The
# reported number is the anchor and growth is the judgement.

def _marketed(**over):
    scalars = {"therapy_mode": "marketed", "base_revenue": 10312.7,
               "revenue_growth_pct": 0.04, "wacc": 0.085,
               "forecast_start_year": 2026, "forecast_years": 10,
               "cogs_pct": 0.14, "sga_pct": 0.15, "rd_pct": 0.33, "tax_rate": 0.15,
               "pos": 1.0}
    scalars.update(over)
    return {"scalars": scalars, "indications": []}


def test_revenue_grows_from_what_was_reported():
    got = F.grown_revenue(100.0, 0.10, 3)
    assert [round(v, 6) for v in got] == [110.0, 121.0, 133.1]


def test_year_one_is_the_base_grown_once():
    """The base is last year's reported figure and the forecast starts after it."""
    assert F.grown_revenue(100.0, 0.05, 1) == [105.0]


def test_a_marketed_product_needs_no_patients_at_all():
    built = F.build(_marketed())
    assert built["mode"] == "marketed"
    assert built["patients"]["total"] == [None] * len(built["years"])
    assert built["revenue"][0] > 10312.7
    assert built["rnpv"] > 0


def test_it_refuses_to_guess_the_anchor_or_the_growth():
    for missing in ("base_revenue", "revenue_growth_pct"):
        try:
            F.build(_marketed(**{missing: None}))
        except F.ForecastError as exc:
            assert any(missing in m for m in exc.missing)
        else:
            raise AssertionError(f"marketed mode invented {missing}")


def test_a_marketed_product_does_not_ask_for_a_price():
    """A price per patient is the wrong question for a drug that files its own sales."""
    try:
        F.build(_marketed())
    except F.ForecastError as exc:
        assert not any("net_price" in m for m in exc.missing)


def test_exclusivity_still_erodes_a_marketed_product():
    plain = F.build(_marketed())
    eroded = F.build({**_marketed(erosion_year1_pct=0.6, erosion_decay_pct=0.3),
                      "loe": {"year": 2030, "basis": "test"}})
    assert eroded["rnpv"] < plain["rnpv"]
    assert eroded["loe_year"] == 2030
    assert eroded["revenue_after_loe"] != eroded["revenue"]


def test_an_loe_with_no_erosion_shape_erodes_nothing():
    """The engine will not invent a decay curve. An LOE year with no shape to apply, and
    no modality to take a curated default from, leaves the revenue alone: a gap that has
    to be visible rather than filled in."""
    built = F.build({**_marketed(), "loe": {"year": 2030, "basis": "test"}})
    assert built["loe_year"] == 2030
    assert built["erosion_basis"] is None
    assert built["revenue_after_loe"] == built["revenue"]


def test_without_an_loe_it_runs_to_the_horizon():
    built = F.build(_marketed())
    assert built["loe_year"] is None
    assert built["revenue_after_loe"] == built["revenue"]


# --- growth fades ----------------------------------------------------------
# A near-term rate is not a long-run one. Vertex guides the CF franchise to about 9.6%
# for one year; held flat to 2037 that is 31bn of Trikafta, close to three times the
# entire US CF population at its net price, and Journavx's launch rate held to 2043 is
# 570bn, larger than the industry.

def test_growth_held_flat_is_still_the_default():
    # Compounded step by step rather than raised to a power, so compare with tolerance.
    got = F.grown_revenue(100.0, 0.10, 3)
    assert [round(v, 6) for v in got] == [110.0, 121.0, 133.1]


def test_the_rate_decays_to_the_long_run_one():
    got = F.grown_revenue(100.0, 0.10, 7, fade_to=0.0, fade_years=5)
    steps = [b / a - 1 for a, b in zip([100.0] + got, got)]
    # Starts at the near-term rate, arrives at the long-run one, never goes back up.
    assert round(steps[0], 6) == 0.10
    assert round(steps[-1], 6) == 0.0
    assert steps == sorted(steps, reverse=True)


def test_it_plateaus_once_the_fade_is_done():
    got = F.grown_revenue(100.0, 0.20, 9, fade_to=0.0, fade_years=4)
    assert round(got[-1], 6) == round(got[-2], 6) == round(got[-3], 6)


def test_a_fade_to_a_positive_rate_keeps_growing():
    got = F.grown_revenue(100.0, 0.20, 8, fade_to=0.02, fade_years=4)
    assert round(got[-1] / got[-2] - 1, 6) == 0.02


def test_the_fade_reaches_the_engine():
    flat = F.build(_marketed(revenue_growth_pct=0.10, forecast_years=12))
    faded = F.build(_marketed(revenue_growth_pct=0.10, forecast_years=12,
                              terminal_growth_pct=0.0, growth_fade_years=5))
    assert faded["revenue"][-1] < flat["revenue"][-1]
    assert faded["rnpv"] < flat["rnpv"]
    assert "fading to" in " ".join(faded["notes"])


# --- A bounded market -------------------------------------------------------
#
# A fade slows growth. It does not stop a product growing through the market it sells
# into, and a launch rate compounds fast enough to do that inside the fade. Vertex is
# switching CF patients from Trikafta to Alyftrek: read off the halves those two grow at
# -4.6% and +176%, one pool of patients moving between them. Alyftrek on its own rate
# passes the entire CF franchise in 2029 and reaches 26bn in 2030.

def test_the_ceiling_binds_the_level_not_the_rate():
    got = F.grown_revenue(100.0, 1.0, 8, ceiling=400.0)
    assert got[:2] == [200.0, 400.0]
    assert got[2:] == [400.0] * 6


def test_a_ceiling_above_the_path_never_binds():
    free = F.grown_revenue(100.0, 0.10, 8, fade_to=0.0, fade_years=4)
    capped = F.grown_revenue(100.0, 0.10, 8, fade_to=0.0, fade_years=4, ceiling=1e9)
    assert capped == free


def test_the_ceiling_survives_a_fade():
    """The fade is still applied underneath. A product held at its ceiling stays there
    rather than resuming growth once the rate settles."""
    got = F.grown_revenue(100.0, 1.5, 10, fade_to=0.0, fade_years=5, ceiling=500.0)
    assert max(got) == 500.0
    assert got[-1] == 500.0


def test_the_ceiling_reaches_the_engine_and_says_so():
    free = F.build(_marketed(revenue_growth_pct=1.0, forecast_years=10,
                             terminal_growth_pct=0.0, growth_fade_years=5))
    capped = F.build(_marketed(revenue_growth_pct=1.0, forecast_years=10,
                               terminal_growth_pct=0.0, growth_fade_years=5,
                               revenue_ceiling_musd=max(free["revenue"]) / 2))
    assert max(capped["revenue"]) < max(free["revenue"])
    assert capped["rnpv"] < free["rnpv"]
    assert "ceiling" in " ".join(capped["notes"])


def test_no_ceiling_is_the_old_behaviour():
    assert (F.build(_marketed(revenue_growth_pct=0.10, forecast_years=10))["revenue"]
            == F.build(_marketed(revenue_growth_pct=0.10, forecast_years=10,
                                 revenue_ceiling_musd=None))["revenue"])


# --- One pool, two products -------------------------------------------------
#
# Trikafta and Alyftrek dispense to the same CF patients. Forecast apart, on growth rates
# of -4.6% and +176% read off their own halves, the pair carried 40% more revenue by 2028
# than the franchise they are both inside. The quantity that behaves is share: Alyftrek
# went 2.0%, 5.4%, 14.6%, 17.9% over four quarters while Trikafta went 92.4%, 87.9%,
# 80.8%, 77.8%, which is one number and its complement.

def _franchise(**over):
    scalars = {"therapy_mode": "franchise", "franchise_revenue": 11150.5,
               "franchise_growth_pct": 0.089252, "share_now": 0.075136,
               "share_plateau": 0.90, "share_ramp_pct": 0.150084, "wacc": 0.085,
               "forecast_start_year": 2026, "forecast_years": 10,
               "cogs_pct": 0.14, "sga_pct": 0.15, "rd_pct": 0.33, "tax_rate": 0.15,
               "pos": 1.0}
    scalars.update(over)
    return {"scalars": scalars, "indications": []}


def test_share_starts_from_now_and_settles_at_the_plateau():
    got = F.share_path(0.10, 0.80, 0.20, 60)
    assert got[0] > 0.10 and got[0] < 0.80          # one year of ramp, not none
    assert got == sorted(got)                        # monotone
    assert got[-1] == pytest.approx(0.80, abs=1e-4)  # arrives


def test_share_runs_downhill_too():
    """The product giving the franchise up approaches its plateau from above. One curve
    does both directions, which is what lets the two shares stay complementary."""
    got = F.share_path(0.90, 0.10, 0.20, 60)
    assert got == sorted(got, reverse=True)
    assert got[-1] == pytest.approx(0.10, abs=1e-4)


def test_a_shared_ramp_makes_the_shares_sum_to_one():
    """The property the whole mode rests on. Shares that sum to one at the base year and
    at the plateau sum to one in every year between, whatever the ramp, so long as every
    member decays at the same rate. Nothing can be counted twice."""
    for ramp in (0.05, 0.150084, 0.4, 1.2):
        a = F.share_path(0.075136, 0.90, ramp, 20)
        b = F.share_path(1 - 0.075136, 0.10, ramp, 20)
        assert [round(x + y, 12) for x, y in zip(a, b)] == [1.0] * 20


def test_a_ramp_they_do_not_share_breaks_the_identity():
    """Stated as a test because it is the failure the company call watches for: differing
    ramps still start and end at one and drift in between."""
    a = F.share_path(0.075136, 0.90, 0.15, 20)
    b = F.share_path(1 - 0.075136, 0.10, 0.30, 20)
    assert max(abs(x + y - 1.0) for x, y in zip(a, b)) > 0.05


def test_two_members_sum_to_the_pool_in_every_year():
    aly = F.build(_franchise())
    tri = F.build(_franchise(share_now=1 - 0.075136, share_plateau=0.10))
    pool = aly["franchise"]["revenue"]
    assert tri["franchise"]["revenue"] == pool          # the same pool, from both sides
    for i, total in enumerate(pool):
        assert aly["revenue"][i] + tri["revenue"][i] == pytest.approx(total)


def test_the_franchise_reproduces_the_guided_first_year():
    """FY2026 is the year Vertex has guided and half reported, so the model has to land
    on it: 12,145.7mm of pool, 2,308.8 of it Alyftrek and 9,836.9 Trikafta."""
    aly = F.build(_franchise())
    tri = F.build(_franchise(share_now=1 - 0.075136, share_plateau=0.10))
    assert aly["franchise"]["revenue"][0] == pytest.approx(12145.7, abs=0.5)
    assert aly["revenue"][0] == pytest.approx(2308.8, abs=1.0)
    assert tri["revenue"][0] == pytest.approx(9836.9, abs=1.0)


def test_the_taker_overtakes_the_giver():
    aly = F.build(_franchise())["revenue"]
    tri = F.build(_franchise(share_now=1 - 0.075136, share_plateau=0.10))["revenue"]
    crossed = [i for i in range(len(aly)) if aly[i] > tri[i]]
    assert crossed, "Alyftrek should pass Trikafta inside the horizon"
    assert crossed[0] == 4                              # 2030 on a 2026 start


def test_franchise_mode_names_what_it_is_missing():
    with pytest.raises(F.ForecastError) as raised:
        F.build({"scalars": {"therapy_mode": "franchise", "wacc": 0.085},
                 "indications": []})
    named = " ".join(raised.value.missing)
    for key in ("franchise_revenue", "franchise_growth_pct", "share_now",
                "share_plateau", "share_ramp_pct"):
        assert key in named


def test_franchise_mode_never_asks_for_a_price():
    """It is anchored on a pool, so a price per patient is the wrong question, exactly as
    it is for a marketed product."""
    assert F.build(_franchise())["rnpv"] > 0


def test_the_other_modes_carry_no_franchise():
    assert F.build(_marketed())["franchise"] is None


# --- A placeholder curve, so a blocked asset draws --------------------------------
#
# Six of eight pipeline assets were blocked on the two uptake numbers no source settles,
# the peak share of the pool and the midpoint of the ramp, and drew nothing. A placeholder
# from data/curve_defaults.csv lets them draw a curve to be argued with. It is labelled
# on the result, and the rollup leaves such an asset out of the per-share number.

PLACEHOLDER = {"chronic": {"penetration_peak_pct": 0.05, "ramp_midpoint_year": 4,
                           "source": "test placeholder", "note": ""}}


def _pool(**over):
    ind = {"name": "Obesity", "scalars": {
        "prevalence": 1_000_000, "eligible_pct": 0.5, "incidence": 50_000,
        "ramp_steepness": 1.2}, "series": {}}
    ind["scalars"].update(over)
    scalars = {"therapy_mode": "chronic", "net_price_per_patient": 0.01,
               "discontinuation_pct": 0.3, "wacc": 0.09, "forecast_start_year": 2027,
               "forecast_years": 8, "cogs_pct": 0.1, "sga_pct": 0.1, "rd_pct": 0.1,
               "tax_rate": 0.2, "pos": 0.5}
    return {"scalars": scalars, "indications": [ind], "curve_defaults": PLACEHOLDER}


def test_the_placeholder_fills_only_the_two_judgements():
    got = F.build(_pool())
    assert got["curve_basis"].startswith("placeholder curve")
    assert got["revenue"][0] > 0
    assert any("placeholder curve" in n for n in got["notes"])


def test_a_stated_curve_is_not_overridden():
    got = F.build(_pool(penetration_peak_pct=0.30, ramp_midpoint_year=3))
    assert got["curve_basis"] == "stated"
    assert not any("placeholder" in n for n in got["notes"])


def test_the_placeholder_does_not_invent_epidemiology():
    """A pool missing eligible_pct is missing a fact, not a judgement, and stays blocked
    rather than being drawn on a made-up share."""
    inputs = _pool()
    del inputs["indications"][0]["scalars"]["eligible_pct"]
    with pytest.raises(F.ForecastError):
        F.build(inputs)


def test_no_defaults_means_the_old_refusal():
    inputs = _pool()
    inputs.pop("curve_defaults")
    with pytest.raises(F.ForecastError):
        F.build(inputs)


def test_the_pnl_carries_every_line():
    row = F.build(_marketed())["pnl"][0]
    for key in ("revenue", "cogs", "sga", "rd", "ebit", "tax", "fcff"):
        assert key in row
    assert row["ebit"] == pytest.approx(row["revenue"] - row["cogs"] - row["sga"]
                                        - row["rd"])
