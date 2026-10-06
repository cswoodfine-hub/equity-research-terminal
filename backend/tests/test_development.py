"""The cost to a pipeline asset's next gate, beside what passing it is worth.

A view beside the valuation: every test here is about what the cost reads and how the
gate nets it, and the last ones prove nothing on the value path can reach it."""

import ast
import datetime as dt
import json
import math
from pathlib import Path

import pytest

import assumptions as A
import db
import development as D
import engines
import forecast
import forecast_view as V
import pos_granular as PG

TODAY = dt.date(2026, 10, 6)
MYELOMA = ("D009101", "Multiple Myeloma")
AMYLOID = ("D000686", "Amyloidosis")
SHARES = 1_000_000_000
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


@pytest.fixture
def big(monkeypatch):
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)
    monkeypatch.setattr(engines, "assign", lambda *a, **k: engines.PHARMA)


def _book(tmp_path, *, phase="Phase 3", currency="USD", name="etentamig", share=None):
    """A big pharma antibody in multiple myeloma, buildable, with its company's shares."""
    path = str(tmp_path / "dev.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'ABBV', 'AbbVie', ?), (2, 'OTHR', 'Other', 'USD')", (currency,))
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (7, 1, ?, 0)", (name,))
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES (3, ?, ?), (4, ?, ?)",
                 (MYELOMA[1], MYELOMA[0], AMYLOID[1], AMYLOID[0]))
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase,"
                 " is_lead, region) VALUES (30, 7, 3, ?, 1, 'US')", (phase,))
    rows = [{"key": k, "value": v, "source": "t"} for k, v in (
        ("net_price_per_patient", 0.3), ("cogs_per_patient", 0.05), ("sga_pct", 0.2),
        ("rd_pct", 0.1), ("tax_rate", 0.15), ("wacc", 0.09), ("forecast_years", 6),
        ("forecast_start_year", 2030))]
    if share is not None:
        rows.append({"key": "economics_share", "value": share, "source": "t"})
    rows.append({"key": "therapy_mode", "text_value": "one_time", "source": "t"})
    for year, patients in ((2030, 400), (2031, 900), (2032, 1500)):
        rows.append({"key": "new_patients", "indication_id": 3, "year": year,
                     "value": patients, "source": "t"})
    A.save(conn, 7, rows)
    conn.execute("INSERT INTO financials (company_id, metric, period_type, fiscal_year,"
                 " value, period_end) VALUES (1, 'WeightedAverageDilutedShares', 'FY',"
                 " 2025, ?, '2025-12-31')", (SHARES,))
    if currency != "USD":
        conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of) VALUES (?, 'USD',"
                     " 0.15, '2026-10-02')", (currency,))
    conn.commit()
    return path, conn


def _trial(conn, nct, asset_id, *, phase="Phase 3", start="2025-10-06",
           pcd="2030-03-31", enrollment=500, disease=MYELOMA, status="Recruiting",
           title=None, table="trials"):
    conditions = json.dumps([disease[1]]) if disease else json.dumps(["Something"])
    browse = (json.dumps({"meshes": [{"id": disease[0], "term": disease[1]}],
                          "ancestors": []}) if disease else None)
    if table == "trials":
        conn.execute(
            "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase, overall_status,"
            " start_date, primary_completion_date, primary_completion_type, enrollment,"
            " title, conditions, mesh_terms, fetched_at) VALUES (?, ?, 1, ?, ?, ?, ?,"
            " 'estimated', ?, ?, ?, ?, datetime('now'))",
            (nct, asset_id, phase, status, start, pcd, enrollment, title or f"A study {nct}",
             conditions, browse))
    else:
        conn.execute(
            "INSERT INTO completed_trials (nct_id, asset_id, phase, conditions, enrollment,"
            " mesh_terms, completion_date) VALUES (?, ?, ?, ?, ?, ?, '2024-01-01')",
            (nct, asset_id, phase, conditions, enrollment, browse))
    conn.commit()


