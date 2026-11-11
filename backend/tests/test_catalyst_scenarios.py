"""A readout inside the business a product already sells, priced from a named scenario.

Fifty-eight readouts on the book read as worth nothing because their patients are
already in the revenue the forecast grows from. Nothing is the wrong answer for some of
them: an outcomes trial inside an approved population changes the claim, the guideline
and the payer position, and so the rate the marketed line grows at. The analyst writes
that as a named scenario restating the two or three figures a win moves, the file ties
the scenario to the readout, and the stake is the difference between the two builds.

Nothing here estimates anything. A scenario with no rows written against it is refused
at the file, because ``assumptions.load`` falls back to base key by key and such a row
would price as a confident zero.
"""

import pytest

import catalyst_scenarios as S
import db
import forecast_view as V

_HEADER = "ticker,asset,nct_id,scenario,basis\n"

_BASE = (("therapy_mode", None, "marketed"), ("base_revenue", 1198.0, None),
         ("revenue_growth_pct", 0.10, None), ("terminal_growth_pct", 0.0, None),
         ("growth_fade_years", 5, None), ("cogs_pct", 0.25, None),
         ("sga_pct", 0.23, None), ("rd_pct", 0.20, None), ("tax_rate", 0.11, None),
         ("wacc", 0.08, None), ("pos", 1.0, None),
         ("forecast_start_year", 2026, None), ("forecast_years", 10, None))


def _db(tmp_path, *, scenario_rows=(("revenue_growth_pct", 0.30),), phase="Phase 3",
        overlap=1.0):
    """A marketed product, a readout inside the pool it already sells to, and a case."""
    path = str(tmp_path / "scenario.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'NVS', 'Novartis')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Leqvio', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Cardiovascular Diseases')")
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " region) VALUES (5, 1, 1, ?, 'US')", (phase,))
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (1, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, 1908000000, '2025-12-31')")
    for key, value, text in _BASE:
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value,"
                     " text_value, source) VALUES (1, 'US', 'base', ?, ?, ?, 'test')",
                     (key, value, text))
    # The pair the readout sits on: wholly inside the base, which is what makes the
    # layer refuse on the evidence and the scenario the only route left.
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                 " key, value, source) VALUES (1, 1, 'US', 'base',"
                 " 'base_pool_overlap_pct', ?, 'test')", (overlap,))
    for key, value in scenario_rows:
        conn.execute("INSERT INTO assumptions (asset_id, region, scenario, key, value,"
                     " source) VALUES (1, 'US', 'victorion_2p', ?, ?, 'test')",
                     (key, value))
    conn.execute("INSERT INTO trials (nct_id, sponsor_company_id, asset_id, title, phase,"
                 " overall_status, primary_completion_date) VALUES ('NCT05030428', 1, 1,"
                 " 'Study of Inclisiran to Prevent Cardiovascular Events', 'Phase 3',"
                 " 'Recruiting', date('now', '+90 days'))")
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, asset_indication_id,"
                 " catalyst_type, expected_date, title, description, source_url, status)"
                 " VALUES (10, 1, 1, 5, 'data readout', date('now', '+90 days'),"
                 " 'Phase 3, Leqvio', 'VICTORION-2-PREVENT',"
                 " 'https://clinicaltrials.gov/study/NCT05030428', 'pending')")
    conn.commit(); conn.close()
    return path


def _file(tmp_path, body, monkeypatch):
    path = tmp_path / "catalyst_scenarios.csv"
    path.write_text(_HEADER + body, encoding="utf-8")
    monkeypatch.setattr(S, "CURATED", path)
    return path


_ROW = ("NVS,Leqvio,NCT05030428,victorion_2p,"
        "\"a cardiovascular outcomes result the label does not carry today\"\n")


# --- the lever --------------------------------------------------------------

def test_a_readout_inside_the_base_is_priced_from_the_case_the_file_names(tmp_path,
                                                                         monkeypatch):
    path = _db(tmp_path)
    assert [r["reason"] for r in V.catalyst_stakes(path, "NVS")["unpriced"]] \
        == ["in_the_base"]
    _file(tmp_path, _ROW, monkeypatch)
    out = V.catalyst_stakes(path, "NVS")
    assert out["unpriced"] == []
    row = out["priced"][0]
    assert row["legs_basis"] == "scenario"
    assert row["scenario"] == "victorion_2p"


def test_the_stake_is_the_difference_between_the_two_builds_and_nothing_else(
        tmp_path, monkeypatch):
    """The whole claim of the mechanism: the engine computes both ends, so the stake
    cannot say anything the model would not."""
    path = _db(tmp_path)
    _file(tmp_path, _ROW, monkeypatch)
    row = V.catalyst_stakes(path, "NVS")["priced"][0]
    base = V.whatif(path, "NVS", 1)["base"]["npv"]
    case = V.whatif(path, "NVS", 1, scenario="victorion_2p")["base"]["npv"]
    assert case > base
    # Success is the case, failure is base, so the swing is the delta times the odds
    # still ahead of the gate. Failure leaves base, which is nil on the delta.
    assert row["rnpv_success"] == pytest.approx((case - base) * 0.906)
    assert row["rnpv_failure"] == 0.0
    assert row["swing"] == pytest.approx((case - base) * 0.906)
    assert row["scenario_npv"] == pytest.approx(case)
    assert row["base_npv"] == pytest.approx(base)


