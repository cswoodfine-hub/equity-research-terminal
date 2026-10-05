"""Catalysts with stakes: the calendar ranked by dollars rather than by date.

The stake is the rNPV under one leg less the rNPV under the other, and rNPV is NPV times
the probability, so one build prices both and a stake can never say anything the model
would not. Stated legs (both rows on file) win; otherwise a big pharma Phase 2 or 3
asset is priced from the legs its gate derives, on the one catalyst that is that gate.
"""

import datetime as dt
import json

import pytest

import assumptions as A
import catalysts as C
import db
import forecast_view as V
import pos_granular as PG


def _seed(tmp_path):
    path = str(tmp_path / "stakes.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'VRTX', 'Vertex')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'CRSP', 'CRISPR')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Casgevy', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (2, 1, 'Unpriced', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Anemia, Sickle Cell')")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 1.8), ("cogs_per_patient", 0.75),
        ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15),
        ("wacc", 0.10), ("pos", 0.8), ("economics_share", 0.6),
        ("pos_success", 0.95), ("pos_failure", 0.40),
        ("forecast_start_year", 2026), ("forecast_years", 3))]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    rows.append({"key": "partner_ticker", "text_value": "CRSP", "source": "t"})
    for year, patients in ((2026, 100), (2027, 200), (2028, 300)):
        rows.append({"key": "new_patients", "indication_id": 1, "year": year,
                     "value": patients, "source": "t"})
    A.save(conn, 1, rows)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (1, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, 258000000, '2025-12-31')")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES"
                 " (10, 1, 1, 'data readout', date('now', '+90 days'),"
                 " 'Phase 3 long-term follow-up', 'NCT1', 'pending')")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, status) VALUES"
                 " (11, 1, 2, 'data readout', date('now', '+30 days'),"
                 " 'A readout on an unpriced asset', 'NCT2', 'pending')")
    conn.commit(); conn.close()
    return path


# --- the ranking ------------------------------------------------------------

def test_a_priced_catalyst_carries_its_swing_and_the_unpriced_says_what_would(tmp_path):
    path = _seed(tmp_path)
    out = V.catalyst_stakes(path, "VRTX")
    assert [r["id"] for r in out["priced"]] == [10]
    row = out["priced"][0]
    # the stake is the arithmetic of the two legs, at the company's share
    up = V.whatif(path, "VRTX", 1, pos=0.95)["varied"]["rnpv"]
    down = V.whatif(path, "VRTX", 1, pos=0.40)["varied"]["rnpv"]
    assert row["swing"] == pytest.approx(up - down)
    assert row["share"] == 0.6
    assert row["share_swing"] == pytest.approx((up - down) * 0.6)
    assert row["per_share"] == pytest.approx((up - down) * 0.6 * 1e6 / 258e6)
    unpriced = out["unpriced"]
    assert [r["id"] for r in unpriced] == [11]
    assert set(unpriced[0]["missing"]) == {"pos_success", "pos_failure"}


def test_the_partner_prices_the_same_event_at_its_share(tmp_path):
    path = _seed(tmp_path)
    out = V.catalyst_stakes(path, "CRSP")
    assert [r["id"] for r in out["priced"]] == [10]
    assert out["priced"][0]["share"] == pytest.approx(0.4)
    # the unpriced asset belongs to Vertex alone and has no partner row
    assert out["unpriced"] == []


