"""The Catalysts tab's one read (backend/catalysts_command.py, GET
/companies/{t}/catalysts/view).

Three layers. The rules, on small dicts: the helpers that read a slip, a regulatory kind or
an asset off source text, and ``assemble``, which is pure. Then the route over a seeded
book in a temporary directory, which has the companies and nothing else, so it serves the
empty case and says the model was not read. Then a guard on the built book, skipped where
none is built, that checks every served gate against the forecast verdict, the catalyst
stakes, the development view and the launch floor it comes from.
"""

from __future__ import annotations

import copy
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

import catalysts_command as cc
import db
import main
import seed

TODAY = dt.date(2026, 10, 6)


# --------------------------------------------------------------------------- helpers
def test_moves_read_slips_and_pulls_newest_first():
    feed = [
        {"change_type": "date_slip", "detected_at": "2026-10-02 07:37:14",
         "headline": "AZN trial NCT07775404: primary completion slips 2027-06-04 -> 2028-04-06"},
        {"change_type": "date_change", "detected_at": "2026-10-03 07:00:00",
         "headline": "AZN trial NCT07775404: primary completion 2028-04-06 -> 2028-04-05"},
        {"change_type": "press_regulatory", "headline": "AZN trial NCT1: not a move"},
        {"change_type": "date_slip", "headline": "AZN trial NCT07775404: unparsable"},
    ]
    out = cc.moves(feed)
    assert list(out) == ["NCT07775404"]
    first, second = out["NCT07775404"]
    assert first == {"nct": "NCT07775404", "old": "2028-04-06", "new": "2028-04-05",
                     "days": -1, "seen": "2026-10-03", "kind": "date_change"}
    assert second["days"] == 307 and second["kind"] == "date_slip"


def test_regulatory_kind_is_read_off_the_words_or_left_general():
    assert cc.reg_kind("Imfinzi granted Priority Review in the US") == "US Priority Review"
    assert cc.reg_kind("Klygefa recommended for approval in the EU by CHMP") == "CHMP opinion"
    assert cc.reg_kind("FDA accepts the filing for tozorakimab") == "regulatory"
    assert cc.reg_kind("Filing acceptance for tozorakimab") == "filing accepted"
    assert cc.reg_kind("A headline naming none of them") == "regulatory"
    assert cc.reg_kind(None) == "regulatory"


def test_an_asset_is_matched_as_a_whole_word_longest_name_first():
    names = cc._names([{"id": 1, "brand_name": None, "generic_name": "efzimfotase alfa"},
                       {"id": 2, "brand_name": "Alfa", "generic_name": None},
                       {"id": 3, "brand_name": "Imfinzi", "generic_name": "durvalumab"}])
    assert cc.match_asset("Efzimfotase alfa granted Priority Review", names) == (
        1, "efzimfotase alfa")
    assert cc.match_asset("Imfinzizumab is not Imfinzi", names) == (3, "Imfinzi")
    assert cc.match_asset("durvalumabX only", names) == (None, None)
    assert cc.readout_asset("durvalumab (Imfinzi)", names) == (3, "Imfinzi")


def test_phase_is_the_titles_then_the_trials():
    assert cc.phase_of("Phase 3, Truqap") == "Phase 3"
    assert cc.phase_of("Phase 2/3, Something") == "Phase 2/3"
    assert cc.phase_of("A study", {"phase": "Phase 2"}) == "Phase 2"
    assert cc.phase_of("A study", {"phase": "N/A"}) is None


# --------------------------------------------------------------------------- assemble
def _gate(**kw):
    g = {"gate": "p3_to_nda", "label": "Phase 3 readout", "date": "2028-04-06",
         "date_basis": "registry", "due": False,
         "trial": {"nct_id": "NCT07775404", "indication": "Obesity"},
         "per_share_now": 4.06, "per_share_success": 6.60, "per_share_failure": 0.0,
         "p_gate": 0.615, "pos_now": 0.55, "pos_success": 0.90, "pos_failure": 0.0,
         "legs_basis": "derived", "basis": "Phase 3 to NDA/BLA 61.5%"}
    g.update(kw)
    return g