def _share_ahead(start, end, today=TODAY):
    return (end - today).days / (end - start).days


# --- the pure pieces ------------------------------------------------------------------

def test_an_even_spend_discounts_to_its_closed_form():
    anchor = dt.date(2025, 12, 31)
    start, end = dt.date(2026, 10, 6), dt.date(2028, 10, 6)
    got = D.pv_even(100.0, start, end, 0.09, anchor)
    months = 24
    step = (end - start).days / months
    numeric = sum(100.0 / months * 1.09 ** -(((start - anchor).days + step * (i + 0.5))
                                             / D.DAYS_A_YEAR) for i in range(months))
    assert got == pytest.approx(numeric, rel=1e-4)
    assert D.pv_even(100.0, start, end, 0.0, anchor) == pytest.approx(100.0)
    assert D.pv_even(50.0, start, start, 0.09, anchor) == pytest.approx(
        50.0 * 1.09 ** -((start - anchor).days / D.DAYS_A_YEAR))


def test_a_year_of_spend_and_the_money_words():
    start, end = dt.date(2026, 10, 6), dt.date(2028, 10, 5)
    assert D.within(100.0, start, end, start, start + dt.timedelta(days=365)) == \
        pytest.approx(100.0 * 365 / (end - start).days)
    assert D.within(100.0, start, end, dt.date(2030, 1, 1), dt.date(2031, 1, 1)) == 0.0
    assert D._mm(2664.0, "DKK") == "DKK 2.7bn" and D._mm(155.2, "USD") == "$155mm"
    assert D._mm(1500.0, "EUR") == "\u20ac1.5bn"


def test_a_study_costs_its_enrolment_at_the_rate_for_the_share_still_ahead():
    rate = {"value": 93145.0}
    start, end = dt.date(2025, 10, 6), dt.date(2030, 3, 31)
    got = D.study_cost({"nct_id": "N1", "phase": "Phase 3", "enrollment": 500,
                        "start_date": start.isoformat(),
                        "primary_completion_date": end.isoformat()}, rate, TODAY)
    assert got["full_usd_mm"] == pytest.approx(500 * 93145 / 1e6)
    assert got["share_ahead"] == pytest.approx(_share_ahead(start, end))
    assert got["ahead_usd_mm"] == pytest.approx(500 * 93145 / 1e6 * _share_ahead(start, end))
    assert got["spend_from"] == TODAY.isoformat() and got["spend_to"] == end.isoformat()
    assert D.evidence.weakest(got["grades"].values()) == "convention"
    sunk = D.study_cost({"nct_id": "N2", "enrollment": 500, "start_date": "2020-01-01",
                         "primary_completion_date": "2026-01-01"}, rate, TODAY)
    assert sunk["share_ahead"] == 0.0 and sunk["ahead_usd_mm"] == 0.0
    assert "sunk" in sunk["basis"]
    undated = D.study_cost({"nct_id": "N3", "enrollment": 100, "start_date": None,
                            "primary_completion_date": "2028-01-01"}, rate, TODAY)
    assert undated["share_ahead"] == 1.0
    later = D.study_cost({"nct_id": "N4", "enrollment": 100, "start_date": "2027-01-01",
                          "primary_completion_date": "2028-01-01"}, rate, TODAY)
    assert later["share_ahead"] == 1.0 and later["spend_from"] == "2027-01-01"