def test_priced_rank_by_size_not_date(tmp_path):
    """A second priced catalyst on a nearer date but a smaller swing sorts second."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (3, 1, 'Smaller', 1)")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 0.2), ("cogs_per_patient", 0.05),
        ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15),
        ("wacc", 0.10), ("pos", 0.5), ("pos_success", 0.6), ("pos_failure", 0.4),
        ("forecast_start_year", 2026), ("forecast_years", 3))]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    rows.append({"key": "new_patients", "indication_id": 1, "year": 2026,
                 "value": 50, "source": "t"})
    A.save(conn, 3, rows)
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, status) VALUES (12, 1, 3, 'data readout',"
                 " date('now', '+10 days'), 'Sooner but smaller', 'pending')")
    conn.commit(); conn.close()
    out = V.catalyst_stakes(path, "VRTX")
    assert [r["id"] for r in out["priced"]] == [10, 12]     # size first, not date


# --- resolve ----------------------------------------------------------------

def test_resolve_steps_the_pos_and_keeps_both_sides_of_history(tmp_path):
    path = _seed(tmp_path)
    before = V.asset_forecast(path, "VRTX", 1)["result"]["rnpv"]
    out = V.resolve_catalyst(path, "VRTX", 10, "missed")
    assert out["pos_applied"] == 0.40
    after = V.asset_forecast(path, "VRTX", 1)["result"]
    assert after["pos"] == 0.40
    assert after["pos_basis"] == "stated"
    assert after["rnpv"] == pytest.approx(before * 0.40 / 0.80)
    conn = db.get_connection(path)
    # the catalyst left the calendar with the outcome on its row
    assert conn.execute("SELECT status FROM catalysts WHERE id = 10"
                        ).fetchone()[0] == "missed"
    assert "resolved missed" in conn.execute(
        "SELECT description FROM catalysts WHERE id = 10").fetchone()[0]
    assert C.list_catalysts(path, within_days=365, ticker="VRTX") == [
        r for r in C.list_catalysts(path, within_days=365, ticker="VRTX")
        if r["id"] != 10]
    # both sides of the event are on file: the pre snapshot and the post one
    snaps = [json.loads(r[0]) for r in conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'forecast'"
        " AND entity_key = '1' ORDER BY id")]
    conn.close()
    assert len(snaps) >= 2
    assert snaps[-2]["pos"] == pytest.approx(0.80)      # pre-event
    assert snaps[-1]["pos"] == pytest.approx(0.40)      # post-event


def test_resolve_refuses_what_it_should(tmp_path):
    path = _seed(tmp_path)
    with pytest.raises(ValueError):                      # not an outcome
        V.resolve_catalyst(path, "VRTX", 10, "maybe")
    with pytest.raises(ValueError):                      # no priced leg on file
        V.resolve_catalyst(path, "VRTX", 11, "met")
    assert V.resolve_catalyst(path, "LLY", 10, "met") is None    # unknown ticker
    V.resolve_catalyst(path, "VRTX", 10, "met")
    with pytest.raises(ValueError):                      # already resolved
        V.resolve_catalyst(path, "VRTX", 10, "missed")


def test_the_partner_can_resolve_too(tmp_path):
    """CRISPR watches the same readout; either side of the economics may record it."""
    path = _seed(tmp_path)
    out = V.resolve_catalyst(path, "CRSP", 10, "met")
    assert out["pos_applied"] == 0.95


def test_a_resolved_catalyst_leaves_list_catalysts(tmp_path):
    path = _seed(tmp_path)
    assert {r["id"] for r in C.list_catalysts(path, 365, "VRTX")} == {10, 11}
    V.resolve_catalyst(path, "VRTX", 10, "met")
    assert {r["id"] for r in C.list_catalysts(path, 365, "VRTX")} == {11}


def test_list_catalysts_now_carries_the_asset_handle(tmp_path):
    path = _seed(tmp_path)
    row = C.list_catalysts(path, 365, "VRTX")[0]
    assert "asset_id" in row and "status" in row



# --- stated legs stay on the event they are tied to ---------------------------

def _casgevy(tmp_path):
    """Casgevy's book: the stated legs cite the long-term follow-up NCT05356195, which
    is catalyst 10. Two more readouts (the sickle cell studies NCT05329649 and
    NCT05477563) reach the asset only through their studies: the catalysts carry no
    asset id."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("UPDATE assumptions SET source = 'durability (NCT05356195)'"
                 " WHERE key IN ('pos_success', 'pos_failure')")
    for nct in ("NCT05356195", "NCT05329649", "NCT05477563"):
        conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
                     " overall_status, primary_completion_date) VALUES (?, 1, 1,"
                     " 'Phase 3', 'Recruiting', date('now', '+200 days'))", (nct,))
    conn.execute("UPDATE catalysts SET source_url ="
                 " 'https://clinicaltrials.gov/study/NCT05356195' WHERE id = 10")
    for cid, nct, days in ((217, "NCT05329649", 60), (219, "NCT05477563", 70)):
        conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                     " expected_date, title, description, is_curated, source_url, status)"
                     " VALUES (?, 1, NULL, 'data readout', date('now', ?), 'Phase 3,"
                     " Casgevy', ?, 0, ?, 'pending')",
                     (cid, f"+{days} days", nct, f"https://clinicaltrials.gov/study/{nct}"))
    conn.commit(); conn.close()
    return path


