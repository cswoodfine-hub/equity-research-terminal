"""The focal context behind the Comps tab's Drivers and risks: catalysts and competition.

Logic tests build their own database and never touch the real book. The pharma engine is
named by hand (``landscape._big_pharma_ids`` is patched), and the forecast verdict and the
catalyst stakes are injected, which is also what proves the module never builds a book cold.

The guards at the foot read the built book and are skipped where there is none. Run them
off a backup copy rather than the live file:

    sqlite3 backend/er_tool.db ".backup '/tmp/book.db'"
    ER_TOOL_DB=/tmp/book.db .venv/bin/python -m pytest -q tests/test_comps_context.py
"""

import ast
import datetime as dt
import json
import time
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import comps_context as cc
import db
import forecast_view
import landscape
import main
import pool_crowding
import response_cache
import screen

TODAY = dt.date(2026, 9, 29)
AZN, NVO, CRSP, LLY, BAYN = 1, 2, 3, 4, 5
BIG = {AZN, NVO, LLY, BAYN}
OBESITY, OVERWEIGHT, ASTHMA, LUNG, HEART = 1, 2, 3, 4, 5
CLOSE = 100.0

# The verdict's modelled lines for AZN: asset id -> (per share, PoS, counted).
LINES = {10: (4.0, 0.55, True),      # sized by the model in obesity
         11: (10.0, 1.0, True),      # sized nowhere: counts in its own lead indication
         12: (2.0, 1.0, True),       # sized nowhere, no lead of its own: its molecule's
         14: (50.0, 0.3, True),      # sized nowhere, no lead anywhere: counts nowhere
         15: (7.0, 0.2, False)}      # not counted by the model: attributed nowhere


def _verdict(lines=None):
    lines = LINES if lines is None else lines
    return {"ok": True, "modelled": [
        {"asset_id": a, "per_share": ps, "pos": pos, "counted": counted}
        for a, (ps, pos, counted) in lines.items()]}


def _for(verdict):
    return lambda ticker: verdict


def _none(ticker):
    return None


# --- seeding -------------------------------------------------------------------------
def _assume(conn, asset_id, key, value=None, indication_id=None, text=None):
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value, text_value)"
                 " VALUES (?, ?, ?, ?, ?)", (asset_id, indication_id, key, value, text))


def _claim(conn, asset_id, indication_id, prevalence, incidence, peak, start, carry=None):
    """The rows that make an asset a claimant on an indication's patient pool."""
    for key, value in (("prevalence", prevalence), ("eligible_pct", 1.0),
                       ("incidence", incidence), ("penetration_peak_pct", peak),
                       ("ramp_midpoint_year", 4), ("ramp_steepness", 1.0)):
        _assume(conn, asset_id, key, value, indication_id)
    if carry is not None:
        _assume(conn, asset_id, "untreated_carryover_pct", carry, indication_id)
    _assume(conn, asset_id, "forecast_start_year", start)
    _assume(conn, asset_id, "discontinuation_pct", 0.1)


def _asset(conn, asset_id, owner, generic=None, brand=None, marketed=0, molecule=None):
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed, molecule_id) VALUES (?, ?, ?, ?, ?, ?)",
                 (asset_id, owner, generic, brand, marketed, molecule))


def _pipeline(conn, asset_id, indication_id, phase, lead=0, row_id=None):
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase, is_lead)"
                 " VALUES (?, ?, ?, ?, ?)", (row_id, asset_id, indication_id, phase, lead))