def test_a_three_gate_ladder_by_hand():
    """p 50%, 60%, 90%; costs 10, 50, 2; success leg 540, so 1,000 on approval."""
    stages = [{"gate": g, "label": g, "date": None, "p": p}
              for g, p in (("p2_to_p3", 0.5), ("p3_to_nda", 0.6), ("nda_to_approval", 0.9))]
    got = D.ladder(stages, 540.0, [10.0, 50.0, 2.0])
    rows = got["rows"]
    assert got["value_on_approval"] == pytest.approx(1000.0)
    assert [r["value_if_passed"] for r in rows] == pytest.approx([488.8, 898.0, 1000.0])
    assert rows[0]["net"] == pytest.approx(0.5 * 488.8 - 10)
    assert rows[0]["breakeven_p"] == pytest.approx(10 / 488.8)
    assert rows[1]["breakeven_p"] == pytest.approx(50 / 898.0)
    assert got["risked_cost"] == pytest.approx(10 + 0.5 * (50 + 0.6 * 2))
    assert got["value_today"] == pytest.approx(0.5 * 540 - got["risked_cost"])
    assert all(r["funds"] and not r["floored"] for r in rows)
    # A Phase 3 no sponsor would fund on these numbers: floored at nil.
    bad = D.ladder(stages, 540.0, [10.0, 700.0, 2.0])
    assert bad["rows"][0]["value_if_passed"] == pytest.approx(0.6 * 898 - 700)
    assert not bad["rows"][1]["funds"] and not bad["rows"][0]["funds"]
    assert bad["rows"][0]["value_if_passed_floored"] == 0.0 and bad["rows"][0]["floored"]


# --- one asset on a database ---------------------------------------------------------

def test_a_phase_3_asset_counts_the_modelled_study_and_reports_the_other(tmp_path, big):
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7, enrollment=500)
    _trial(conn, "NCT00000002", 7, enrollment=300, disease=AMYLOID, pcd="2029-06-30")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["ok"] is True and got["currency"] == "USD"
    gate = got["gate"]
    assert gate["label"] == "Phase 3 readout" and gate["trial"]["nct_id"] == "NCT00000001"
    share = _share_ahead(dt.date(2025, 10, 6), dt.date(2030, 3, 31))
    assert gate["cost_usd_mm"] == pytest.approx(500 * 93145 / 1e6 * share)
    assert gate["full_usd_mm"] == pytest.approx(500 * 93145 / 1e6)
    (first, review) = got["stages"]
    assert [s["nct_id"] for s in first["studies"]] == ["NCT00000001"]
    assert first["grade"] == "convention" and review["grade"] == "analogue"
    assert review["cost_usd_mm"] == 2.6
    outside = got["outside"]["studies"]
    assert [s["nct_id"] for s in outside] == ["NCT00000002"]
    assert outside[0]["fit"] == "other" and outside[0]["ahead_usd_mm"] > 0
    assert got["outside"]["cost_usd_mm"] == pytest.approx(outside[0]["ahead_usd_mm"])
    # Discounted from today to the primary completion, at the asset's WACC, after tax.
    anchor = dt.date(TODAY.year - 1, 12, 31)
    expect = D.pv_even(gate["cost_usd_mm"], TODAY, dt.date(2030, 3, 31), 0.09, anchor) * 0.85
    assert gate["cost"] == pytest.approx(expect)
    assert got["after_tax"] is True and got["tax_rate"] == 0.15
    # The headline is the user's wording: p_gate x the success leg less the cost.
    built = forecast.build(A.load(db.get_connection(path), 7))
    assert gate["success_leg"] == pytest.approx(built["npv"] * gate["pos_success"])
    assert gate["ev"] == pytest.approx(gate["p"] * gate["success_leg"])
    assert gate["ev"] == pytest.approx(built["rnpv"])
    assert gate["net"] == pytest.approx(built["rnpv"] - gate["cost"])
    assert gate["breakeven_p"] == pytest.approx(gate["cost"] / gate["success_leg"])
    assert gate["net_per_share"] == pytest.approx(gate["net"] * 1e6 / SHARES)
    ladder = got["ladder"]
    assert ladder["label"] == "after later trial costs"
    assert ladder["value_today"] == pytest.approx(ladder["rnpv"] - ladder["risked_cost"],
                                                  abs=1e-9)
    assert gate["high"]["cost"] == pytest.approx(
        gate["cost"] * D.dimasi_ratio(D.costs_table())["3"])


