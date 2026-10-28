"""An unapproved indication on a product that already sells something else.

The marketed mode values a reported revenue grown to a ceiling and carries no patient
funnel, so a label expansion read as "outside the gate model" on every marketed product
in the book. The layer values the expansion the way the book values anything not yet
approved, bottom-up over its own pool, and leaves the marketed line alone.
"""

import pytest

import db
import indication_layer as IL
import assumptions as A


def _seed(tmp_path, *, pool=True, price=True, marketed=True):
    path = str(tmp_path / "layer.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Omvoh', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (7, 'Pediatric Crohn''s disease')")
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " region) VALUES (5, 1, 7, 'Phase 3', 'US')")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("sga_pct", 0.17), ("rd_pct", 0.20), ("tax_rate", 0.16), ("cogs_pct", 0.17),
        ("wacc", 0.09), ("forecast_start_year", 2027), ("forecast_years", 15),
        ("discontinuation_pct", 0.275))]
    rows.append({"key": "therapy_mode", "text_value": "marketed" if marketed else "chronic",
                 "source": "t"})
    if marketed:
        rows += [{"key": "base_revenue", "value": 386.0, "source": "t"},
                 {"key": "revenue_growth_pct", "value": 0.40, "source": "t"},
                 {"key": "revenue_ceiling_musd", "value": 1120.0, "source": "t"}]
    if price:
        rows += [{"key": "list_price_per_patient", "value": 0.033083, "source": "t"},
                 {"key": "gross_to_net_pct", "value": 0.50, "source": "t"}]
    if pool:
        rows += [{"key": k, "indication_id": 7, "value": v, "source": "t"} for k, v in (
            ("prevalence", 36500.0), ("incidence", 3650.0), ("eligible_pct", 0.303),
            ("penetration_peak_pct", 0.0330387), ("ramp_midpoint_year", 4.15),
            ("ramp_steepness", 1.005))]
    A.save(conn, 1, rows)
    conn.commit()
    return path, conn


def test_the_layer_is_built_bottom_up_over_its_own_pool(tmp_path):
    """36,500 paediatric Crohn's patients, 30.3% of them on a biologic, a peak of 3.3%
    of those at $16,541 a year. The marketed line's 386mm contributes nothing to it."""
    _, conn = _seed(tmp_path)
    got = IL.build(conn, 1, 7)
    assert got["ok"]
    assert got["npv"] > 0
    # Small, and that is the finding: paediatric Crohn's is a fraction of the franchise.
    assert 5 < got["peak_revenue"] < 60
    conn.close()


def test_the_layer_does_not_carry_the_marketed_line(tmp_path):
    """base_revenue is the business the product already has. A layer that started from
    it would value the whole franchise again and call the difference an expansion."""
    _, conn = _seed(tmp_path)
    got = IL.build(conn, 1, 7)
    assert got["peak_revenue"] < 386.0
    conn.close()


def test_the_layer_is_unrisked(tmp_path):
    """The probability belongs to the gate, which applies it to both legs. A value
    risked here would be risked twice."""
    _, conn = _seed(tmp_path)
    plain = IL.build(conn, 1, 7)["npv"]
    A.save(conn, 1, [{"key": "pos", "value": 0.3, "source": "t"}])
    conn.commit()
    assert IL.build(conn, 1, 7)["npv"] == plain
    conn.close()


def test_the_layer_leaves_out_the_share_already_in_the_business(tmp_path):
    """The marketed line adds (1 - overlap) of a layer, so the gate's stake must too: a
    layer half inside the approved business is worth half of one wholly outside it."""
    _, conn = _seed(tmp_path)
    full = IL.build(conn, 1, 7)
    A.save(conn, 1, [{"key": "base_pool_overlap_pct", "indication_id": 7, "value": 0.5,
                      "source": "t"}])
    conn.commit()
    half = IL.build(conn, 1, 7)
    assert half["ok"] and half["base_pool_overlap_pct"] == 0.5
    assert half["peak_revenue"] == pytest.approx(full["peak_revenue"] / 2, rel=0.02)
    assert half["npv"] < full["npv"]
    conn.close()