def test_stated_legs_price_once_on_the_study_they_cite(tmp_path):
    path = _casgevy(tmp_path)
    for ticker, share in (("VRTX", 0.6), ("CRSP", 0.4)):
        out = V.catalyst_stakes(path, ticker)
        assert [r["id"] for r in out["priced"]] == [10], ticker
        assert out["priced"][0]["share"] == pytest.approx(share)
        got = _by_id(out)
        for cid in (217, 219):
            assert got[cid]["priced"] is False
            assert got[cid]["reason"] == "stated_elsewhere", ticker
            assert got[cid]["why"] == (
                "The stated legs on file are tied to catalyst 10 (NCT05356195), and this "
                "event reaches the asset only through its study, so it is not priced "
                "against them.")
            assert "own_asset_id" not in got[cid] and "owner_company_id" not in got[cid]
            _house_style(got[cid]["why"])
    assert set(V.STAKE_REASONS) >= {"stated_elsewhere"}


def test_a_stated_resolve_is_refused_on_a_study_the_legs_do_not_cite(tmp_path):
    path = _casgevy(tmp_path)
    for cid in (217, 219):
        with pytest.raises(ValueError, match="only through its study"):
            V.resolve_catalyst(path, "VRTX", cid, "missed")
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM catalysts WHERE status != 'pending'"
                        ).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM assumptions WHERE key = 'pos'"
                        " AND source LIKE 'catalyst %'").fetchone()[0] == 0
    conn.close()
    assert V.resolve_catalyst(path, "CRSP", 10, "missed")["pos_applied"] == 0.40


def test_stated_legs_tied_to_two_events_are_priced_on_the_first_once(tmp_path):
    """With no study cited, the analyst's own asset link ties the legs; two such events
    are one risk, priced on the earlier."""
    path = _seed(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, status) VALUES (13, 1, 1, 'PDUFA',"
                 " date('now', '+200 days'), 'Casgevy decision', 'pending')")
    conn.commit(); conn.close()
    got = _by_id(V.catalyst_stakes(path, "VRTX"))
    assert got[10]["priced"] and not got[13]["priced"]
    assert got[13]["reason"] == "stated_elsewhere"
    assert got[13]["why"].startswith("The stated legs on file are priced once, on "
                                     "catalyst 10 (")
    with pytest.raises(ValueError, match="priced once"):
        V.resolve_catalyst(path, "VRTX", 13, "met")


# --- derived legs ------------------------------------------------------------
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
MYELOMA = ("D009101", "Multiple Myeloma")
FOLLICULAR = ("D008224", "Lymphoma, Follicular")


def _day(days):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def _house_style(text):
    assert "—" not in text and "–" not in text, text
    assert not any(word in text.lower() for word in BANNED), text


@pytest.fixture
def big(monkeypatch):
    """Every owner reads as big pharma, which is what puts an asset on the gate."""
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)


def _pipeline(tmp_path, phase="Phase 3", extra=(), share=None, partner=None):
    """An antibody in Phase 3 for multiple myeloma at a big pharma owner, with a forecast
    the engine can build and no probability of its own, so its placement governs."""
    path = str(tmp_path / "gate.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'ABBV', 'AbbVie', 'USD')")
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (2, 'GMAB', 'Genmab', 'USD')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (7, 1, 'etentamig', 0)")
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES (3, ?, ?)", MYELOMA[::-1])
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES (4, ?, ?)",
                 FOLLICULAR[::-1])
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " is_lead, region) VALUES (30, 7, 3, ?, 1, 'US')", (phase,))
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " is_lead, region) VALUES (31, 7, 4, 'Phase 2', 0, 'US')")
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 0.3), ("cogs_per_patient", 0.05),
        ("sga_pct", 0.2), ("rd_pct", 0.1), ("tax_rate", 0.15), ("wacc", 0.09),
        ("forecast_start_year", 2028), ("forecast_years", 6), *extra)]
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    if share is not None:
        rows.append({"key": "economics_share", "value": share, "source": "t"})
    if partner:
        rows.append({"key": "partner_ticker", "text_value": partner, "source": "t"})
    for year, patients in ((2028, 400), (2029, 900), (2030, 1500)):
        rows.append({"key": "new_patients", "indication_id": 3, "year": year,
                     "value": patients, "source": "t"})
    A.save(conn, 7, rows)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (1, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, 1770000000, '2025-12-31')")
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (2, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, 64000000, '2025-12-31')")
    conn.commit()
    return path, conn