def test_the_separate_figure_is_the_whole_programme_beyond_the_headline(tmp_path, big):
    """A Phase 3 asset also running two Phase 2s, one in its modelled disease and one in
    another. Neither is on the path to the Phase 3 readout, so neither is in the headline;
    both are in the separate figure, each with its why, so it covers the whole programme
    rather than the gate's own phase alone. A Phase 1 is never counted."""
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7, enrollment=500)
    _trial(conn, "NCT00000003", 7, phase="Phase 2", enrollment=100, pcd="2028-06-30")
    _trial(conn, "NCT00000004", 7, phase="Phase 2", enrollment=80, disease=AMYLOID,
           pcd="2028-06-30")
    _trial(conn, "NCT00000005", 7, phase="Phase 1", enrollment=40, pcd="2027-06-30")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert [s["nct_id"] for s in got["stages"][0]["studies"]] == ["NCT00000001"]
    outside = {s["nct_id"]: s for s in got["outside"]["studies"]}
    assert set(outside) == {"NCT00000003", "NCT00000004"}
    assert outside["NCT00000003"]["why"] == D.BESIDE_WHY
    assert outside["NCT00000004"]["why"] == "in an indication the forecast does not value"
    share = _share_ahead(dt.date(2025, 10, 6), dt.date(2028, 6, 30))
    assert outside["NCT00000003"]["ahead_usd_mm"] == pytest.approx(100 * 78753 / 1e6 * share)
    assert got["outside"]["cost_usd_mm"] == pytest.approx(180 * 78753 / 1e6 * share)
    # The headline is untouched by them.
    full = 500 * 93145 / 1e6
    assert got["gate"]["full_usd_mm"] == pytest.approx(full)


def test_the_success_leg_is_the_one_the_verdict_shows(tmp_path, big):
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7)
    conn.close()
    got = D.for_asset(path, "ABBV", 7, dt.date.today())
    verdict = V.verdict(path, "ABBV", 7)
    assert got["gate"]["success_leg"] == pytest.approx(verdict["gate"]["rnpv_success"])
    assert got["gate"]["success_leg_per_share"] == pytest.approx(
        verdict["gate"]["per_share_success"])


def _phase2_book(tmp_path, peers):
    path, conn = _book(tmp_path, phase="Phase 2")
    _trial(conn, "NCT00000010", 7, phase="Phase 2", enrollment=120, pcd="2027-06-30")
    for i in range(peers):
        conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                     " VALUES (?, 2, ?, 0)", (100 + i, f"peermab{i}"))
        _trial(conn, f"NCT0000020{i}", 100 + i, enrollment=400 + 100 * i)
        _trial(conn, f"NCT0000030{i}", 100 + i, enrollment=200, table="completed_trials")
    conn.commit()
    return path, conn


def test_a_phase_2_asset_with_three_peers_prices_its_phase_3_from_them(tmp_path, big):
    path, conn = _phase2_book(tmp_path, 3)
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["ok"] is True and got["gate"]["label"] == "Phase 2 readout"
    phase3 = got["stages"][1]
    assert phase3["gate"] == "p3_to_nda" and phase3["route"] == "peer"
    (part,) = phase3["parts"]
    # Peer totals 600, 700, 800 (each with a 200-patient completed study): median 700.
    assert part["peers"] == 3 and part["median_enrollment"] == 700
    assert phase3["cost_usd_mm"] == pytest.approx(700 * 93145 / 1e6)
    assert phase3["grade"] == "analogue"
    assert "Multiple Myeloma" in part["basis"]
    # Spread from the Phase 2 readout over Sertkaya's 57.7-month oncology Phase 3.
    assert phase3["date"] == D.add_months(dt.date(2027, 6, 30), 57.7).isoformat()


def test_with_two_peers_the_benchmark_programme_cost_is_used(tmp_path, big):
    path, conn = _phase2_book(tmp_path, 2)
    conn.close()
    phase3 = D.for_asset(path, "ABBV", 7, TODAY)["stages"][1]
    assert phase3["route"] == "benchmark" and phase3["cost_usd_mm"] == 37.7
    assert phase3["parts"][0]["peers"] == 2