def _catalyst(conn, cid, company, date, kind="data readout", asset=None, title=None,
              confidence="estimated", url=None, status="pending", curated=0, pair=None):
    conn.execute(
        """INSERT INTO catalysts (id, company_id, asset_id, asset_indication_id, catalyst_type,
               expected_date, date_confidence, title, is_curated, source_url, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, company, asset, pair, kind, date, confidence, title, curated, url, status))


def _trial(conn, nct, asset, phase, conditions, meshes):
    conn.execute(
        "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, title, phase, conditions,"
        " mesh_terms) VALUES (?, ?, 1, 'A study', ?, ?, ?)",
        (nct, asset, phase, json.dumps(conditions),
         json.dumps({"meshes": [{"id": i, "term": t} for i, t in meshes], "ancestors": []})))


def _ctgov(nct):
    return f"https://clinicaltrials.gov/study/{nct}"


def _companies(conn):
    for cid, ticker in ((AZN, "AZN"), (NVO, "NVO"), (CRSP, "CRSP"), (LLY, "LLY"),
                        (BAYN, "BAYN")):
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     (cid, ticker, ticker))


def _book(tmp_path, name="context.db"):
    path = str(tmp_path / name)
    db.init(path)
    conn = db.get_connection(path)
    _companies(conn)
    for iid, label, mesh in ((OBESITY, "Obesity", "D009765"), (OVERWEIGHT, "Overweight", "D050177"),
                             (ASTHMA, "Asthma", "D001249"),
                             (LUNG, "Carcinoma, Non-Small-Cell Lung", "D002289"),
                             (HEART, "Heart Failure", "D006333")):
        conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES (?, ?, ?)",
                     (iid, label, mesh))

    # AstraZeneca. One population under two names (the migration groups them), so obesity
    # and overweight are one row.
    _asset(conn, 10, AZN, generic="Elecoglipron")
    _pipeline(conn, 10, OBESITY, "Phase 3")
    _pipeline(conn, 10, OVERWEIGHT, "Phase 3")
    _claim(conn, 10, OBESITY, 1_000_000, 20_000, 0.30, 2027)
    _asset(conn, 11, AZN, generic="Osimertinib", brand="Tagrisso", marketed=1)
    _pipeline(conn, 11, LUNG, "Approved", lead=1, row_id=500)
    _assume(conn, 11, "wacc", 0.08)
    _assume(conn, 11, "pos_success", 0.95)
    _assume(conn, 11, "pos_failure", 0.40)
    _asset(conn, 13, AZN, generic="Budesonide triple")
    _pipeline(conn, 13, ASTHMA, "Phase 3", lead=1)
    _asset(conn, 12, AZN, generic="Budesonide triple", brand="Breztri", marketed=1, molecule=13)
    _assume(conn, 12, "wacc", 0.08)
    _asset(conn, 14, AZN, generic="AZD0001")
    _assume(conn, 14, "wacc", 0.08)
    _asset(conn, 15, AZN, generic="AZD0002")
    _pipeline(conn, 15, HEART, "Phase 2")
    _assume(conn, 15, "pos", 0.2, HEART)
    _asset(conn, 16, AZN, generic="AZD0003")            # no modelled line

    # Novo: a rival candidate whose pool claim is written under the group's other name,
    # and an incumbent that arrives through a completed trial and its label.
    _asset(conn, 20, NVO, generic="Cagrilintide")
    _pipeline(conn, 20, OBESITY, "Phase 3")
    _claim(conn, 20, OVERWEIGHT, 1_000_000, 20_000, 0.50, 2028)
    _asset(conn, 21, NVO, generic="Semaglutide", brand="Wegovy", marketed=1)
    conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title,"
                 " phase, conditions) VALUES ('NCT00000021', 2, 21, 'STEP 1', 'Phase 3', ?)",
                 (json.dumps(["Obesity"]),))
    conn.execute("INSERT INTO labels (asset_id, setid, indications_text) VALUES (21, 's21',"
                 " 'WEGOVY is indicated to reduce excess body weight in adults with obesity')")

    # Lilly: a product sold for something else and trialled in lung, and a Phase 2 asset.
    _asset(conn, 40, LLY, generic="Abemaciclib", brand="Verzenio", marketed=1)
    conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title,"
                 " phase, conditions) VALUES ('NCT00000040', 4, 40, 'JUNIPER', 'Phase 3', ?)",
                 (json.dumps(["Non-Small Cell Lung Cancer"]),))
    conn.execute("INSERT INTO labels (asset_id, setid, indications_text) VALUES (40, 's40',"
                 " 'VERZENIO is indicated for the treatment of breast cancer')")
    _asset(conn, 41, LLY, generic="Olomorasib")
    _pipeline(conn, 41, LUNG, "Phase 2")

    # CRISPR: outside the pharma engine, partner in an asset another company owns.
    _assume(conn, 14, "partner_ticker", text="CRSP")

    for company, day, close in ((AZN, "2026-09-25", 98.0), (AZN, "2026-09-28", CLOSE),
                                (AZN, "2026-09-30", 999.0), (NVO, "2026-09-28", 50.0),
                                (CRSP, "2026-09-28", 54.0)):
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                     " VALUES (?, ?, ?, '1d')", (company, day, close))

    _trial(conn, "NCT07775404", 10, "Phase 3", ["Obesity"], [("D009765", "Obesity")])
    _trial(conn, "NCT00000002", 11, "Phase 2/3", ["Asthma"], [("D001249", "Asthma")])
    _catalyst(conn, 1, AZN, "2027-06-04", asset=10, url=_ctgov("NCT07775404"),
              title="Phase 3, A Study of Elecoglipron in Participants With Obesity")
    _catalyst(conn, 2, AZN, "2026-10", confidence="month", url=_ctgov("NCT00000002"),
              title="A study of osimertinib", pair=500)
    _catalyst(conn, 3, AZN, "2027-01-15", kind="PDUFA", asset=14, confidence="confirmed",
              title="PDUFA date for AZD0001", curated=1)
    _catalyst(conn, 4, AZN, "2027-03-31", confidence="quarter", title="Phase 1/2, first data")
    _catalyst(conn, 5, AZN, "2027-06-30", kind="EMA decision", asset=12, confidence="half",
              title="EMA decision on Breztri")
    _catalyst(conn, 6, AZN, "2027-02-01", asset=10, status="met", title="Phase 3, resolved")
    _catalyst(conn, 7, NVO, "2027-02-01", asset=20, title="Phase 3, Cagrilintide")
    _catalyst(conn, 8, AZN, "2027-08-01", asset=16, title="Phase 2, AZD0003")
    _catalyst(conn, 9, AZN, "2027-09-01", asset=15, title="Phase 2, AZD0002")
    conn.commit()
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    """A named pharma engine and an empty memo around every test."""
    monkeypatch.setattr(landscape, "_big_pharma_ids", lambda conn: BIG)
    cc.clear_memo()
    yield
    cc.clear_memo()


@pytest.fixture
def path(tmp_path):
    return _book(tmp_path)


@pytest.fixture
def out(path):
    return cc.build("AZN", path, TODAY, _for(_verdict()), _none)


def _items(payload):
    return {item["id"]: item for item in payload["catalysts"]["items"]}


def _rows(payload):
    return {row["indication"]["id"]: row for row in payload["competition"]["indications"]}


# --- 1. the company ------------------------------------------------------------------
def test_an_unknown_ticker_builds_nothing(path):
    assert cc.build("ZZZZ", path, TODAY, _none, _none) is None
    assert cc.build("azn", path, TODAY, _none, _none)["ticker"] == "AZN"


def test_the_top_level(out):
    assert out["schema"] == 1 and out["ticker"] == "AZN"
    assert out["today"] == "2026-09-29"
    assert out["window"] == {"from": "2026-09-29", "to": "2027-09-29"}
    assert out["complete"] is True and out["incomplete_reason"] is None
    # The latest close on or before today, not the one dated after it.
    assert out["price"] == {"close": CLOSE, "as_of": "2026-09-28"}
    assert out["model"] == {"state": "modelled", "assets": 5}
    assert out["generated_at"].endswith("Z")
    assert set(out) == {"schema", "ticker", "generated_at", "today", "window", "complete",
                        "incomplete_reason", "price", "model", "catalysts", "competition"}


# --- 2. the window -------------------------------------------------------------------
def _window_book(tmp_path, today):
    path = str(tmp_path / "window.db")
    db.init(path)
    conn = db.get_connection(path)
    _companies(conn)
    day = lambda n: (today + dt.timedelta(days=n)).isoformat()
    _catalyst(conn, 1, AZN, day(0), title="today")
    _catalyst(conn, 2, AZN, day(365), title="the last day")
    _catalyst(conn, 3, AZN, day(-1), title="yesterday")
    _catalyst(conn, 4, AZN, day(366), title="a day late")
    _catalyst(conn, 5, AZN, day(60)[:7], confidence="month", title="a month inside")
    _catalyst(conn, 6, AZN, None, title="undated")
    conn.commit()
    conn.close()
    return path


def test_the_window_is_today_to_today_plus_365_days(tmp_path):
    path = _window_book(tmp_path, TODAY)
    got = cc.build("AZN", path, TODAY, _none, _none)["catalysts"]
    assert sorted(i["id"] for i in got["items"]) == [1, 2, 5]
    assert got["total"] == 3 and got["sent"] == 3
    # Ordered by date as stored, then id: a month sorts before the days of that month.
    assert [i["id"] for i in got["items"]] == [1, 5, 2]


def test_the_count_is_the_screens_twelve_month_count(tmp_path):
    # The screen counts from SQLite's date('now'), which is the UTC date.
    today = dt.datetime.now(dt.timezone.utc).date()
    path = _window_book(tmp_path, today)
    conn = db.get_connection(path)
    try:
        expected = screen._catalysts_12m(conn, AZN)
    finally:
        conn.close()
    assert cc.build("AZN", path, today, _none, _none)["catalysts"]["total"] == expected == 3


def test_at_most_sixty_are_sent_and_all_are_counted(tmp_path):
    path = str(tmp_path / "many.db")
    db.init(path)
    conn = db.get_connection(path)
    _companies(conn)
    for n in range(70):
        _catalyst(conn, n + 1, AZN, (TODAY + dt.timedelta(days=n)).isoformat(), title="event",
                  curated=1 if n >= 65 else 0)
    conn.commit()
    conn.close()
    got = cc.build("AZN", path, TODAY, _none, _none)["catalysts"]
    assert got["total"] == 70 and got["sent"] == 60 and len(got["items"]) == 60
    assert got["counts"]["curated"] == 5          # counted over all seventy


# --- 3. the fields of a catalyst ------------------------------------------------------
def test_only_the_companys_pending_catalysts(out):
    assert sorted(_items(out)) == [1, 2, 3, 4, 5, 8, 9]
    assert out["catalysts"]["total"] == 7
    assert out["catalysts"]["counts"] == {"with_asset": 6, "with_indication": 2,
                                          "with_stake": 0, "with_asset_value": 5,
                                          "curated": 1}


def test_date_precision_and_kind(out):
    items = _items(out)
    assert [(items[i]["date"], items[i]["date_precision"], items[i]["date_confidence"])
            for i in (1, 2, 3, 4, 5)] == [
        ("2027-06-04", "day", "estimated"), ("2026-10", "month", "month"),
        ("2027-01-15", "day", "confirmed"), ("2027-03-31", "quarter", "quarter"),
        ("2027-06-30", "half", "half")]
    assert {i: items[i]["regulatory"] for i in (1, 3, 5)} == {1: False, 3: True, 5: True}
    assert items[3]["kind"] == "PDUFA" and items[1]["kind"] == "data readout"
    for kind in ("PDUFA", "regulatory decision", "AdCom", "EMA decision"):
        assert kind in cc.REGULATORY_KINDS
    assert items[3]["is_curated"] is True and items[1]["is_curated"] is False


def test_the_trial_is_read_from_the_source_url(out):
    items = _items(out)
    assert items[1]["nct_id"] == "NCT07775404"
    assert items[1]["source_url"] == "https://clinicaltrials.gov/study/NCT07775404"
    assert items[3]["nct_id"] is None and items[3]["source_url"] is None


def test_asset_and_phase_come_from_the_trial_when_the_row_names_no_asset(out):
    items = _items(out)
    # The catalyst row carries no asset id: the trial's asset and the trial's phase.
    assert items[2]["asset"] == {"id": 11, "name": "Tagrisso", "is_marketed": True}
    assert items[2]["phase"] == "Phase 2/3"
    # The row's own asset, named by brand, then generic, then code.
    assert items[1]["asset"] == {"id": 10, "name": "Elecoglipron", "is_marketed": False}
    assert items[1]["phase"] == "Phase 3"
    # No trial: the leading phase of the title, else nothing.
    assert items[4]["phase"] == "Phase 1/2" and items[8]["phase"] == "Phase 2"
    assert items[3]["phase"] is None


def test_the_indication_by_the_pair_then_by_the_trials_mesh(out):
    items = _items(out)
    # asset_indication_id wins over the trial's own descriptor (asthma).
    assert items[2]["indication"] == {"id": LUNG, "name": "Carcinoma, Non-Small-Cell Lung"}
    assert items[1]["indication"] == {"id": OBESITY, "name": "Obesity"}
    assert items[3]["indication"] is None
    assert items[3]["na"]["indication"] == "no_indication_link"


def test_every_null_of_a_catalyst_has_its_reason(out):
    for item in out["catalysts"]["items"]:
        for field in ("asset", "indication", "stake", "asset_value"):
            assert (item[field] is None) == (field in item["na"]), (item["id"], field)
    assert _items(out)[4]["na"] == {"asset": "no_asset", "indication": "no_indication_link",
                                    "stake": "no_asset", "asset_value": "no_asset"}


def test_the_asset_value_is_the_modelled_line(out):
    items = _items(out)
    assert items[1]["asset_value"] == {"per_share": 4.0, "pct_of_price": pytest.approx(0.04),
                                       "pos": 0.55, "counted": True}
    # A line the model does not count is still the asset's value, and says so.
    assert items[9]["asset_value"]["counted"] is False
    assert items[8]["asset_value"] is None and items[8]["na"]["asset_value"] == "not_modelled"


# --- 4. the stake --------------------------------------------------------------------
def test_a_priced_catalyst_carries_the_stake_engines_figure(path):
    stakes = {"priced": [{"id": 1, "per_share": -2.5, "pos_now": 0.55, "pos_success": 0.9,
                          "pos_failure": 0.2, "share": 0.4}], "unpriced": []}
    got = cc.build("AZN", path, TODAY, _for(_verdict()), _for(stakes))
    item = _items(got)[1]
    assert item["stake"] == {"per_share": -2.5, "pct_of_price": pytest.approx(2.5 / CLOSE),
                             "pos_now": 0.55, "pos_success": 0.9, "pos_failure": 0.2,
                             "economics_share": 0.4, "basis": "stated", "gate": None}
    assert "stake" not in item["na"]
    assert got["catalysts"]["counts"]["with_stake"] == 1
    assert item["asset_value"]["per_share"] == 4.0          # beside the stake, not instead


def test_a_derived_stake_says_so_and_names_its_gate(path):
    stakes = {"priced": [{"id": 1, "per_share": 3.0, "pos_now": 0.55, "pos_success": 0.9,
                          "pos_failure": 0.0, "share": 1.0, "legs_basis": "derived",
                          "gate_label": "Phase 3 readout"}], "unpriced": []}
    got = cc.build("AZN", path, TODAY, _for(_verdict()), _for(stakes))
    stake = _items(got)[1]["stake"]
    assert stake["basis"] == "derived" and stake["gate"] == "Phase 3 readout"
    assert stake["pos_failure"] == 0.0 and stake["pct_of_price"] == pytest.approx(0.03)


def test_each_reason_no_stake_is_stated(out):
    items = _items(out)
    assert all(item["stake"] is None for item in items.values())
    assert items[4]["na"]["stake"] == "no_asset"            # the event names no asset
    assert items[8]["na"]["stake"] == "not_modelled"        # the asset has no line
    # The engine ran, since Elecoglipron is a modelled pipeline line, and found no gate:
    # the fixture's owner is not on the pharma engine's gate model.
    assert items[1]["na"]["stake"] == "no_gate"
    assert items[5]["na"]["stake"] == "no_gate"             # marketed, no stated legs
    # Tagrisso's readout is dated to a month the engine's calendar, read from the real
    # date, has already reached, so the engine returned nothing for it.
    assert items[2]["na"]["stake"] == "not_in_stakes"


def test_the_engines_own_reason_is_the_reason_stated(path):
    """na.stake carries the stake engine's reason for the catalyst; where the engine
    returned nothing, a marketed product with no stated legs has no gate, and anything
    else was not read."""
    stakes = {"priced": [], "unpriced": [{"id": 1, "reason": "same_gate_later"},
                                         {"id": 9, "reason": "not_gate_phase"}]}
    items = _items(cc.build("AZN", path, TODAY, _for(_verdict()), _for(stakes)))
    assert items[1]["na"]["stake"] == "same_gate_later"
    assert items[9]["na"]["stake"] == "not_gate_phase"
    assert items[5]["na"]["stake"] == "no_gate"             # Breztri: marketed, no legs
    assert items[2]["na"]["stake"] == "not_in_stakes"       # Tagrisso carries both legs
    assert items[3]["na"]["stake"] == "not_in_stakes"       # a pipeline line, no answer


def test_no_price_is_its_own_reason(path):
    conn = db.get_connection(path)
    conn.execute("DELETE FROM prices WHERE company_id = ?", (AZN,))
    conn.commit()
    conn.close()
    got = cc.build("AZN", path, TODAY, _for(_verdict()), _none)
    assert got["price"] is None
    item = _items(got)[1]
    assert item["na"]["stake"] == "no_price" and item["na"]["asset_value"] == "no_price"
    row = _rows(got)[OBESITY]
    assert row["value"]["per_share"] == 4.0 and row["value"]["pct_of_price"] is None
    assert row["na"]["value_pct"] == "no_price"


def test_the_stake_engine_runs_only_where_it_could_price_something(path, monkeypatch):
    calls = []

    def engine(db_path, ticker):
        calls.append(ticker)
        return {"priced": [{"id": 3, "per_share": 1.5, "pos_now": 0.3, "pos_success": 0.9,
                            "pos_failure": 0.1, "share": 1.0}], "unpriced": []}

    monkeypatch.setattr(forecast_view, "catalyst_stakes", engine)
    # Only marketed lines are modelled and no asset with an in-window catalyst carries
    # both stated legs (Tagrisso's are taken off), so the engine could price nothing and
    # is never asked.
    conn = db.get_connection(path)
    conn.execute("DELETE FROM assumptions WHERE asset_id = 11"
                 "   AND key IN ('pos_success', 'pos_failure')")
    conn.commit()
    conn.close()
    marketed = _verdict({11: LINES[11], 12: LINES[12]})
    cc.build("AZN", path, TODAY, _for(marketed), _none)
    assert calls == []

    # A modelled pipeline line with a catalyst in the window has a gate to price.
    got = cc.build("AZN", path, TODAY, _for(_verdict()), _none)
    assert calls == ["AZN"]
    assert _items(got)[3]["stake"]["per_share"] == 1.5

    # So does an asset carrying both stated legs, modelled line or not.
    conn = db.get_connection(path)
    _assume(conn, 12, "pos_success", 0.9)
    _assume(conn, 12, "pos_failure", 0.1)
    conn.commit()
    conn.close()
    cc.build("AZN", path, TODAY, _for(marketed), _none)
    assert calls == ["AZN", "AZN"]
    # A stakes read already computed is used as it stands.
    cc.build("AZN", path, TODAY, _for(_verdict()), _for({"priced": [], "unpriced": []}))
    assert calls == ["AZN", "AZN"]

    def broken(db_path, ticker):
        raise RuntimeError("no forecast")

    monkeypatch.setattr(forecast_view, "catalyst_stakes", broken)
    got = cc.build("AZN", path, TODAY, _for(_verdict()), _none)
    assert _items(got)[3]["stake"] is None and _items(got)[3]["na"]["stake"] == "not_in_stakes"


# --- 5. never a cold book --------------------------------------------------------------
def test_a_verdict_that_is_not_cached_is_never_built(path, monkeypatch):
    def cold(*args, **kwargs):
        raise AssertionError("the book must not be built cold")

    monkeypatch.setattr(forecast_view, "company_verdict", cold)
    monkeypatch.setattr(landscape, "landscape", cold)
    monkeypatch.setattr(landscape, "_model_lines", cold)
    got = cc.build("AZN", path, TODAY, _none, _none)
    assert got["model"] == {"state": "not_computed", "assets": 0}
    assert got["complete"] is False and got["incomplete_reason"] == "model_not_computed"
    item = _items(got)[1]
    assert item["asset_value"] is None
    assert item["na"]["asset_value"] == "model_not_computed"
    assert item["na"]["stake"] == "model_not_computed"
    comp = got["competition"]
    assert comp["covered"] is True and comp["ranked_by"] == "contest" and comp["valued"] == 0
    for row in comp["indications"]:
        assert row["value"] == {"per_share": None, "pct_of_price": None, "assets": 0}
        assert row["na"]["value"] == "model_not_computed"
    # The same with nothing injected: the suite runs with the response cache off.
    assert cc.build("AZN", path, TODAY)["model"]["state"] == "not_computed"


def test_the_verdict_and_the_stakes_default_to_the_response_cache(path, monkeypatch):
    reads = {"/companies/AZN/forecast-verdict": _verdict(),
             "/companies/AZN/catalysts/stakes": {"priced": [
                 {"id": 1, "per_share": 3.0, "pos_now": 0.5, "pos_success": 0.9,
                  "pos_failure": 0.1, "share": 1.0}]}}
    monkeypatch.setattr(response_cache, "cached_json", lambda p, query="": reads.get(p))
    got = cc.build("AZN", path, TODAY)
    assert got["model"] == {"state": "modelled", "assets": 5} and got["complete"] is True
    assert _items(got)[1]["stake"]["pct_of_price"] == pytest.approx(0.03)


def test_the_model_states(path):
    # A verdict that failed.
    got = cc.build("AZN", path, TODAY, _for({"ok": False}), _none)
    assert got["model"]["state"] == "failed" and got["complete"] is True
    assert _items(got)[1]["na"]["asset_value"] == "not_modelled"
    assert {r["na"]["value"] for r in got["competition"]["indications"]} == {"not_modelled"}
    # No asset the company owns or partners carries assumptions: the verdict is not asked.
    asked = []
    got = cc.build("NVO", path, TODAY, _none, _none)
    assert got["model"]["state"] == "not_computed"
    conn = db.get_connection(path)
    conn.execute("DELETE FROM assumptions WHERE asset_id = 20")
    conn.commit()
    conn.close()
    got = cc.build("NVO", path, TODAY, lambda t: asked.append(t), _none)
    assert got["model"] == {"state": "not_modelled", "assets": 0} and asked == []
    assert got["complete"] is True
    assert got["competition"]["ranked_by"] == "contest"
    assert {r["na"]["value"] for r in got["competition"]["indications"]} == {"not_modelled"}
    # The named partner of an asset another company owns has a book.
    got = cc.build("CRSP", path, TODAY, _for(_verdict({14: (6.0, 0.8, True)})), _none)
    assert got["model"] == {"state": "modelled", "assets": 1}


# --- 6. outside the pharma engine ------------------------------------------------------
def test_a_company_outside_the_pharma_engine_is_not_covered(path, monkeypatch):
    def scan(*args, **kwargs):
        raise AssertionError("the landscape must not be read for this company")

    monkeypatch.setattr(landscape, "candidates", scan)
    monkeypatch.setattr(landscape, "indications", scan)
    got = cc.build("CRSP", path, TODAY, _none, _none)
    assert got["competition"] == {"covered": False, "reason": "not_big_pharma",
                                  "ranked_by": None, "total": 0, "valued": 0,
                                  "indications": []}
    assert got["catalysts"]["total"] == 0 and got["catalysts"]["items"] == []


def test_a_pharma_company_in_no_landscape_has_no_indications(path):
    got = cc.build("BAYN", path, TODAY, _none, _none)
    assert got["competition"]["covered"] is False
    assert got["competition"]["reason"] == "no_indications"
    assert got["model"]["state"] == "not_modelled" and got["price"] is None


# --- 7. attribution and ranking --------------------------------------------------------
def test_value_is_attributed_by_the_stated_rule_and_ranks_the_rows(out):
    comp = out["competition"]
    assert comp["covered"] is True and comp["reason"] is None
    assert comp["ranked_by"] == "model_value"
    assert comp["total"] == 4 and comp["valued"] == 3
    rows = comp["indications"]
    # Lung by the asset's own lead flag, obesity by the model's indication, asthma by the
    # molecule's lead flag. The $50 asset with neither counts nowhere, and the line the
    # model does not count leaves heart failure without a value.
    assert [(r["indication"]["id"], r["value"]["per_share"], r["value"]["assets"])
            for r in rows] == [(LUNG, 10.0, 1), (OBESITY, 4.0, 1), (ASTHMA, 2.0, 1)]
    assert [r["value"]["pct_of_price"] for r in rows] == [
        pytest.approx(0.10), pytest.approx(0.04), pytest.approx(0.02)]
    assert all("value" not in r["na"] for r in rows)


def test_one_population_under_two_names_is_one_row(out):
    row = _rows(out)[OBESITY]
    # Obesity and overweight are one group; the row carries the more contested name.
    assert row["indication"]["name"] == "Obesity"
    assert sorted(row["indication"]["members"]) == ["Obesity", "Overweight"]
    assert OVERWEIGHT not in _rows(out)


def test_own_candidates_carry_the_attributed_value(out):
    rows = _rows(out)
    assert rows[OBESITY]["own"]["candidates"] == [
        {"name": "Elecoglipron", "stage": "phase3", "phase_here": "Phase 3",
         "is_marketed": False, "asset_ids": [10], "per_share": 4.0, "attributed": True}]
    assert rows[OBESITY]["own"]["more"] == 0
    lung = rows[LUNG]["own"]["candidates"][0]
    assert lung["stage"] == "marketed" and lung["per_share"] == 10.0 and lung["asset_ids"] == [11]
    # The asthma value sits on the brand, which no pipeline row places here: the candidate
    # listed is the molecule, with no value of its own.
    asthma = rows[ASTHMA]["own"]["candidates"][0]
    assert asthma["per_share"] is None and asthma["attributed"] is False


def test_with_no_model_the_rows_are_ranked_by_contest(path):
    got = cc.build("AZN", path, TODAY, _none, _none)["competition"]
    assert got["ranked_by"] == "contest" and got["total"] == 4 and got["valued"] == 0
    # Companies, then assets, then name: the landscape's own order.
    assert [r["indication"]["id"] for r in got["indications"]] == [LUNG, OBESITY, ASTHMA, HEART]


def test_a_modelled_company_with_no_value_in_any_listed_group(path):
    got = cc.build("AZN", path, TODAY, _for(_verdict({14: (50.0, 0.3, True)})), _none)
    comp = got["competition"]
    assert comp["ranked_by"] == "contest" and comp["valued"] == 0
    assert {r["na"]["value"] for r in comp["indications"]} == {"no_attributed_asset"}


def test_at_most_five_rows_and_five_own_candidates(tmp_path):
    path = str(tmp_path / "wide.db")
    db.init(path)
    conn = db.get_connection(path)
    _companies(conn)
    lines = {}
    names = ("Psoriasis", "Migraine Disorders", "Hypertension", "Alopecia Areata", "Gout",
             "Lupus Nephritis", "Colitis, Ulcerative")
    for n in range(7):
        conn.execute("INSERT INTO indications (id, name) VALUES (?, ?)", (100 + n, names[n]))
        _asset(conn, 200 + n, AZN, generic=f"AZD9{n:03d}")
        _pipeline(conn, 200 + n, 100 + n, "Phase 3", lead=1)
        _assume(conn, 200 + n, "wacc", 0.08)
        lines[200 + n] = (float(n + 1), 0.5, True)
    for n in range(7):                                   # seven candidates in one disease
        _asset(conn, 300 + n, AZN, generic=f"AZD8{n:03d}")
        _pipeline(conn, 300 + n, 106, "Phase 2")
    conn.commit()
    conn.close()
    comp = cc.build("AZN", path, TODAY, _for(_verdict(lines)), _none)["competition"]
    assert comp["total"] == 7 and comp["valued"] == 7 and len(comp["indications"]) == 5
    assert [r["value"]["per_share"] for r in comp["indications"]] == [7.0, 6.0, 5.0, 4.0, 3.0]
    own = comp["indications"][0]["own"]
    assert own["n"] == 8 and len(own["candidates"]) == 5 and own["more"] == 3
    # By attributed value, then stage, then name.
    assert own["candidates"][0]["name"] == "AZD9006" and own["candidates"][0]["per_share"] == 7.0
    assert [c["name"] for c in own["candidates"][1:]] == ["AZD8000", "AZD8001", "AZD8002",
                                                          "AZD8003"]


# --- 8. counts are the landscape's own -------------------------------------------------
def _bucket_of(stage_text):
    if stage_text == "Marketed":
        return "marketed"
    if "Phase 3" in stage_text or "Phase 2/3" in stage_text:
        return "phase3"
    return "phase2" if "Phase 2" in stage_text else "other"


@pytest.mark.parametrize("indication_id", [LUNG, OBESITY])
def test_counts_are_the_landscapes_own(path, out, monkeypatch, indication_id):
    monkeypatch.setattr(landscape, "_model_lines", lambda db_path, tickers, verdict_for=None: {})
    land = landscape.landscape(path, indication_id)
    row = _rows(out)[indication_id]
    assert row["own"]["n"] + row["rivals"]["n"] == len(land["candidates"])
    assert row["own"]["n"] + row["rivals"]["n"] == land["coverage"]["candidates"]
    expected = Counter(_bucket_of(c["stage"]) for c in land["candidates"])
    got = Counter()
    for side in ("own", "rivals"):
        got.update({k: v for k, v in row[side]["by_stage"].items() if v})
    assert got == expected
    assert row["rivals"]["companies"] == len({c["ticker"] for c in land["candidates"]} - {"AZN"})


def test_stage_buckets(out):
    rows = _rows(out)
    # Lung: Tagrisso is marketed here; Verzenio is sold for breast cancer and reached
    # Phase 3 here; olomorasib is in Phase 2.
    assert rows[LUNG]["own"]["by_stage"] == {"marketed": 1, "phase3": 0, "phase2": 0, "other": 0}
    assert rows[LUNG]["rivals"] == {"n": 2, "companies": 1, "by_stage": {
        "marketed": 0, "phase3": 1, "phase2": 1, "other": 0}}
    # Obesity: Wegovy arrives by its completed trial and its label names the disease.
    assert rows[OBESITY]["rivals"] == {"n": 2, "companies": 1, "by_stage": {
        "marketed": 1, "phase3": 1, "phase2": 0, "other": 0}}
    assert cc._stage(True, None, False) == "marketed"
    assert cc._stage(True, "Phase 2/3", False) == "phase3"
    assert cc._stage(False, "Phase 1", False) == "other"
    assert cc._stage(False, None, False) == "other"


# --- 9. the pool ---------------------------------------------------------------------
def _pool_book(tmp_path, claims):
    """One ungrouped disease, a candidate each for AZN, NVO and LLY, and the claims given
    as (asset, prevalence, incidence, peak penetration)."""
    path = str(tmp_path / "pool.db")
    db.init(path)
    conn = db.get_connection(path)
    _companies(conn)
    conn.execute("INSERT INTO indications (id, name) VALUES (?, 'Asthma')", (ASTHMA,))
    for asset_id, owner in ((10, AZN), (20, NVO), (40, LLY)):
        _asset(conn, asset_id, owner, generic=f"Drug {asset_id}")
        _pipeline(conn, asset_id, ASTHMA, "Phase 3")
    for asset_id, prevalence, incidence, peak in claims:
        _claim(conn, asset_id, ASTHMA, prevalence, incidence, peak, 2027)
    conn.commit()
    conn.close()
    return path


@pytest.mark.parametrize("claims, na, patients", [
    ([], {"pool": "no_pool"}, None),
    ([(10, 1e6, 2e4, 0.3)], {"crowding": "single_claimant"}, 1e6),
    # A pool stated equal to its inflow is each year's new patients: nothing stands.
    ([(10, 5e4, 5e4, 0.3), (20, 5e4, 5e4, 0.3)], {"crowding": "flow_pool"}, 0.0),
    ([(10, 1e3, 5e3, 0.5), (20, 1e3, 5e3, 0.5)], {"crowding": "claims_exceed_pool"}, 1e3),
    ([(10, 1e6, 1e3, 0.002), (20, 1e6, 1e3, 0.002)], {"crowding": "share_under_1pct"}, 1e6),
    # Two rivals share the pool and the company draws on none of it.
    ([(20, 1e6, 2e4, 0.3), (40, 1e6, 2e4, 0.3)], {"company_pool": "no_claimant"}, 1e6),
    # The company's claim is on a different population: it is modelled alone.
    ([(10, 5e5, 2e4, 0.3), (20, 1e6, 2e4, 0.3), (40, 1e6, 2e4, 0.3)],
     {"company_pool": "no_claimant"}, 1e6),
])
def test_each_reason_no_pool_share_is_stated(tmp_path, claims, na, patients):
    path = _pool_book(tmp_path, claims)
    row = cc.build("AZN", path, TODAY, _none, _none)["competition"]["indications"][0]
    reasons = {k: v for k, v in row["na"].items() if k != "value"}
    assert reasons == na
    assert row["company_pool"] is None
    if "pool" in na:
        assert row["pool"] is None and row["crowding"] is None
    else:
        assert row["pool"]["patients"] == patients
        assert row["pool"]["claimants"] == len(claims)
        assert (row["crowding"] is None) == ("crowding" in na)
    if len(claims) == 3:
        assert row["pool"]["pooled_claimants"] == 2 and row["pool"]["companies"] == 2


def test_a_shared_pool_and_each_companys_part_of_it(path):
    azn = _rows(cc.build("AZN", path, TODAY, _for(_verdict()), _none))[OBESITY]
    nvo = cc.build("NVO", path, TODAY, _none, _none)["competition"]["indications"]
    nvo = next(r for r in nvo if r["indication"]["id"] == OBESITY)

    # The same figures straight from the pool model, one claim under each name.
    conn = db.get_connection(path)
    try:
        claims = pool_crowding.claimants(conn, OBESITY)
    finally:
        conn.close()
    assert {c["asset_id"] for c in claims} == {10, 20}
    solved = pool_crowding.solve(claims, years=23, first_year=2027)
    peaks = {a["asset_id"]: (max(a["uncrowded"]), max(a["crowded"])) for a in solved["assets"]}
    summary = pool_crowding.summary(solved)
    total = peaks[10][1] + peaks[20][1]

    assert azn["pool"] == {"patients": 1_000_000.0, "claimants": 2, "pooled_claimants": 2,
                           "companies": 2}
    assert azn["pool"] == nvo["pool"] and azn["crowding"] == nvo["crowding"]
    crowding = azn["crowding"]
    assert crowding["uncrowded_share"] == pytest.approx(summary["uncrowded_share"])
    assert crowding["crowded_share"] == pytest.approx(summary["crowded_share"])
    assert crowding["kept"] == pytest.approx(summary["crowded_share"] / summary["uncrowded_share"])
    assert crowding["peak_year"] == summary["peak_year"]
    assert 0 < crowding["crowded_share"] < crowding["uncrowded_share"] <= 1

    mine, theirs = azn["company_pool"], nvo["company_pool"]
    assert mine["claimants"] == 1 and theirs["claimants"] == 1
    assert mine["keeps"] == pytest.approx(peaks[10][1] / peaks[10][0])
    assert theirs["keeps"] == pytest.approx(peaks[20][1] / peaks[20][0])
    assert 0 < mine["keeps"] < 1
    assert mine["share_of_claims"] == pytest.approx(peaks[10][1] / total)
    assert mine["share_of_claims"] + theirs["share_of_claims"] == pytest.approx(1.0)
    assert mine["share_of_pool"] == pytest.approx(peaks[10][1] / 1_000_000)
    # Novo claims the larger share, so it leads and AZN is second of two.
    assert (theirs["rank"], mine["rank"]) == (1, 2)
    assert mine["of_companies"] == theirs["of_companies"] == 2
    assert mine["leader"] == theirs["leader"] == {
        "ticker": "NVO", "share_of_claims": pytest.approx(peaks[20][1] / total)}
    assert azn["na"] == {} and "company_pool" not in nvo["na"]


def test_every_null_of_a_row_has_its_reason(path):
    for verdict in (_for(_verdict()), _none):
        for row in cc.build("AZN", path, TODAY, verdict, _none)["competition"]["indications"]:
            na = row["na"]
            assert (row["pool"] is None) == ("pool" in na)
            assert (row["crowding"] is None) == ("pool" in na or "crowding" in na)
            assert (row["company_pool"] is None) == bool(
                {"pool", "crowding", "company_pool"} & set(na))
            assert (row["value"]["per_share"] is None) == ("value" in na)
            assert set(na) <= {"pool", "crowding", "company_pool", "value", "value_pct"}


def test_reason_codes_are_the_contracts(path):
    codes = {"no_asset", "no_price", "not_modelled", "model_not_computed", "not_in_stakes",
             "no_indication_link", "no_attributed_asset", "no_pool",
             "single_claimant", "flow_pool", "claims_exceed_pool", "share_under_1pct",
             "no_claimant", "not_big_pharma", "no_indications",
             # The stake engine's own reasons, forecast_view.STAKE_REASONS.
             "no_forecast", "nil", "no_gate", "regulatory_not_gate", "not_a_gate",
             "no_trial_link", "past_gate", "not_gate_phase", "phase_ahead_of_book",
             "other_indication", "same_gate_later"}
    assert set(forecast_view.STAKE_REASONS) <= codes
    seen = set()
    for ticker in ("AZN", "NVO", "CRSP", "BAYN"):
        for verdict in (_for(_verdict()), _none):
            got = cc.build(ticker, path, TODAY, verdict, _none)
            if got["competition"]["reason"]:
                seen.add(got["competition"]["reason"])
            for item in got["catalysts"]["items"]:
                seen |= set(item["na"].values())
            for row in got["competition"]["indications"]:
                seen |= set(row["na"].values())
    assert seen <= codes


# --- 10. strict JSON, Python 3.9 -------------------------------------------------------
def test_strict_json(path):
    lines = dict(LINES)
    verdict = _verdict(lines)
    verdict["modelled"].append({"asset_id": 16, "per_share": float("nan"), "pos": 0.5})
    verdict["modelled"].append({"asset_id": 13, "per_share": float("inf"), "pos": 0.5})
    verdict["modelled"][0]["pos"] = float("nan")
    got = cc.build("AZN", path, TODAY, _for(verdict), _none)
    body = json.dumps(got, allow_nan=False)
    assert json.loads(body) == got
    # A value that is not a finite number is no value: the line is left out.
    assert got["model"]["assets"] == 5
    assert _items(got)[8]["asset_value"] is None
    assert _items(got)[1]["asset_value"]["pos"] is None
    assert cc._clean({"a": float("nan"), 1: (float("inf"), 2.5)}) == {"a": None, "1": [None, 2.5]}


def test_the_module_is_python_3_9():
    source = Path(cc.__file__).read_text()
    ast.parse(source, feature_version=(3, 9))
    assert "from __future__ import annotations" in source
    assert chr(0x2014) not in source               # no em dash


# --- 11. the group memo ----------------------------------------------------------------
def test_a_second_build_under_the_same_stamp_does_not_rescan(path, monkeypatch):
    calls = []
    scan = landscape.candidates

    def counted(conn, members):
        calls.append(sorted(m["id"] for m in members))
        return scan(conn, members)

    monkeypatch.setattr(landscape, "candidates", counted)
    first = cc.build("AZN", path, TODAY, _for(_verdict()), _none)
    assert len(calls) == 3                         # one scan a returned group
    second = cc.build("AZN", path, TODAY, _for(_verdict()), _none)
    assert len(calls) == 3
    assert {k: v for k, v in first.items() if k != "generated_at"} == {
        k: v for k, v in second.items() if k != "generated_at"}
    # Another company asking about the same population reuses the group.
    cc.build("NVO", path, TODAY, _none, _none)
    assert len(calls) == 3

    # A write moves the stamp, and the groups are read again.
    conn = db.get_connection(path)
    _asset(conn, 22, NVO, generic="Amycretin")
    _pipeline(conn, 22, OBESITY, "Phase 3")
    conn.commit()
    conn.close()
    third = cc.build("AZN", path, TODAY, _for(_verdict()), _none)
    assert len(calls) == 6
    assert _rows(third)[OBESITY]["rivals"]["n"] == _rows(first)[OBESITY]["rivals"]["n"] + 1


def test_the_memo_is_bounded(path):
    stamp = cc._stamp(path)
    for n in range(cc.MEMO_MAX + 10):
        cc._memo_get(stamp, f"g{n}")
        cc._memo_put(stamp, f"g{n}", {"n": n})
    assert len(cc._memo["groups"]) == cc.MEMO_MAX
    assert cc._memo_get(stamp, "g0") is None and cc._memo_get(stamp, "g20") == {"n": 20}
    # A detail computed under a stamp that has since moved is not kept.
    moved = stamp + ("later",)
    cc._memo_get(moved, "x")
    cc._memo_put(stamp, "late", {"n": -1})
    assert cc._memo_get(moved, "late") is None


# --- 12. the route and the cache -------------------------------------------------------
def test_the_route(path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", Path(path))
    client = TestClient(main.app)
    assert client.get("/companies/ZZZZ/comps-context").status_code == 404

    # The verdict is not cached: the body says so and is kept out of the response cache.
    response = client.get("/companies/AZN/comps-context")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == 1 and body["ticker"] == "AZN" and body["complete"] is False
    assert response.headers.get(response_cache.SKIP) == "1"

    reads = {"/companies/AZN/forecast-verdict": _verdict()}
    monkeypatch.setattr(response_cache, "cached_json", lambda p, query="": reads.get(p))
    response = client.get("/companies/azn/comps-context")
    assert response.json()["complete"] is True
    assert response.json()["model"] == {"state": "modelled", "assets": 5}
    assert response_cache.SKIP not in response.headers


def test_the_cache_stores_only_a_complete_body(path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", Path(path))
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE", "1")
    monkeypatch.setattr(response_cache, "start_warming", lambda base: None)
    response_cache.clear()
    key = "/companies/AZN/comps-context?"
    try:
        client = TestClient(main.app)
        first = client.get("/companies/AZN/comps-context")
        assert first.headers.get(response_cache.SKIP) == "1"
        assert key not in response_cache._entries
        reads = {"/companies/AZN/forecast-verdict": _verdict()}
        monkeypatch.setattr(response_cache, "cached_json", lambda p, query="": reads.get(p))
        second = client.get("/companies/AZN/comps-context")
        assert second.json()["complete"] is True and second.headers.get("x-cache") == "miss"
        assert key in response_cache._entries
        assert client.get("/companies/AZN/comps-context").headers.get("x-cache") == "hit"
    finally:
        response_cache.clear()


def test_the_context_is_warmed_after_the_verdict_it_embeds():
    reads = response_cache.COMPANY_READS
    assert reads[-1] == "/companies/{t}/comps-context"
    assert reads.index(cc.VERDICT_PATH) < len(reads) - 1
    assert reads.index(cc.STAKES_PATH) < len(reads) - 1
    assert response_cache.cacheable("/companies/AZN/comps-context", "")


# --- 13. book guards -------------------------------------------------------------------
@pytest.fixture
def real_engine(monkeypatch):
    """The book's own pharma engine, in place of the named one."""
    monkeypatch.undo()
    cc.clear_memo()
    landscape._big.clear()
    yield
    landscape._big.clear()


def _obesity(payload):
    return next(r for r in payload["competition"]["indications"]
                if "Obesity" in r["indication"]["members"])


def test_book_the_pharma_engine_is_covered_and_the_rest_is_not(book, real_engine):
    verdicts = {t: forecast_view.company_verdict(None, t) for t in ("AZN", "LLY")}
    built = {}
    for ticker in ("AZN", "LLY"):
        got = cc.build(ticker, verdict_for=verdicts.get, stakes_for=_none)
        json.dumps(got, allow_nan=False)
        built[ticker] = got
        comp = got["competition"]
        assert got["model"]["state"] == "modelled" and got["complete"] is True, ticker
        assert comp["covered"] is True and comp["ranked_by"] == "model_value", ticker
        assert len(comp["indications"]) == 5, ticker
        values = [r["value"]["per_share"] for r in comp["indications"]]
        assert values == sorted(values, reverse=True) and values[-1] > 0, ticker
        for row in comp["indications"]:
            assert row["own"]["n"] >= 1, (ticker, row["indication"]["name"])
            assert sum(row["own"]["by_stage"].values()) == row["own"]["n"]
            assert sum(row["rivals"]["by_stage"].values()) == row["rivals"]["n"]
        row = _obesity(got)
        assert 0 < row["crowding"]["crowded_share"] <= row["crowding"]["uncrowded_share"] <= 1
        assert 0 < row["company_pool"]["keeps"] <= 1, ticker
        assert 0 < row["company_pool"]["share_of_claims"] <= 1, ticker
        assert got["catalysts"]["total"] >= got["catalysts"]["sent"] == len(
            got["catalysts"]["items"])
        assert len(json.dumps(got, separators=(",", ":")).encode("utf-8")) < 60 * 1024
    # One pool, read the same from either side.
    assert _obesity(built["AZN"])["pool"] == _obesity(built["LLY"])["pool"]
    assert _obesity(built["AZN"])["crowding"] == _obesity(built["LLY"])["crowding"]

    # Warm means the verdict and the stakes are both in the response cache, which warms
    # the stakes read ahead of this one (response_cache.COMPANY_READS).
    stakes = {"AZN": forecast_view.catalyst_stakes(None, "AZN")}
    started = time.perf_counter()
    again = cc.build("AZN", verdict_for=verdicts.get, stakes_for=stakes.get)
    assert time.perf_counter() - started < 0.3
    assert again["competition"] == built["AZN"]["competition"]
    assert again["catalysts"] == built["AZN"]["catalysts"]

    crsp = cc.build("CRSP", verdict_for=_none, stakes_for=_none)
    assert crsp["competition"]["covered"] is False
    assert crsp["competition"]["reason"] == "not_big_pharma"


def test_book_the_count_is_the_screens_and_every_null_has_a_reason(book, real_engine):
    today = dt.datetime.now(dt.timezone.utc).date()
    for ticker in ("AZN", "VRTX", "CRSP"):
        company_id = book.execute("SELECT id FROM companies WHERE ticker = ?",
                                  (ticker,)).fetchone()[0]
        got = cc.build(ticker, today=today, verdict_for=_none, stakes_for=_none)
        assert got["catalysts"]["total"] == screen._catalysts_12m(book, company_id), ticker
        for item in got["catalysts"]["items"]:
            for field in ("asset", "indication", "stake", "asset_value"):
                assert (item[field] is None) == (field in item["na"]), (ticker, item["id"])