def _src(**kw):
    src = {
        "today": TODAY.isoformat(), "ticker": "AZN",
        "company": {"id": 1, "ticker": "AZN", "name": "AstraZeneca PLC"},
        "currency": "USD", "scorecard_held": True,
        "verdict": {"ok": True, "close": 150.0, "close_date": "2026-10-05", "modelled": [
            {"asset_id": 10, "name": "Elecoglipron", "per_share": 4.06, "is_marketed": False,
             "gate": _gate(held={"per_share": 4.06, "open": 8, "pos": 0.55,
                                 "ncts": ["NCT1"]})},
            {"asset_id": 11, "name": "Tozorakimab", "per_share": 1.1, "is_marketed": False,
             "gate": _gate(gate="nda_to_approval", label="FDA decision", date=None,
                           trial=None, per_share_now=1.13, per_share_success=1.18,
                           per_share_failure=0.0)},
            {"asset_id": 12, "name": "Truqap", "per_share": 2.4, "is_marketed": True,
             "loe_year": 2033},
            {"asset_id": 13, "name": "Unpriced", "per_share": 0.2,
             "gate": _gate(per_share_now=None)},
        ]},
        "stakes": {"priced": [{"id": 7, "asset_id": 10, "per_share": 6.60,
                               "expected_date": "2028-04-06", "description": "NCT07775404",
                               "title": "Phase 3, Elecoglipron", "resolvable": False,
                               "resolve_note": "switched off"}],
                   "unpriced": [{"id": 8, "asset_id": 12, "expected_date": "2026-11-01",
                                 "description": "NCT2", "title": "Phase 3, Truqap",
                                 "reason": "no_gate", "why": "marketed"},
                                {"id": 9, "asset_id": 12, "expected_date": None,
                                 "description": "not an nct", "reason": "no_gate"}]},
        "development": {"rows": [{"asset_id": 10, "ok": True, "gate": {"cost_per_share": 0.01},
                                  "ladder": {"rows": []}, "extra": "dropped"}],
                        "refused": [{"asset_id": 11, "ok": False, "why": "no cost read"}]},
        "launch": [{"asset_id": 11, "decision_date": "2026-11-26", "seed_year": 2027}],
        "changes": [{"change_type": "date_slip", "detected_at": "2026-10-02",
                     "headline": "AZN trial NCT07775404: primary completion slips "
                                 "2027-06-04 -> 2028-04-06"},
                    {"change_type": "date_slip", "detected_at": "2026-10-01",
                     "headline": "AZN trial NCT06455449: primary completion slips "
                                 "2027-01-01 -> 2027-09-01"},
                    {"change_type": "press_regulatory", "detected_at": "2026-09-26 06:00",
                     "headline": "AZN Imfinzi granted Priority Review in the US",
                     "url": "https://example.org/x"}],
        "readouts": [{"drug": "durvalumab (Imfinzi)", "phase": 3, "outcome": "positive",
                      "event_date": "2026-08-27", "quote": "met"}],
        "exclusivities": [{"asset_id": 12, "brand_name": "Truqap", "loe": "2033-05-01",
                           "loe_basis": "compound patent"}],
        "losses": [{"asset_id": 12, "share_of_revenue": 0.02, "fy": "FY2025"}],
        "programmes": [], "competition": {},
        "assets": [{"id": 10, "brand_name": None, "generic_name": "elecoglipron",
                    "modality": "small molecule", "is_marketed": 0},
                   {"id": 12, "brand_name": "Truqap", "generic_name": "capivasertib",
                    "modality": "small molecule", "is_marketed": 1},
                   {"id": 14, "brand_name": "Imfinzi", "generic_name": "durvalumab",
                    "modality": "biologic", "is_marketed": 1}],
        "trials": {"NCT07775404": {"nct_id": "NCT07775404", "phase": "Phase 3",
                                   "enrollment": 351, "conditions": ["Obesity"],
                                   "asset_id": 10},
                   "NCT06455449": {"nct_id": "NCT06455449", "phase": "Phase 2",
                                   "asset_id": 12}},
        "areas": {"10": "Metabolic", "11": "Respiratory", "12": "Oncology"},
    }
    src.update(kw)
    return src