def test_a_seamless_phase_2_3_carries_its_own_phase_3(tmp_path, big):
    path, conn = _book(tmp_path, phase="Phase 2/3")
    _trial(conn, "NCT00000011", 7, phase="Phase 2/3", enrollment=600, pcd="2028-06-30")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    first, phase3 = got["stages"][0], got["stages"][1]
    assert first["studies"][0]["per_patient_usd"] == 93145
    assert phase3["route"] == "seamless" and phase3["cost_usd_mm"] == 0.0


def test_a_positive_readout_leaves_only_the_review(tmp_path, big):
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('0000-26-1', 1, 'etentamig', 3, 'positive',"
                 " '2026-08-19')")
    conn.commit()
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["gate"]["gate"] == "nda_to_approval" and len(got["stages"]) == 1
    assert got["gate"]["cost_usd_mm"] == 2.6
    assert [s["why"] for s in got["outside"]["studies"]] == ["not needed for this gate"]


def test_a_study_past_primary_completion_has_nothing_left_to_spend(tmp_path, big):
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7, start="2022-01-01", pcd="2026-06-30")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["gate"]["due"] is True
    assert got["gate"]["cost_usd_mm"] == 0.0 and got["gate"]["cost"] == 0.0
    assert "sunk" in got["gate"]["basis"]


def test_a_gate_with_no_study_in_a_modelled_indication_is_unread_not_free(tmp_path, big):
    """Its only open Phase 3 is in amyloidosis, which the forecast does not value, and
    nothing has been sunk into the gate. The cost to reach it is unknown: None with the
    reason, never a nil that reads as a gate costing nothing and breaking even at 0%."""
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000002", 7, enrollment=300, disease=AMYLOID, pcd="2029-06-30")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    gate = got["gate"]
    assert got["ok"] is True and gate["gate"] == "p3_to_nda" and gate["trial"] is None
    assert gate["unread"] is True and gate["due"] is False
    for key in ("cost", "cost_per_share", "net", "net_per_share", "breakeven_p", "funds",
                "cost_usd_mm", "full_usd_mm", "grade"):
        assert gate[key] is None, key
    assert gate["high"]["cost"] is None and gate["high"]["funds"] is None
    assert "cannot be read" in gate["basis"] and "1 open study sits outside" in gate["basis"]
    # What passing is worth still reads; only what needs the unread cost does not.
    assert gate["success_leg"] > 0 and gate["ev"] == pytest.approx(gate["rnpv"])
    ladder = got["ladder"]
    assert ladder["value_today"] is None and ladder["risked_cost"] is None
    first, review = ladder["rows"]
    assert first["cost"] is None and first["net"] is None and first["funds"] is None
    assert first["value_if_passed"] > 0 and review["cost"] > 0 and review["funds"] is True
    assert [s["nct_id"] for s in got["outside"]["studies"]] == ["NCT00000002"]
    company = D.for_company(path, "ABBV", TODAY)
    assert [r["asset_id"] for r in company["uncosted"]] == [7]
    assert company["failing"] == [] and company["rows"] == []


