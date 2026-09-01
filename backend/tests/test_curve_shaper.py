"""The two numbers no source settles, given something to be judged against.

Steepness falls out of a launch's early growth and incidence out of a cohort study, but a
ceiling cannot be read off a curve that has not reached one, and the midpoint moves with
the ceiling. So the hardest judgement in the model was the one made with the least
feedback: an asset blocked on these two drew nothing at all.
"""

import db
import forecast_view


def _seed(tmp_path):
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (1, 1, 'Retatrutide', 0)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Obesity')")
    rows = [
        ("therapy_mode", None, "chronic", None),
        ("net_price_per_patient", 0.0066, None, None),
        ("discontinuation_pct", 0.648, None, None),
        ("wacc", 0.08, None, None),
        ("forecast_start_year", 2027, None, None),
        ("cogs_pct", 0.2, None, None), ("sga_pct", 0.2, None, None),
        ("rd_pct", 0.2, None, None), ("tax_rate", 0.2, None, None),
        ("pos", 0.65, None, None),
        ("prevalence", 107_592_242, None, 1),
        ("eligible_pct", 1.0, None, 1),
        ("incidence", 4_478_747, None, 1),
        ("ramp_steepness", 1.402, None, 1),
    ]
    for key, value, text, ind in rows:
        conn.execute(
            "INSERT INTO assumptions (asset_id, indication_id, key, value, text_value,"
            " source) VALUES (1, ?, ?, ?, ?, 'test')", (ind, key, value, text))
    conn.commit()
    conn.close()
    return path


def test_the_curve_can_be_shaped_before_it_is_committed(tmp_path):
    path = _seed(tmp_path)
    out = forecast_view.shape_curve(path, "LLY", 1, peak=0.05, midpoint=4)
    assert out["ok"] is True
    assert out["shaped_indications"] == 1
    assert out["rnpv"] > 0
    # And nothing was written. On its own the asset now draws on the placeholder curve
    # rather than refusing, and says so; the two values it lacks are still not on file.
    own = forecast_view.asset_forecast(path, "LLY", 1)
    assert own["ok"] is True
    assert own["result"]["curve_basis"].startswith("placeholder curve")
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assumptions WHERE key IN"
                        " ('penetration_peak_pct', 'ramp_midpoint_year')").fetchone()[0] == 0
    conn.close()


def test_a_higher_ceiling_is_worth_more(tmp_path):
    path = _seed(tmp_path)
    low = forecast_view.shape_curve(path, "LLY", 1, peak=0.03, midpoint=4)
    high = forecast_view.shape_curve(path, "LLY", 1, peak=0.09, midpoint=4)
    assert high["rnpv"] > low["rnpv"]
    assert max(high["revenue"]) > max(low["revenue"])


def test_a_later_midpoint_is_worth_less(tmp_path):
    """The same ceiling reached later discounts harder. That is the whole reason the two
    handles have to move together."""
    path = _seed(tmp_path)
    soon = forecast_view.shape_curve(path, "LLY", 1, peak=0.05, midpoint=2)
    late = forecast_view.shape_curve(path, "LLY", 1, peak=0.05, midpoint=9)
    assert soon["rnpv"] > late["rnpv"]


def test_it_names_the_indications_it_could_write_to(tmp_path):
    path = _seed(tmp_path)
    out = forecast_view.shape_curve(path, "LLY", 1, peak=0.05, midpoint=4)
    assert out["pooled"] == [{"id": 1, "name": "Obesity"}]


def test_a_value_already_on_file_is_never_overridden(tmp_path):
    # The shaper fills gaps. An assumption an analyst has committed stays committed.
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'penetration_peak_pct', 0.02, 'committed')")
    conn.commit(); conn.close()

    at_two = forecast_view.shape_curve(path, "LLY", 1, peak=0.02, midpoint=4)
    proposed = forecast_view.shape_curve(path, "LLY", 1, peak=0.20, midpoint=4)
    assert proposed["rnpv"] == at_two["rnpv"]


def test_it_still_reports_what_else_is_missing(tmp_path):
    """Shaping must not disguise a forecast that is short of something other than the
    ramp, or a blocked asset would look shaped."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("DELETE FROM assumptions WHERE key = 'net_price_per_patient'")
    conn.commit(); conn.close()

    out = forecast_view.shape_curve(path, "LLY", 1, peak=0.05, midpoint=4)
    assert out["ok"] is False
    assert any("net_price" in m for m in out["missing"])


def test_another_company_cannot_shape_this_asset(tmp_path):
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'MRK', 'Merck')")
    conn.commit(); conn.close()
    assert forecast_view.shape_curve(path, "MRK", 1, peak=0.05, midpoint=4) is None


def test_a_verdict_knows_whether_its_scenarios_are_real(tmp_path):
    """Only Casgevy has bear and bull rows. Everything else would have shown the same
    number three times and called it a spread."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'penetration_peak_pct', 0.05, 'test')")
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'ramp_midpoint_year', 4, 'test')")
    conn.commit(); conn.close()

    v = forecast_view.verdict(path, "LLY", 1)
    assert v["ok"] is True
    assert v["has_range"] is False
    assert v["spread"]["bear"]["defined"] is False

    conn = db.get_connection(path)
    conn.execute("INSERT INTO assumptions (asset_id, key, value, scenario, source)"
                 " VALUES (1, 'net_price_per_patient', 0.004, 'bear', 'test')")
    conn.commit(); conn.close()

    v = forecast_view.verdict(path, "LLY", 1)
    assert v["has_range"] is True
    assert v["spread"]["bear"]["rnpv"] < v["spread"]["base"]["rnpv"]


