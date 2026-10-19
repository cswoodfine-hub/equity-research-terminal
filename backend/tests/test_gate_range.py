"""The next gate's range on the verdict: what a pipeline asset is worth now, if its next
gate passes and if it fails, per share. Derived beside the value, never in it."""

import datetime as dt
import json

import pytest

import assumptions as A
import db
import forecast_view as V
import pos_granular as PG

MYELOMA = ("D009101", "Multiple Myeloma")
FOLLICULAR = ("D008224", "Lymphoma, Follicular")
SHARES = 1_770_000_000


def _day(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


@pytest.fixture
def big(monkeypatch):
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)


def _book(tmp_path, extra=(), share=None, name="etentamig", second_trial=True):
    """A Phase 3 antibody in multiple myeloma at a big pharma owner, beside a marketed
    product, each with a forecast the engine can build."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = str(tmp_path / "range.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'ABBV', 'AbbVie', 'USD')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (7, 1, ?, 0)", (name,))
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (8, 1, 'oldmab', 1)")
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES (3, ?, ?)",
                 MYELOMA[::-1])
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " is_lead, region) VALUES (30, 7, 3, 'Phase 3', 1, 'US')")
    common = (("net_price_per_patient", 0.3), ("cogs_per_patient", 0.05),
              ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15), ("wacc", 0.09),
              ("forecast_years", 6))
    rows = [{"key": k, "value": v, "source": "t"}
            for k, v in (*common, ("forecast_start_year", 2028), *extra)]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    if share is not None:
        rows.append({"key": "economics_share", "value": share, "source": "t"})
    for year, patients in ((2028, 400), (2029, 900), (2030, 1500)):
        rows.append({"key": "new_patients", "indication_id": 3, "year": year,
                     "value": patients, "source": "t"})
    A.save(conn, 7, rows)
    marketed = [{"key": k, "value": v, "source": "t"}
                for k, v in (*common, ("forecast_start_year", 2026), ("pos", 1.0))]
    marketed.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    marketed.append({"key": "new_patients", "indication_id": 3, "year": 2026,
                     "value": 900, "source": "t"})
    A.save(conn, 8, marketed)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (1, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, ?, '2025-12-31')", (SHARES,))
    trials = [("NCT00000001", _day(200), 500, MYELOMA)]
    if second_trial:
        trials.append(("NCT00000004", _day(400), 900, FOLLICULAR))
    for nct, completion, enrollment, term in trials:
        conn.execute(
            "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
            " overall_status, primary_completion_date, enrollment, title, conditions,"
            " mesh_terms) VALUES (?, 7, 1, 'Phase 3', 'Recruiting', ?, ?, 'A study', ?, ?)",
            (nct, completion, enrollment, json.dumps([term[1]]),
             json.dumps({"meshes": [{"id": term[0], "term": term[1]}], "ancestors": []})))
    conn.commit()
    conn.close()
    return path


def test_the_gate_per_share_figures_are_npv_times_each_leg(tmp_path, big):
    path = _book(tmp_path, share=0.8)
    v = V.verdict(path, "ABBV", 7)
    gate = v["gate"]
    unit = v["npv"] * 0.8 * 1e6 / SHARES
    assert v["gate_range"] is True
    assert gate["label"] == "Phase 3 readout" and gate["legs_basis"] == "derived"
    assert gate["trial"]["nct_id"] == "NCT00000001"
    assert gate["trial"]["indication"] == MYELOMA[1]
    assert gate["date"] == _day(200)
    assert gate["per_share_now"] == pytest.approx(v["per_share"], rel=1e-12)
    assert gate["per_share_success"] == pytest.approx(unit * gate["pos_success"], rel=1e-12)
    assert gate["per_share_failure"] == 0.0 and gate["pos_failure"] == 0.0
    assert gate["p_gate"] * gate["pos_success"] == pytest.approx(v["pos"], abs=1e-12)
    # a miss leaves the follicular study open, so the model would hold it
    assert gate["held"]["ncts"] == ["NCT00000004"]
    assert gate["held"]["per_share"] == pytest.approx(unit * gate["held"]["pos"])


def test_the_band_is_drawn_only_where_the_placement_sets_a_wide_enough_pos(tmp_path, big,
                                                                         monkeypatch):
    path = _book(tmp_path)
    gate = V.verdict(path, "ABBV", 7)["gate"]
    placement = V.asset_forecast(path, "ABBV", 7)["result"]["pos_placement"]
    assert placement["high"] - placement["low"] >= V.GATE_BAND_MIN
    assert gate["band"]["pos_low"] == placement["low"]
    assert gate["band"]["per_share_high"] == pytest.approx(
        gate["per_share_now"] / gate["pos_now"] * placement["high"], rel=1e-12)
    # a band narrower than the threshold is one number printed twice
    monkeypatch.setattr(V, "GATE_BAND_MIN", placement["high"] - placement["low"] + 1e-9)
    assert V.verdict(path, "ABBV", 7)["gate"]["band"] is None
    monkeypatch.undo()
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)
    # a stated probability sets the value, so the placement's band is not drawn
    stated = _book(tmp_path / "s", extra=(("pos", 0.3),))
    gate = V.verdict(stated, "ABBV", 7)["gate"]
    assert gate["band"] is None and gate["pos_now"] == 0.3
    assert gate["p_gate"] == pytest.approx(0.3 / gate["pos_success"])


def test_the_hand_range_and_the_value_are_untouched(tmp_path, big, monkeypatch):
    path = _book(tmp_path)
    with_gate = V.verdict(path, "ABBV", 7)
    company = V.company_verdict(path, "ABBV")
    monkeypatch.setattr(PG, "legs_for_inputs", lambda *a, **k: (None, None))
    without = V.verdict(path, "ABBV", 7)
    bare = V.company_verdict(path, "ABBV")
    assert without["gate"] is None and without["gate_range"] is False
    for key in ("rnpv", "per_share", "spread", "has_range", "pos", "levers"):
        assert with_gate[key] == without[key], key
    assert company["rnpv_total"] == bare["rnpv_total"]
    assert company["sotp"]["equity_per_share"] == bare["sotp"]["equity_per_share"]
    assert [m["rnpv_share"] for m in company["modelled"]] == [
        m["rnpv_share"] for m in bare["modelled"]]


def test_a_marketed_asset_has_no_gate(tmp_path, big):
    path = _book(tmp_path)
    v = V.verdict(path, "ABBV", 8)
    assert v["gate"] is None and v["gate_range"] is False


def test_the_company_verdict_carries_each_pipeline_lines_gate(tmp_path, big):
    path = _book(tmp_path, share=0.8)
    company = V.company_verdict(path, "ABBV")
    lines = {m["asset_id"]: m for m in company["modelled"]}
    v = V.verdict(path, "ABBV", 7)
    assert lines[7]["gate"]["per_share_success"] == pytest.approx(
        v["gate"]["per_share_success"], rel=1e-12)
    assert lines[7]["per_share_success"] == lines[7]["gate"]["per_share_success"]
    assert lines[7]["per_share_failure"] == 0.0
    assert lines[7]["gate"]["per_share_now"] == pytest.approx(lines[7]["per_share"],
                                                              rel=1e-12)
    assert lines[8]["gate"] is None and lines[8]["per_share_success"] is None


def test_stated_legs_outrank_the_derived_ones_on_the_gate(tmp_path, big):
    path = _book(tmp_path, extra=(("pos_success", 0.7), ("pos_failure", 0.1)))
    gate = V.verdict(path, "ABBV", 7)["gate"]
    assert gate["legs_basis"] == "stated"
    assert (gate["pos_success"], gate["pos_failure"]) == (0.7, 0.1)
    assert gate["p_gate"] is None and gate["held"] is None and gate["band"] is None
    assert gate["label"] == "Phase 3 readout"