def test_a_study_with_no_enrolment_or_no_completion_is_unknown_not_free():
    """The registry gives the study no enrolment, or no primary completion to time it
    by: what it costs is unknown, never a nil. A study already past its completion has
    nothing ahead of it whatever its enrolment."""
    rate = {"value": 93145.0}
    no_count = D.study_cost({"nct_id": "N1", "enrollment": None, "start_date": "2026-01-01",
                             "primary_completion_date": "2028-01-01"}, rate, TODAY)
    assert no_count["ahead_usd_mm"] is None and no_count["full_usd_mm"] is None
    assert no_count["missing"] == "has no enrolment on file"
    assert no_count["spend_from"] is None and no_count["spend_to"] is None
    zero = D.study_cost({"nct_id": "N2", "enrollment": 0, "start_date": "2026-01-01",
                         "primary_completion_date": "2028-01-01"}, rate, TODAY)
    assert zero["ahead_usd_mm"] is None and zero["missing"] == "has no enrolment on file"
    undated = D.study_cost({"nct_id": "N3", "enrollment": 300, "start_date": "2026-01-01",
                            "primary_completion_date": None}, rate, TODAY)
    assert undated["ahead_usd_mm"] is None
    assert undated["missing"] == "has no primary completion date on file"
    sunk = D.study_cost({"nct_id": "N4", "enrollment": None, "start_date": "2022-01-01",
                         "primary_completion_date": "2026-01-01"}, rate, TODAY)
    assert sunk["ahead_usd_mm"] == 0.0 and sunk["missing"] is None
    assert sunk["full_usd_mm"] is None


def test_a_gate_study_with_no_enrolment_leaves_the_gate_unread_not_free(tmp_path, big):
    """The only study counted towards the gate has no enrolment on file. Priced at nil, the
    gate would read as costing nothing and breaking even at 0%; it is unread, with the
    study named, and the company view lists the line under uncosted."""
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7, enrollment=None)
    _trial(conn, "NCT00000002", 7, enrollment=200, pcd="2029-06-30")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    gate = got["gate"]
    assert got["ok"] is True and gate["unread"] is True
    for key in ("cost", "net", "breakeven_p", "funds", "cost_usd_mm", "full_usd_mm"):
        assert gate[key] is None, key
    assert gate["basis"] == ("what reaching this gate costs cannot be read from the registry:"
                             " NCT00000001 has no enrolment on file")
    assert gate["ev"] == pytest.approx(gate["rnpv"]) and gate["success_leg"] > 0
    assert got["ladder"]["value_today"] is None and got["ladder"]["risked_cost"] is None
    assert {s["nct_id"] for s in got["stages"][0]["studies"]} == {"NCT00000001",
                                                                 "NCT00000002"}
    company = D.for_company(path, "ABBV", TODAY)
    assert [r["asset_id"] for r in company["uncosted"]] == [7]
    assert company["failing"] == [] and company["rows"] == []


def test_a_later_stage_that_cannot_be_costed_leaves_what_rests_on_it_unread(tmp_path, big):
    """The Phase 2 gate reads; the registered Phase 3 in the same disease has no
    enrolment on file. The headline still reads, since it needs only the cost to the
    Phase 2 readout, but the value if the Phase 2 passes after later trial costs, and
    today's value after every cost, are None rather than computed on a nil Phase 3."""
    path, conn = _phase2_book(tmp_path, 3)
    _trial(conn, "NCT00000099", 7, enrollment=None, start="2027-07-01", pcd="2031-06-30",
           status="Not yet recruiting")
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    gate, (first, phase3, review) = got["gate"], got["stages"]
    assert gate["label"] == "Phase 2 readout" and gate["unread"] is False
    assert gate["cost"] > 0 and gate["net"] == pytest.approx(gate["ev"] - gate["cost"])
    assert phase3["unread"] is True and phase3["cost_usd_mm"] is None
    assert "NCT00000099 has no enrolment on file" in phase3["basis"]
    rows = got["ladder"]["rows"]
    assert rows[0]["value_if_passed"] is None and rows[0]["net"] is None
    assert rows[1]["value_if_passed"] > 0 and rows[1]["cost"] is None
    assert rows[1]["net"] is None and rows[1]["funds"] is None
    assert rows[2]["value_if_passed"] > 0 and rows[2]["funds"] is True
    assert got["ladder"]["value_today"] is None and got["ladder"]["risked_cost"] is None