# --- the company call ------------------------------------------------------
# An analyst covers a name, not a compound. What makes the sum honest is saying in the
# same breath how much of the business it covers.

def _company(tmp_path):
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'penetration_peak_pct', 0.05, 'test')")
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'ramp_midpoint_year', 4, 'test')")
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " period_end, value, unit) VALUES"
                 " (1, 'WeightedAverageDilutedShares', 'FY', 2025, '2025-12-31',"
                 "  258000000, 'shares')")
    conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                 " VALUES (1, '2026-08-27', 547.55, '1d')")
    # One modelled product and one much larger one that is not.
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value)"
                 " VALUES (1, 2025, 'FY', 120000000)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (2, 1, 'Trikafta', 1)")
    conn.execute("INSERT INTO asset_revenue (asset_id, fiscal_year, period, value)"
                 " VALUES (2, 2025, 'FY', 10310000000)")
    conn.commit(); conn.close()
    return path


def test_the_company_call_reports_coverage_beside_the_number(tmp_path):
    path = _company(tmp_path)
    v = forecast_view.company_verdict(path, "LLY")
    assert v["per_share"] > 0
    assert v["pct_of_price"] == v["per_share"] / 547.55
    # The guard: one product of two, and the small one.
    assert round(v["coverage"]["share"], 3) == 0.012
    assert v["coverage"]["unmodelled"][0]["name"] == "Trikafta"


def test_the_note_leads_with_what_is_not_modelled(tmp_path):
    import forecast_note
    path = _company(tmp_path)
    note = forecast_note.write_company(forecast_view.company_verdict(path, "LLY"))
    # No reported total is seeded here, so coverage is against the tagged rows and the
    # headline says so rather than calling that the company.
    assert "1.2% of FY2025 tagged revenue" in note["headline"]
    assert "Trikafta alone is 99%" in note["headline"]
    body = " ".join(note["body"])
    assert "point it at the rest" in body          # thin coverage is called out
    assert "work queue" in body


def test_thin_coverage_is_flagged_and_full_coverage_is_not(tmp_path):
    import forecast_note
    path = _company(tmp_path)
    v = forecast_view.company_verdict(path, "LLY")
    assert "point it at the rest" in " ".join(forecast_note.company_body(v))
    v["coverage"]["share"] = 0.90
    v["coverage"]["unmodelled"] = []
    assert "point it at the rest" not in " ".join(forecast_note.company_body(v))


def test_an_unknown_ticker_is_none(tmp_path):
    path = _company(tmp_path)
    assert forecast_view.company_verdict(path, "ZZZZ") is None


def test_a_marketed_price_becomes_a_patient_count_to_check(tmp_path):
    """A marketed product is valued off revenue, so its price is otherwise unused.
    Dividing one by the other turns the price into a check an analyst can hold against a
    registry."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("DELETE FROM assumptions WHERE asset_id = 1")
    for key, value in (("base_revenue", 1000.0), ("revenue_growth_pct", 0.0),
                       ("wacc", 0.08), ("forecast_start_year", 2026),
                       ("cogs_pct", 0.2), ("sga_pct", 0.2), ("rd_pct", 0.2),
                       ("tax_rate", 0.2), ("pos", 1.0),
                       ("net_price_per_patient", 0.25)):
        conn.execute("INSERT INTO assumptions (asset_id, key, value, source)"
                     " VALUES (1, ?, ?, 'test')", (key, value))
    conn.execute("INSERT INTO assumptions (asset_id, key, text_value, source)"
                 " VALUES (1, 'therapy_mode', 'marketed', 'test')")
    conn.commit(); conn.close()

    v = forecast_view.verdict(path, "LLY", 1)
    assert v["ok"] is True
    # 1,000mm of revenue at 0.25mm a patient is 4,000 patients.
    assert round(v["implied_patients"]) == 4000


def test_a_patient_built_forecast_implies_nothing_of_the_kind(tmp_path):
    """The check only means something where revenue was the input rather than the
    output."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'penetration_peak_pct', 0.05, 'test')")
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, source)"
                 " VALUES (1, 1, 'ramp_midpoint_year', 4, 'test')")
    conn.commit(); conn.close()
    assert forecast_view.verdict(path, "LLY", 1)["implied_patients"] is None