def test_the_case_is_risked_at_the_published_transitions_like_any_layer(tmp_path,
                                                                       monkeypatch):
    """A case that needs a label change is only worth its delta if the label changes, so
    it is risked exactly as an indication layer is: the study's own gate, then every
    transition between it and approval."""
    path = _db(tmp_path)
    _file(tmp_path, _ROW, monkeypatch)
    row = V.catalyst_stakes(path, "NVS")["priced"][0]
    assert row["gate"] == "p3_to_nda"
    assert row["p_gate"] == pytest.approx(0.578)            # All indications, published
    assert row["pos_success"] == pytest.approx(0.906)       # the FDA decision still ahead
    assert row["pos_now"] == pytest.approx(0.578 * 0.906)
    assert row["resolvable"] is False


def test_a_phase_2_readout_takes_the_longer_chain(tmp_path, monkeypatch):
    path = _db(tmp_path, phase="Phase 2")
    _file(tmp_path, _ROW, monkeypatch)
    row = V.catalyst_stakes(path, "NVS")["priced"][0]
    assert row["gate"] == "p2_to_p3"
    assert row["pos_success"] == pytest.approx(0.578 * 0.906)


def test_a_phase_without_a_gate_stays_refused(tmp_path, monkeypatch):
    """The odds are the published transitions between the study's own phase and
    approval, so a phase the gate table does not reach has no probability to risk the
    case at, and the book will not invent one. Two of the fifty-eight sit at Phase 4,
    which has no regulatory transition left at all."""
    path = _db(tmp_path, phase="Phase 1")
    _file(tmp_path, _ROW, monkeypatch)
    out = V.catalyst_stakes(path, "NVS")
    assert out["priced"] == []
    assert [r["reason"] for r in out["unpriced"]] == ["in_the_base"]


# --- what the file will not do ----------------------------------------------

def test_a_scenario_nobody_has_written_is_refused_rather_than_priced_at_base(
        tmp_path, monkeypatch):
    """The failure that would be invisible. ``assumptions.load`` falls back to base key
    by key, so a scenario with no rows builds the base forecast exactly, the delta is
    nought and the row would read as priced while saying nothing."""
    path = _db(tmp_path, scenario_rows=())
    _file(tmp_path, _ROW, monkeypatch)
    conn = db.get_connection(path)
    assert S.load(conn) == {}
    assert S.unresolved(conn) == [
        "NVS Leqvio: no assumption row is written in scenario 'victorion_2p'"]
    conn.close()
    assert [r["reason"] for r in V.catalyst_stakes(path, "NVS")["unpriced"]] \
        == ["in_the_base"]


def test_a_case_that_moves_nothing_is_not_a_stake(tmp_path, monkeypatch):
    """Rows written in the scenario, but restating base's own figure. The delta is nil
    and a nil stake is not a stake."""
    path = _db(tmp_path, scenario_rows=(("revenue_growth_pct", 0.10),))
    _file(tmp_path, _ROW, monkeypatch)
    assert [r["reason"] for r in V.catalyst_stakes(path, "NVS")["unpriced"]] \
        == ["in_the_base"]


def test_an_asset_the_book_does_not_hold_is_named_not_swallowed(tmp_path, monkeypatch):
    path = _db(tmp_path)
    _file(tmp_path, "NVS,Entresto,NCT05030428,victorion_2p,a case\n", monkeypatch)
    conn = db.get_connection(path)
    assert S.unresolved(conn) == ["NVS Entresto: no single asset of that name"]
    conn.close()


def test_one_case_is_worth_its_delta_once(tmp_path, monkeypatch):
    """Tezspire has two asthma readouts and Abrysvo five in RSV. Where one case covers
    several of them the earliest carries it; counting the delta on each would sell the
    same label change five times."""
    path = _db(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, asset_indication_id,"
                 " catalyst_type, expected_date, title, description, source_url, status)"
                 " VALUES (11, 1, 1, 5, 'data readout', date('now', '+300 days'),"
                 " 'Phase 3, Leqvio', 'VICTORION-2-PREVENT second date',"
                 " 'https://clinicaltrials.gov/study/NCT05030428', 'pending')")
    conn.commit(); conn.close()
    _file(tmp_path, _ROW, monkeypatch)
    out = V.catalyst_stakes(path, "NVS")
    assert [r["id"] for r in out["priced"]] == [10]
    later = out["unpriced"][0]
    assert later["id"] == 11
    assert later["reason"] == "same_gate_later"
    assert later["priced_on"] == 10
    assert "victorion_2p" in later["why"]


def test_an_indication_the_label_does_not_cover_still_asks_for_a_layer(tmp_path,
                                                                      monkeypatch):
    """The scenario is the lever for a readout inside the base, and only that. Where the
    pool is genuinely outside the business the right answer is still the layer, and a
    scenario must not be allowed to stand in for one."""
    path = _db(tmp_path, overlap=0.0)
    _file(tmp_path, _ROW, monkeypatch)
    out = V.catalyst_stakes(path, "NVS")
    assert out["priced"] == []
    assert [r["reason"] for r in out["unpriced"]] == ["needs_layer"]


# --- the file on the book ---------------------------------------------------

def test_no_row_of_the_curated_file_is_silently_ignored():
    """The guard the orphaned seed files earned. A row naming an asset the book does not
    hold, or a scenario nobody wrote, prices as a confident nothing; the file is only
    worth keeping if a row that does not land says so."""
    conn = db.get_connection()
    try:
        assert S.unresolved(conn) == []
    finally:
        conn.close()