def test_a_layer_wholly_inside_the_business_is_not_priced(tmp_path):
    _, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "base_pool_overlap_pct", "indication_id": 7, "value": 1.0,
                      "source": "t"}])
    conn.commit()
    got = IL.build(conn, 1, 7)
    assert not got["ok"] and "wholly inside" in got["why"]
    conn.close()


def test_the_franchise_ceiling_is_reported_not_applied(tmp_path):
    """The ceiling is somebody's forecast of the whole product at peak, so it already
    contains the expansions. Silently capping would hide that; the flag shows it."""
    _, conn = _seed(tmp_path)
    got = IL.build(conn, 1, 7)
    assert got["ceiling"] == 1120.0
    assert got["peak_together"] == got["base_peak_revenue"] + got["peak_revenue"]
    assert got["ceiling_binds"] is True          # the base alone already reaches 1,120
    # Reported, not applied: the layer keeps its own value.
    assert got["peak_revenue"] > 0
    conn.close()


def test_a_layer_with_no_pool_names_what_it_needs(tmp_path):
    """Nothing is invented. The keys are named the way a forecast names what it lacks."""
    _, conn = _seed(tmp_path, pool=False)
    got = IL.build(conn, 1, 7)
    assert got["ok"] is False
    assert set(got["missing"]) >= {"prevalence", "eligible_pct", "penetration_peak_pct"}
    conn.close()


def test_a_layer_with_no_price_names_it(tmp_path):
    _, conn = _seed(tmp_path, price=False)
    got = IL.build(conn, 1, 7)
    assert got["ok"] is False
    assert "net_price_per_patient" in got["missing"]
    conn.close()


def test_an_indication_with_no_assumptions_is_refused(tmp_path):
    _, conn = _seed(tmp_path)
    conn.execute("INSERT INTO indications (id, name) VALUES (8, 'Something else')")
    conn.commit()
    got = IL.build(conn, 1, 8)
    assert got["ok"] is False
    conn.close()


# --- the layer inside the valuation ----------------------------------------
import forecast


def _marketed_inputs(**over):
    """A marketed line with one unapproved indication carrying a full pool."""
    ind = {"name": "Pediatric Crohn's disease", "indication_id": 7, "approved": False,
           "series": {}, "scalars": {
               "prevalence": 36500.0, "incidence": 3650.0, "eligible_pct": 0.303,
               "penetration_peak_pct": 0.0330387, "ramp_midpoint_year": 4.15,
               "ramp_steepness": 1.005, "base_pool_overlap_pct": 0.0, "pos": 0.523668}}
    ind["scalars"].update(over.pop("indication", {}))
    scalars = {"therapy_mode": "marketed", "base_revenue": 386.0,
               "revenue_growth_pct": 0.404568, "revenue_ceiling_musd": 1120.0,
               "growth_fade_years": 5, "terminal_growth_pct": 0.0,
               "forecast_start_year": 2027, "forecast_years": 15,
               "list_price_per_patient": 0.033083, "gross_to_net_pct": 0.50,
               "discontinuation_pct": 0.275, "cogs_pct": 0.17, "sga_pct": 0.17,
               "rd_pct": 0.20, "tax_rate": 0.16, "wacc": 0.09, "pos": 1.0}
    scalars.update(over.pop("scalars", {}))
    return {"scalars": scalars, "indications": [ind], "is_marketed": True}


def test_the_layer_is_added_to_the_marketed_line():
    """Before this a label expansion was worth nothing anywhere in the book, because
    marketed mode grows a reported revenue and carries no patient funnel at all.

    Measured with no ceiling, because a franchise ceiling is the separate case below:
    there the expansion is already inside the published peak and the layer can only
    redistribute it."""
    free = _marketed_inputs()
    free["scalars"].pop("revenue_ceiling_musd")
    without = _marketed_inputs()
    without["scalars"].pop("revenue_ceiling_musd")
    without["indications"] = []
    assert forecast.build(free)["npv"] > forecast.build(without)["npv"]