def _trial(conn, nct, phase, completion, term, status="Recruiting", enrollment=500,
           asset_id=7):
    conn.execute(
        "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase, overall_status,"
        " primary_completion_date, enrollment, title, conditions, mesh_terms)"
        " VALUES (?, ?, 1, ?, ?, ?, ?, 'A study', ?, ?)",
        (nct, asset_id, phase, status, completion, enrollment, json.dumps([term[1]]),
         json.dumps({"meshes": [{"id": term[0], "term": term[1]}], "ancestors": []})))


def _cat(conn, cid, kind, days, nct=None, asset_id=7, indication=None, title="An event",
         description=None):
    url = f"https://clinicaltrials.gov/study/{nct}" if nct else "https://sec.gov/x"
    conn.execute(
        "INSERT INTO catalysts (id, company_id, asset_id, asset_indication_id,"
        " catalyst_type, expected_date, title, description, is_curated, source_url,"
        " status) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 0, ?, 'pending')",
        (cid, asset_id, indication, kind, _day(days), title, description or nct, url))


def _phase_3_book(tmp_path, **kw):
    path, conn = _pipeline(tmp_path, **kw)
    _trial(conn, "NCT00000001", "Phase 3", _day(200), MYELOMA)
    _trial(conn, "NCT00000002", "Phase 3", _day(100), FOLLICULAR)
    _trial(conn, "NCT00000003", "Phase 2", _day(60), MYELOMA, enrollment=200)
    _trial(conn, "NCT00000004", "Phase 3", _day(400), MYELOMA, enrollment=900)
    _cat(conn, 21, "data readout", 200, "NCT00000001")          # the gate
    _cat(conn, 22, "data readout", 100, "NCT00000002")          # another disease
    _cat(conn, 23, "data readout", 60, "NCT00000003")           # a Phase 2
    _cat(conn, 24, "data readout", 400, "NCT00000004")          # the same gate, later
    # A filing for the second indication: filed_for leaves the asset at its Phase 3
    # gate (a filing for the lead would put it at the FDA decision), and the date is not
    # the gate the model prices.
    _cat(conn, 25, "PDUFA", 300, indication=31)
    _cat(conn, 26, "AdCom", 250)                                # informs, never the gate
    _cat(conn, 27, "data readout", 150, description="no study named")
    _cat(conn, 28, "conference", 90, "NCT00000001")
    conn.commit()
    conn.close()
    return path


def _by_id(out):
    return {r["id"]: r for r in out["priced"] + out["unpriced"]}


def test_a_derived_gate_prices_its_one_catalyst_from_npv_and_the_success_leg(tmp_path, big):
    path = _phase_3_book(tmp_path)
    out = V.catalyst_stakes(path, "ABBV")
    built = V.asset_forecast(path, "ABBV", 7)["result"]
    legs = PG.legs_for_asset(db.get_connection(path), 7, big=True)
    assert [r["id"] for r in out["priced"]] == [21], "exactly one priced per asset and gate"
    row = out["priced"][0]
    assert row["legs_basis"] == "derived" and row["gate"] == "p3_to_nda"
    assert row["gate_label"] == "Phase 3 readout" and row["trial"] == "NCT00000001"
    assert row["gate_trial"] == "NCT00000001"
    assert row["pos_failure"] == 0.0 and row["pos_success"] == legs["pos_success"]
    assert row["pos_now"] == built["pos"]
    assert row["p_gate"] * row["pos_success"] == pytest.approx(row["pos_now"], abs=1e-12)
    assert row["swing"] == pytest.approx(built["npv"] * legs["pos_success"], rel=1e-12)
    assert row["rnpv_failure"] == 0.0 and row["share"] == 1.0
    assert row["share_swing"] == pytest.approx(row["swing"])
    assert row["per_share"] == pytest.approx(row["swing"] * 1e6 / 1.77e9)
    assert row["resolvable"] is True and row["resolve_note"] is None
    assert row["evidence"] == {"p_gate": "published", "success": "published",
                               "failure": "convention"}
    # the other Phase 3 still open holds the asset after a miss
    assert row["held"]["ncts"] == ["NCT00000004"]
    _house_style(row["basis"])