def test_a_ladder_with_an_unread_later_stage_by_hand():
    stages = [{"gate": g, "label": g, "date": None, "p": p}
              for g, p in (("p2_to_p3", 0.5), ("p3_to_nda", 0.6), ("nda_to_approval", 0.9))]
    got = D.ladder(stages, 540.0, [10.0, None, 2.0])
    rows = got["rows"]
    assert rows[0]["value_if_passed"] is None and rows[0]["ev_at_gate"] is None
    assert rows[0]["net"] is None and rows[0]["funds"] is None
    assert rows[0]["value_if_passed_floored"] is None and rows[0]["floored"] is False
    assert rows[1]["value_if_passed"] == pytest.approx(898.0) and rows[1]["net"] is None
    assert rows[2]["value_if_passed"] == pytest.approx(1000.0) and rows[2]["funds"] is True
    assert got["risked_cost"] is None and got["value_today"] is None


def test_a_kroner_asset_is_converted_at_the_stored_rate(tmp_path, big):
    path, conn = _book(tmp_path, currency="DKK")
    _trial(conn, "NCT00000001", 7)
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["currency"] == "DKK" and got["fx"]["rate"] == 0.15
    anchor = dt.date(TODAY.year - 1, 12, 31)
    usd = D.pv_even(got["gate"]["cost_usd_mm"], TODAY, dt.date(2030, 3, 31), 0.09, anchor)
    assert got["gate"]["cost"] == pytest.approx(usd / 0.15 * 0.85)


def test_tax_is_netted_only_on_the_pharma_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)
    monkeypatch.setattr(engines, "assign", lambda *a, **k: engines.BIOTECH)
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7)
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["after_tax"] is False and got["tax_rate"] is None
    anchor = dt.date(TODAY.year - 1, 12, 31)
    assert got["gate"]["cost"] == pytest.approx(
        D.pv_even(got["gate"]["cost_usd_mm"], TODAY, dt.date(2030, 3, 31), 0.09, anchor))


def test_a_partner_cost_follows_its_share_of_the_economics(tmp_path, big):
    path, conn = _book(tmp_path, share=0.6)
    _trial(conn, "NCT00000001", 7)
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["portion"] == 0.6 and got["portion_basis"] == D.PORTION_NOTE
    full = D.pv_even(got["gate"]["cost_usd_mm"], TODAY, dt.date(2030, 3, 31), 0.09,
                     dt.date(TODAY.year - 1, 12, 31)) * 0.85
    assert got["gate"]["cost"] == pytest.approx(full * 0.6)


def test_a_partner_bears_the_rest_and_nets_tax_on_its_own_engine(tmp_path, monkeypatch):
    """The owner keeps 60% and is on the pharma engine; the partner named in the rows
    bears the other 40% and is not, so its share of the cost stays pre-tax. Whether a
    deduction can be used now belongs to the company bearing the cost."""
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: True)
    monkeypatch.setattr(engines, "assign", lambda conn, company_id, revenue: (
        engines.PHARMA if company_id == 1 else engines.BIOTECH))
    path, conn = _book(tmp_path, share=0.6)
    _trial(conn, "NCT00000001", 7)
    conn.execute("INSERT INTO assumptions (asset_id, key, text_value, source)"
                 " VALUES (7, 'partner_ticker', 'OTHR', 't')")
    conn.commit()
    conn.close()
    owner, partner = D.for_asset(path, "ABBV", 7, TODAY), D.for_asset(path, "OTHR", 7, TODAY)
    pv = D.pv_even(owner["gate"]["cost_usd_mm"], TODAY, dt.date(2030, 3, 31), 0.09,
                   dt.date(TODAY.year - 1, 12, 31))
    assert owner["portion"] == 0.6 and owner["after_tax"] is True
    assert owner["gate"]["cost"] == pytest.approx(pv * 0.85 * 0.6)
    assert partner["portion"] == pytest.approx(0.4) and partner["after_tax"] is False
    assert partner["gate"]["cost"] == pytest.approx(pv * 0.4)
    assert "company bearing the cost" in partner["tax_basis"]