def test_under_a_franchise_ceiling_the_layer_redistributes_rather_than_adds():
    """The arithmetic consequence of calling the ceiling a franchise peak, and it is
    worth seeing rather than hiding. The published 1,120mm already contains the
    expansions, so carving room for one and adding it back cannot raise the total; it
    moves revenue from the faster-growing approved business to the slower-ramping
    layer, and the value falls slightly. A ceiling that meant approved indications only
    would behave the other way."""
    capped = forecast.build(_marketed_inputs())
    alone = _marketed_inputs()
    alone["indications"] = []
    assert max(capped["revenue"]) == pytest.approx(1120.0, abs=0.01)
    assert max(forecast.build(alone)["revenue"]) == pytest.approx(1120.0, abs=0.01)
    assert capped["npv"] < forecast.build(alone)["npv"]


def test_the_franchise_ceiling_holds_the_two_together():
    """The ceiling is somebody's forecast of the whole product at peak, so it already
    contains the expansions. The base is grown into what is left of it, and the sum
    reaches the published peak rather than passing it."""
    built = forecast.build(_marketed_inputs())
    assert max(built["revenue"]) <= 1120.0 + 1e-6
    assert max(built["revenue"]) > 1100.0          # the layer is really in there


def test_an_approved_indication_adds_nothing():
    """The approved business is inside the revenue the line is grown from. Adding it
    again bottom-up would buy it twice."""
    inputs = _marketed_inputs()
    inputs["indications"][0]["approved"] = True
    assert max(forecast.build(inputs)["revenue"]) == max(
        forecast.build({**inputs, "indications": []})["revenue"])


def test_a_layer_without_a_stated_overlap_is_left_out():
    """Assuming independence is how a comorbidity expansion turns into a second
    franchise. Orforglipron's hypertension studies enrol the obese adults it already
    sells to, so the share outside the base has to be stated before anything is added."""
    inputs = _marketed_inputs(indication={"base_pool_overlap_pct": None})
    built = forecast.build(inputs)
    assert max(built["revenue"]) <= 1120.0 + 1e-6
    assert any("base_pool_overlap_pct" in n for n in built["notes"])


def test_a_fully_overlapping_layer_adds_nothing():
    """A pool wholly inside the approved business is already being sold to."""
    inputs = _marketed_inputs(indication={"base_pool_overlap_pct": 1.0})
    plain = _marketed_inputs()
    plain["indications"] = []
    assert max(forecast.build(inputs)["revenue"]) == max(
        forecast.build(plain)["revenue"])


def test_the_layer_is_risked_at_its_own_odds():
    """The marketed line is a product that sells, carried at a probability of one. An
    indication that has not read out is not, and one probability cannot stand for both."""
    def uncapped(pos):
        inputs = _marketed_inputs(indication={"pos": pos})
        inputs["scalars"].pop("revenue_ceiling_musd")
        return max(forecast.build(inputs)["revenue"])

    assert uncapped(1.0) > uncapped(0.5) > uncapped(0.1)


def test_the_other_modes_are_untouched():
    """chronic and one_time already build every indication bottom-up. A layer there
    would count the same patients twice."""
    inputs = _marketed_inputs(scalars={"therapy_mode": "chronic"})
    for key in ("base_revenue", "revenue_growth_pct", "revenue_ceiling_musd"):
        inputs["scalars"].pop(key)
    built = forecast.build(inputs)
    assert not any("added as a layer" in n for n in built["notes"])


def test_a_wholly_overlapping_indication_says_so_without_a_pool():
    """An indication inside the approved business is nil whatever its prevalence, so it
    is answered before the pool is asked for. Orforglipron's hypertension, knee
    osteoarthritis and stress incontinence studies all enrol "obesity or overweight"
    patients its label already covers, and recording that is worth more than a silent
    skip that reads like missing data."""
    inputs = _marketed_inputs(indication={"base_pool_overlap_pct": 1.0,
                                          "prevalence": None, "eligible_pct": None,
                                          "penetration_peak_pct": None})
    built = forecast.build(inputs)
    assert any("adds nothing" in n for n in built["notes"])


def test_the_layer_names_the_ramp_among_the_keys_it_needs():
    """A layer is built on the pool identity, which turns a pool into patients a year
    and then needs a curve to say how quickly they arrive. Without one the engine has no
    patient series and refuses with "supply new_patients rows or the pool identity
    inputs", naming neither key and reading like a fault in the engine rather than a gap
    in the seed. Six layers carried every other key and failed exactly that way."""
    assert "ramp_midpoint_year" in IL.INDICATION_KEYS
    assert "ramp_steepness" in IL.INDICATION_KEYS