def test_every_other_catalyst_on_the_asset_says_why_it_is_not_priced(tmp_path, big):
    path = _phase_3_book(tmp_path)
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert {i: got[i]["reason"] for i in (22, 23, 24, 25, 26, 27, 28)} == {
        22: "other_indication", 23: "not_gate_phase", 24: "same_gate_later",
        25: "regulatory_not_gate", 26: "regulatory_not_gate", 27: "no_trial_link",
        28: "not_a_gate"}
    for i in (22, 23, 24, 25, 26, 27, 28):
        assert got[i]["priced"] is False
        assert got[i]["missing"] == ["pos_success", "pos_failure"]
        assert set(V.STAKE_REASONS) >= {got[i]["reason"]}
        _house_style(got[i]["why"])
    assert "Lymphoma, Follicular" in got[22]["why"]
    assert "phase 3 readout" in got[25]["why"]


def test_a_phase_2_gate_prices_its_readout_and_does_not_resolve_by_hand(tmp_path, big):
    path, conn = _pipeline(tmp_path, phase="Phase 2")
    _trial(conn, "NCT00000005", "Phase 2", _day(120), MYELOMA, enrollment=200)
    _trial(conn, "NCT00000006", "Phase 3", _day(300), MYELOMA)
    _cat(conn, 31, "data readout", 120, "NCT00000005")
    _cat(conn, 32, "data readout", 300, "NCT00000006")
    conn.commit(); conn.close()
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[31]["priced"] and got[31]["gate"] == "p2_to_p3"
    assert got[31]["resolvable"] is False
    assert got[31]["resolve_note"] == ("A Phase 2 result moves the model when its Phase 3 "
                                       "starts or the programme is retired.")
    assert got[31]["held"] is None
    assert got[32]["reason"] == "phase_ahead_of_book"
    with pytest.raises(ValueError, match="Phase 2 result"):
        V.resolve_catalyst(path, "ABBV", 31, "met")


def test_at_the_fda_gate_the_filing_is_priced_and_a_readout_is_past_it(tmp_path, big):
    path, conn = _pipeline(tmp_path)
    _trial(conn, "NCT00000001", "Phase 3", _day(-200), MYELOMA, status="Completed")
    _trial(conn, "NCT00000007", "Phase 3", _day(90), MYELOMA)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('000-1', 1, 'etentamig', 3, 'positive', ?)",
                 (_day(-30),))
    _cat(conn, 41, "data readout", 90, "NCT00000007")
    _cat(conn, 42, "PDUFA", 200, indication=30, title="etentamig PDUFA, Multiple myeloma")
    _cat(conn, 43, "PDUFA", 250, indication=31, title="etentamig PDUFA, lymphoma")
    _cat(conn, 44, "PDUFA", 260, title="etentamig PDUFA")
    conn.commit(); conn.close()
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[42]["priced"] and got[42]["gate"] == "nda_to_approval"
    assert got[42]["pos_success"] == 1.0 and got[42]["resolvable"] is False
    assert got[42]["resolve_note"] == "An FDA decision resolves when openFDA lists the approval."
    assert got[41]["reason"] == "past_gate"
    assert got[43]["reason"] == "other_indication" and "Lymphoma" in got[43]["why"]
    assert got[44]["reason"] == "other_indication"
    with pytest.raises(ValueError, match="openFDA"):
        V.resolve_catalyst(path, "ABBV", 42, "met")