def test_refusals_are_data(tmp_path, big, monkeypatch):
    path, conn = _book(tmp_path, name="Investigational zoster vaccine")
    _trial(conn, "NCT00000001", 7)
    conn.close()
    assert D.for_asset(path, "ABBV", 7, TODAY)["reason"] == "vaccine"
    assert D.for_asset(path, "ZZZZ", 7, TODAY) is None
    assert D.for_asset(path, "OTHR", 7, TODAY) is None
    conn = db.get_connection(path)
    conn.execute("UPDATE assets SET generic_name = 'etentamig'")
    # Its only Phase 3 read out negative and none stays open: nil, no gate left.
    conn.execute("UPDATE trials SET overall_status = 'Completed'")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('0000-26-9', 1, 'etentamig', 3, 'negative',"
                 " '2026-08-19')")
    conn.commit()
    assert D.for_asset(path, "ABBV", 7, TODAY)["reason"] == "no_gate"
    conn.execute("UPDATE assets SET is_marketed = 1")
    conn.commit()
    conn.close()
    assert D.for_asset(path, "ABBV", 7, TODAY)["reason"] == "marketed"
    monkeypatch.setattr(PG, "big_pharma", lambda *a, **k: False)
    conn = db.get_connection(path)
    conn.execute("UPDATE assets SET is_marketed = 0")
    conn.execute("DELETE FROM trial_readouts")
    conn.commit()
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    assert got["ok"] is False and got["reason"] == "no_gate_split"
    assert got["reason"] in D.REFUSALS and got["why"]


def test_the_company_view_puts_failing_gates_first_and_reconciles(tmp_path, big):
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7)
    conn.close()
    got = D.for_company(path, "ABBV", TODAY)
    assert [r["asset_id"] for r in got["failing"] + got["rows"]] == [7]
    rec = got["reconciliation"]
    assert set(rec) >= {"named_spend_12m", "book_rd", "book_rd_year", "ratio", "sentence"}
    assert D.for_company(path, "ZZZZ", TODAY) is None


def test_the_copy_keeps_the_house_style(tmp_path, big):
    path, conn = _phase2_book(tmp_path, 2)
    conn.close()
    got = D.for_asset(path, "ABBV", 7, TODAY)
    texts = [got["tax_basis"], got["area_basis"], got["anchor_basis"], got["paid_note"],
             got["outside"]["note"], got["next_12m"]["basis"], got["gate"]["high"]["label"],
             D.HIGH_LABEL, D.PORTION_NOTE]
    for stage in got["stages"]:
        texts += [stage["basis"], stage.get("date_basis") or ""]
        texts += [p["basis"] for p in stage.get("parts") or []]
    texts += [D.__doc__]
    for text in texts:
        assert "—" not in text
        for word in BANNED:
            assert word not in text.lower(), (word, text)


# --- nothing on the value path reaches it --------------------------------------------

def _imports(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_no_module_on_the_value_path_imports_development():
    """The R&D ratio already pays for these trials. A cost wired into the build, the sum
    of the parts, the future pipeline, the 12-month value, the ratings or the
    break-points would count it twice, and this is the fence."""
    backend = Path(__file__).resolve().parent.parent
    for name in ("forecast", "forecast_view", "assumptions", "pos_granular",
                 "company_score", "breakpoints", "fair_value", "comps_valuation",
                 "future_pipeline", "launch_timing", "company_lines", "insights"):
        source = backend / f"{name}.py"
        if source.exists():
            assert "development" not in _imports(source), name


def test_loading_the_value_path_never_brings_development_in():
    """The scan above reads each module's own imports. This loads the value path, and the
    refresh that writes snapshots, in a fresh interpreter and checks the module never
    arrives through anything they import in turn."""
    import subprocess
    import sys
    backend = Path(__file__).resolve().parent.parent
    code = ("import sys\n"
            "import forecast, forecast_view, assumptions, pos_granular, company_score\n"
            "import breakpoints, fair_value, comps_valuation, future_pipeline, valuation\n"
            "import launch_timing, company_lines, insights, refresh, scheduled_refresh\n"
            "print('development' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=backend, capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "False"