def test_assemble_is_pure_and_strict_json():
    src = _src()
    before = copy.deepcopy(src)
    a, b = cc.assemble(src), cc.assemble(src)
    assert a == b and src == before
    json.dumps(a, allow_nan=False)
    assert a["complete"] and a["incomplete_reason"] is None and a["model_ok"]


def test_every_line_with_a_priced_next_gate_is_served_with_its_legs():
    out = cc.assemble(_src())
    gates = {g["asset_id"]: g for g in out["gates"]}
    assert set(gates) == {10, 11}                    # marketed and unpriced lines left out
    e = gates[10]
    assert (e["now"], e["success"], e["failure"]) == (4.06, 6.60, 0.0)
    assert e["swing"] == pytest.approx(6.60)
    assert e["area"] == "Metabolic" and e["trial"]["enrollment"] == 351
    assert e["move"]["days"] == 307
    assert e["stake"]["id"] == 7 and e["stake"]["resolvable"] is False
    assert e["development"] == {k: ({"cost_per_share": 0.01} if k == "gate" else
                                    {"rows": []} if k == "ladder" else
                                    True if k == "ok" else None) for k in cc.DEV_FIELDS}
    # An FDA decision with no date sits at the launch floor's earliest approval, as a floor.
    t = gates[11]
    assert t["date"] is None and t["floor"] == "2026-11-26"
    assert t["stake"] is None and t["development"]["why"] == "no cost read"


def test_a_missing_figure_stays_null_never_zero():
    src = _src()
    src["verdict"]["modelled"][0]["gate"]["per_share_success"] = None
    src["development"] = None
    src["verdict"]["close"] = None
    out = cc.assemble(src)
    e = next(g for g in out["gates"] if g["asset_id"] == 10)
    assert e["success"] is None and e["swing"] is None and e["development"] is None
    assert out["close"] is None


def test_events_say_why_the_rest_carry_no_price():
    out = cc.assemble(_src())
    ev = {e["id"]: e for e in out["events"]}
    assert ev[7]["priced"] and ev[7]["per_share"] == 6.60 and ev[7]["reason"] is None
    assert not ev[8]["priced"] and ev[8]["per_share"] is None
    assert ev[8]["reason"] == "no_gate" and ev[8]["marketed"] is True
    assert ev[9]["nct"] is None and ev[9]["date"] is None
    assert [e["id"] for e in out["events"]][-1] == 9          # no date sorts last
    assert out["unpriced_reasons"] == {"no_gate": 2}


def test_slips_put_the_one_on_a_priced_gate_first():
    out = cc.assemble(_src())
    assert [s["nct"] for s in out["slips"]] == ["NCT07775404", "NCT06455449"]
    assert out["slips"][0]["gate_asset"] == 10
    assert out["slips"][1]["gate_asset"] is None and out["slips"][1]["asset"] == "Truqap"


def test_exclusivity_regulatory_and_record_rows():
    out = cc.assemble(_src())
    (c,) = out["cliffs"]
    assert c["asset"] == "Truqap" and c["share_of_revenue"] == 0.02
    assert c["model_per_share"] == 2.4 and not c["passed"]
    assert out["loe_by_year"] == {"2033": {"per_share": 2.4,
                                           "products": [["Truqap", 2.4, "small molecule"]]}}
    (r,) = out["regulatory"]
    assert r["kind"] == "US Priority Review" and r["asset"] == "Imfinzi"
    assert r["headline"].startswith("Imfinzi") and r["date"] == "2026-09-26"
    (ro,) = out["readouts"]
    assert ro["asset_id"] == 14 and ro["asset"] == "Imfinzi"