def test_a_stated_pos_at_its_success_leg_is_read_at_the_fda_decision(tmp_path, big):
    path, conn = _pipeline(tmp_path, extra=(("pos", 0.95),))
    _trial(conn, "NCT00000001", "Phase 3", _day(200), MYELOMA)
    _cat(conn, 51, "data readout", 200, "NCT00000001")
    conn.commit(); conn.close()
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[51]["reason"] == "past_gate" and "implies a filing" in got[51]["why"]


def test_nil_and_outside_the_gate_are_named(tmp_path, big):
    path, conn = _pipeline(tmp_path, extra=(("pos", 0.0),))
    _trial(conn, "NCT00000001", "Phase 3", _day(200), MYELOMA)
    _cat(conn, 61, "data readout", 200, "NCT00000001")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (8, 1, 'oldmab', 1)")
    _cat(conn, 62, "data readout", 210, asset_id=8)
    conn.commit(); conn.close()
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[61]["reason"] == "nil"
    assert got[62]["reason"] == "no_gate"


def test_a_lone_stated_leg_is_named_and_the_derived_legs_price(tmp_path, big):
    path = _phase_3_book(tmp_path, extra=(("pos_success", 0.99),))
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[21]["legs_basis"] == "derived" and got[21]["pos_success"] != 0.99
    assert got[21]["ignored"].startswith("pos_success is on file without pos_failure")
    _house_style(got[21]["ignored"])


def test_the_partner_prices_the_derived_gate_at_its_share(tmp_path, big):
    path = _phase_3_book(tmp_path, share=0.7, partner="GMAB")
    mine = V.catalyst_stakes(path, "ABBV")["priced"][0]
    theirs = V.catalyst_stakes(path, "GMAB")["priced"][0]
    assert mine["id"] == theirs["id"] == 21
    assert mine["share"] == 0.7 and theirs["share"] == pytest.approx(0.3)
    assert theirs["per_share"] == pytest.approx(mine["swing"] * 0.3 * 1e6 / 64e6)


def test_the_stated_route_is_linear_and_matches_the_two_whatif_runs(tmp_path):
    path = _seed(tmp_path)
    row = V.catalyst_stakes(path, "VRTX")["priced"][0]
    up = V.whatif(path, "VRTX", 1, pos=0.95)["varied"]["rnpv"]
    down = V.whatif(path, "VRTX", 1, pos=0.40)["varied"]["rnpv"]
    assert row["legs_basis"] == "stated" and row["resolvable"] is True
    assert row["swing"] == pytest.approx(up - down, rel=1e-6)
    assert row["rnpv_success"] == pytest.approx(up, rel=1e-6)


# --- resolving a derived gate ------------------------------------------------

def _rows(path, sql, *args):
    conn = db.get_connection(path)
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def test_a_met_derived_gate_lands_on_its_success_leg_and_writes_no_assumption(tmp_path, big):
    path = _phase_3_book(tmp_path)
    priced = V.catalyst_stakes(path, "ABBV")["priced"][0]
    rows_before = _rows(path, "SELECT * FROM assumptions ORDER BY id")
    out = V.resolve_catalyst(path, "ABBV", 21, "met")
    after = V.asset_forecast(path, "ABBV", 7)["result"]
    assert out["route"] == "gate evidence" and out["stated_pos_governs"] is False
    assert out["pos_applied"] == pytest.approx(priced["pos_success"], abs=1e-4)
    assert after["pos"] == priced["pos_success"] and out["stage"] == "positive"
    assert out["leg"] == priced["pos_success"] and out["held"] is None
    assert _rows(path, "SELECT * FROM assumptions ORDER BY id") == rows_before
    cat = _rows(path, "SELECT status, description FROM catalysts WHERE id = 21")[0]
    assert cat["status"] == "met"
    assert cat["description"].endswith(" | resolved met, recorded as gate evidence")
    snaps = [json.loads(r["payload"]) for r in _rows(
        path, "SELECT payload FROM snapshots WHERE source = 'forecast'"
        " AND entity_key = '7' ORDER BY id")]
    assert [s["pos"] for s in snaps[-2:]] == [priced["pos_now"], priced["pos_success"]]
    assert 21 not in {r["id"] for r in C.list_catalysts(path, 730, "ABBV")}
    # the gate has moved: a readout is now past it
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[24]["reason"] == "past_gate"


