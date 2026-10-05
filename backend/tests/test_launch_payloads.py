"""The launch floor in the forecast payloads: beside the forecast, the verdict and each
rollup line, and on its own route. A flag, so the one thing proved here beyond the wiring
is that the forecast is the same with it as without it."""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import assumptions as A
import db
import forecast
import forecast_view as V
import launch_timing as L
import main
import pos_granular as PG

MYELOMA = ("D009101", "Multiple Myeloma")
SHARES = 1_770_000_000


@pytest.fixture
def big(monkeypatch):
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)


def _book(tmp_path, seed=2028):
    """A Phase 3 antibody in multiple myeloma at a big pharma owner whose only Phase 3
    completes in March 2030, beside a marketed product, each buildable."""
    path = str(tmp_path / "launch.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'ABBV', 'AbbVie', 'USD')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (7, 1, 'etentamig', 0), (8, 1, 'oldmab', 1)")
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES (3, ?, ?)",
                 MYELOMA[::-1])
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " is_lead, region) VALUES (30, 7, 3, 'Phase 3', 1, 'US')")
    common = (("net_price_per_patient", 0.3), ("cogs_per_patient", 0.05),
              ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15), ("wacc", 0.09),
              ("forecast_years", 6))
    rows = [{"key": k, "value": v, "source": "t"}
            for k, v in (*common, ("forecast_start_year", seed))]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    for year, patients in ((seed, 400), (seed + 1, 900), (seed + 2, 1500)):
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
    conn.execute(
        "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase, overall_status,"
        " primary_completion_date, primary_completion_type, enrollment, title,"
        " conditions, mesh_terms, fetched_at) VALUES ('NCT00000001', 7, 1, 'Phase 3',"
        " 'Recruiting', '2030-03-31', 'estimated', 500, 'A study', ?, ?,"
        " datetime('now'))",
        (json.dumps([MYELOMA[1]]),
         json.dumps({"meshes": [{"id": MYELOMA[0], "term": MYELOMA[1]}],
                     "ancestors": []})))
    conn.commit()
    conn.close()
    return path


def test_the_forecast_carries_the_floor_and_is_the_same_without_it(tmp_path, big,
                                                                  monkeypatch):
    path = _book(tmp_path)
    state = V.asset_forecast(path, "ABBV", 7)
    launch = state["launch"]
    assert launch["status"] == "before_floor" and launch["flag"] == "red"
    assert launch["decision_date"] == "2030-11-30"
    assert launch["gate"]["nct_id"] == "NCT00000001"
    assert launch["gate"]["same_as_governing"] is True
    # Purity: the forecast with the floor patched out is the same forecast.
    monkeypatch.setattr(L, "for_asset", lambda *a, **k: None)
    without = V.asset_forecast(path, "ABBV", 7)
    assert without["launch"] is None
    assert without["result"] == state["result"]
    assert V.asset_forecast(path, "ABBV", 8)["launch"] is None


def test_reading_the_floor_leaves_the_inputs_and_the_build_untouched(tmp_path, big):
    path = _book(tmp_path)
    conn = db.get_connection(path)
    inputs = A.load(conn, 7, "base")
    before = copy.deepcopy(inputs)
    built = forecast.build(inputs)
    legs, _ = PG.legs_for_inputs(conn, 7, inputs)
    L.for_asset(conn, 7, legs=legs)
    after = forecast.build(inputs)
    conn.close()
    assert inputs == before
    assert after == built


def test_the_verdict_dates_the_gate_it_prices(tmp_path, big):
    path = _book(tmp_path)
    v = V.verdict(path, "ABBV", 7)
    assert v["launch"]["gate"]["nct_id"] == v["gate"]["trial"]["nct_id"]
    assert v["launch"]["gate"]["label"] == v["gate"]["label"]
    assert v["launch"]["gate"]["first_full_year"] == 2031
    assert V.verdict(path, "ABBV", 8)["launch"] is None


def test_each_rollup_line_carries_the_compact_floor(tmp_path, big):
    path = _book(tmp_path)
    lines = {l["asset_id"]: l for l in V.company_rollup(path, "ABBV")["lines"]}
    conn = db.get_connection(path)
    full = L.for_asset(conn, 7)
    conn.close()
    assert lines[7]["launch"] == L.summary(full)
    assert lines[7]["launch"]["status"] == "before_floor"
    assert lines[8]["launch"] is None
    modelled = {l["asset_id"]: l for l in V.company_verdict(path, "ABBV")["modelled"]}
    assert modelled[7]["launch"]["first_full_year"] == 2031


def test_the_route_lists_unmarketed_assets_red_first(tmp_path, big, monkeypatch):
    path = _book(tmp_path)
    monkeypatch.setattr(db, "DB_PATH", Path(path))
    client = TestClient(main.app)
    assert client.get("/companies/ZZZZ/launch-timing").status_code == 404
    body = client.get("/companies/abbv/launch-timing").json()
    assert body["ticker"] == "ABBV"
    assert [a["asset_id"] for a in body["assets"]] == [7]
    assert body["assets"][0]["status"] == "before_floor"


def test_no_module_on_the_value_path_reads_the_floor():
    """The floor sits beside the value. forecast_view carries it into the payloads; the
    engine, its inputs, the probability, the sum of the parts, the future pipeline, the
    break-points and the ratings never import it."""
    backend = Path(__file__).resolve().parent.parent
    for name in ("forecast", "assumptions", "pos_granular", "applications", "breakpoints",
                 "fair_value", "company_score", "comps_valuation", "future_pipeline"):
        source = (backend / f"{name}.py").read_text(encoding="utf-8")
        assert "launch_timing" not in source, name