def test_a_body_before_the_scorecard_or_the_model_is_marked_incomplete():
    out = cc.assemble(_src(scorecard_held=False))
    assert not out["complete"] and out["incomplete_reason"] == "scorecard_not_warm"
    out = cc.assemble(_src(verdict={"ok": False}))
    assert not out["complete"] and out["incomplete_reason"] == "model_not_read"
    assert out["gates"] == [] and not out["model_ok"]


# --------------------------------------------------------------------------- the route
@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("catalysts") / "book.db"
    db.init(path)
    seed.load_companies(path)
    return path


def test_route_on_a_seeded_book(seeded, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", seeded)
    client = TestClient(main.app)
    assert client.get("/companies/NOPE/catalysts/view").status_code == 404
    response = client.get("/companies/AZN/catalysts/view")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "AZN" and body["schema"] == cc.SCHEMA
    # Nothing is on file: every list is empty and the read says the model was not read,
    # so the page draws today's tab rather than an empty one.
    assert body["gates"] == [] and body["events"] == [] and body["slips"] == []
    assert not body["complete"] and body["close"] is None


# --------------------------------------------------------------------------- the book
def test_book_guard_every_gate_matches_its_sources(book):
    import development
    import forecast_view
    import launch_timing
    out = cc.build("AZN", today=TODAY)
    json.dumps(out, allow_nan=False)
    verdict = forecast_view.company_verdict(None, "AZN")
    if not verdict.get("ok"):
        pytest.skip("the book has no AZN forecast")
    lines = {m["asset_id"]: m for m in verdict["modelled"]}
    priced = [m for m in verdict["modelled"]
              if isinstance(m.get("gate"), dict) and m["gate"].get("per_share_now") is not None]
    assert {g["asset_id"] for g in out["gates"]} == {m["asset_id"] for m in priced}
    stakes = forecast_view.catalyst_stakes(None, "AZN")
    by_asset = {}
    for s in stakes.get("priced") or []:
        by_asset.setdefault(s["asset_id"], []).append(s)
    dev = development.for_company(None, "AZN", TODAY)
    dev_rows = {r["asset_id"]: r for part in ("failing", "rows", "uncosted", "refused")
                for r in dev.get(part) or []}
    cid = book.execute("SELECT id FROM companies WHERE ticker = 'AZN'").fetchone()[0]
    floor = {a["asset_id"]: a for a in launch_timing.for_company(book, cid, TODAY)}
    for g in out["gates"]:
        vg = lines[g["asset_id"]]["gate"]
        assert (g["now"], g["success"], g["failure"], g["p_gate"]) == (
            vg["per_share_now"], vg["per_share_success"], vg["per_share_failure"],
            vg["p_gate"]), g["name"]
        if g["stake"]:
            assert g["stake"]["id"] in {s["id"] for s in by_asset[g["asset_id"]]}
            assert g["stake"]["per_share"] == pytest.approx(g["swing"], abs=0.01), g["name"]
        row = dev_rows.get(g["asset_id"])
        assert ((g["development"] or {}).get("gate") or {}).get("cost_per_share") == (
            ((row or {}).get("gate") or {}).get("cost_per_share")), g["name"]
        if g["asset_id"] in floor:
            assert g["launch"]["decision_date"] == floor[g["asset_id"]].get("decision_date")
    n_priced = sum(1 for e in out["events"] if e["priced"])
    assert n_priced == len({s["id"] for s in stakes.get("priced") or []})
    assert sum(out["unpriced_reasons"].values()) == len(stakes.get("unpriced") or [])