def test_a_missed_derived_gate_is_held_while_another_phase_3_is_open(tmp_path, big):
    path = _phase_3_book(tmp_path)
    priced = V.catalyst_stakes(path, "ABBV")["priced"][0]
    out = V.resolve_catalyst(path, "ABBV", 21, "missed")
    assert out["stage"] == "mixed"
    assert out["pos_applied"] == priced["held"]["pos"] == out["held"]["pos"]
    assert out["leg"] == 0.0


def test_a_missed_derived_gate_with_nothing_else_open_is_nil(tmp_path, big):
    path, conn = _pipeline(tmp_path)
    _trial(conn, "NCT00000001", "Phase 3", _day(200), MYELOMA)
    _cat(conn, 21, "data readout", 200, "NCT00000001")
    conn.commit(); conn.close()
    out = V.resolve_catalyst(path, "ABBV", 21, "missed")
    assert out["pos_applied"] == 0.0 and out["stage"] == "negative"


def test_resolve_refuses_what_the_stakes_do_not_price(tmp_path, big):
    path = _phase_3_book(tmp_path)
    for cid in (22, 24, 25, 26):
        with pytest.raises(ValueError):
            V.resolve_catalyst(path, "ABBV", cid, "met")
    assert _rows(path, "SELECT COUNT(*) AS n FROM catalysts WHERE status != 'pending'"
                 )[0]["n"] == 0


def test_a_stated_pos_still_governs_after_a_derived_resolve(tmp_path, big):
    path, conn = _pipeline(tmp_path, extra=(("pos", 0.3),))
    _trial(conn, "NCT00000001", "Phase 3", _day(200), MYELOMA)
    _cat(conn, 21, "data readout", 200, "NCT00000001")
    conn.commit(); conn.close()
    out = V.resolve_catalyst(path, "ABBV", 21, "met")
    assert out["stated_pos_governs"] is True
    assert out["pos_applied"] == 0.3 == out["pos_before"]
    assert out["stage"] == "positive"


def test_a_readout_belongs_to_the_asset_its_study_is_mapped_to(tmp_path, big):
    """A derived readout written before its study was mapped carries no asset id, and one
    written before a remap carries the old one. The study's mapping is the authority, for
    the price and for the evidence a resolve records."""
    path, conn = _pipeline(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (8, 1, 'oldmab', 1)")
    _trial(conn, "NCT00000001", "Phase 3", _day(200), MYELOMA)
    _trial(conn, "NCT00000004", "Phase 3", _day(400), MYELOMA)
    _cat(conn, 21, "data readout", 200, "NCT00000001", asset_id=None)
    _cat(conn, 24, "data readout", 400, "NCT00000004", asset_id=8)
    conn.commit(); conn.close()
    got = _by_id(V.catalyst_stakes(path, "ABBV"))
    assert got[21]["priced"] and got[21]["asset_id"] == 7
    assert got[24]["asset_id"] == 7 and got[24]["reason"] == "same_gate_later"
    out = V.resolve_catalyst(path, "ABBV", 21, "met")
    assert out["stage"] == "positive"


def test_a_priced_readout_other_than_the_gate_study_says_why(tmp_path, big):
    """The gate study passed its completion date with no readout on file, so its catalyst
    is gone from the calendar; the next readout at the gate is priced and says so."""
    path, conn = _pipeline(tmp_path)
    _trial(conn, "NCT00000001", "Phase 3", _day(-20), MYELOMA, enrollment=900,
           status="Active not recruiting")
    _trial(conn, "NCT00000004", "Phase 3", _day(400), MYELOMA)
    _cat(conn, 24, "data readout", 400, "NCT00000004")
    conn.commit(); conn.close()
    row = V.catalyst_stakes(path, "ABBV")["priced"][0]
    assert row["trial"] == "NCT00000004" and row["gate_trial"] == "NCT00000001"
    assert row["gate_note"].startswith("The gate study NCT00000001 passed its completion")
    assert row["held"] is None, "a miss on the last open study leaves nothing to hold"
    _house_style(row["gate_note"])
