"""The disease area scorecard (backend/disease_areas.py): which assets sit in an area, the
four pillars, the 0 to 100 scale, the overall, USD conversion, and missing data staying
missing.

``assemble`` takes plain inputs, so most rules are tested on hand-built rows; the area
assignment and the stage are tested on a tmp_path database.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest

import db
import disease_areas as D

TODAY = dt.date(2026, 10, 7)
RATES = {"DKK": 0.15, "EUR": 1.1, "as_of": "2026-10-06"}
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


# --- names and the scale -----------------------------------------------------------
def test_an_area_travels_as_a_slug_and_back():
    assert D.slug("Immunology and inflammation") == "immunology-and-inflammation"
    assert D.area_of("immunology-and-inflammation") == "Immunology and inflammation"
    assert D.area_of("ONCOLOGY") == "Oncology"
    assert D.area_of("nowhere") is None


def test_healthy_volunteers_and_other_are_not_areas():
    names = D.area_names()
    assert "Oncology" in names and "Metabolic" in names
    assert "Healthy volunteers" not in names and "Other" not in names
    assert D.area_of("healthy-volunteers") is None


def test_the_scale_is_a_percentile_rank_from_0_to_100():
    s = D.percentile_scores({"a": 1.0, "b": 10.0, "c": 1000.0})
    assert s == {"a": 0.0, "b": 50.0, "c": 100.0}


def test_a_tie_counts_half_and_a_missing_figure_stays_missing():
    s = D.percentile_scores({"a": 0.0, "b": 0.0, "c": 5.0, "d": None})
    assert s["a"] == s["b"] == pytest.approx(25.0)
    assert s["c"] == 100.0
    assert s["d"] is None


def test_less_is_better_reverses_the_scale():
    s = D.percentile_scores({"a": 0.1, "b": 0.5, "c": 0.9}, higher_is_better=False)
    assert s == {"a": 100.0, "b": 50.0, "c": 0.0}


def test_a_company_alone_with_a_figure_scores_50():
    assert D.percentile_scores({"a": 3.0, "b": None}) == {"a": 50.0, "b": None}
    assert D.percentile_scores({}) == {}


def test_the_overall_is_the_mean_of_the_pillars_present_with_the_count():
    assert D.overall({"value": 80, "pipeline": 40, "durability": None, "clinical": 60}) \
        == (pytest.approx(60.0), 3)
    assert D.overall({"value": None, "pipeline": None, "durability": None,
                      "clinical": None}) == (None, 0)


def test_usd_converts_at_the_books_rate_and_never_guesses_one():
    assert D.usd(100.0, "USD", RATES) == 100.0
    assert D.usd(100.0, "DKK", RATES) == pytest.approx(15.0)
    assert D.usd(100.0, "CHF", RATES) is None
    assert D.usd(None, "USD", RATES) is None


# --- the assembly ---------------------------------------------------------------------
def _asset(id_, company_id, area, stage, name=None, brand=None):
    return {"id": id_, "company_id": company_id, "area": area, "name": name or f"A{id_}",
            "brand_name": brand or name or f"A{id_}", "generic_name": None,
            "is_marketed": 1 if stage == "Marketed" else 0, "stage": stage,
            "phase": None if stage == "Marketed" else stage, "has_model": False}


def _line(asset_id, rnpv, marketed, gate=None, counted=True):
    return {"asset_id": asset_id, "rnpv_share": rnpv, "is_marketed": marketed,
            "counted": counted, "gate": {"gate": gate} if gate else None}


def _verdict(currency, lines):
    return {"ok": True, "sotp": {"fx": {"currency": currency}}, "modelled": lines}


COMPANIES = [{"id": 1, "ticker": "AAA", "name": "Alpha Pharma Inc.", "currency": "USD"},
             {"id": 2, "ticker": "BBB", "name": "Beta A/S", "currency": "DKK"},
             {"id": 3, "ticker": "CCC", "name": "Gamma AG", "currency": "EUR"},
             {"id": 4, "ticker": "DDD", "name": "Delta plc", "currency": "USD"}]


def _book():
    assets = [
        # Alpha: two marketed (one modelled), a Phase 3, a filed one, and a product in
        # another area whose value must not count here.
        _asset(10, 1, "Oncology", "Marketed", "Onco1"),
        _asset(11, 1, "Oncology", "Marketed", "Onco2"),
        _asset(12, 1, "Oncology", "Phase 3", "P3a"),
        _asset(13, 1, "Oncology", "Phase 2", "Filedx"),
        _asset(14, 1, "Metabolic", "Marketed", "Meta1"),
        # Beta files in kroner.
        _asset(20, 2, "Oncology", "Marketed", "Krone1"),
        _asset(21, 2, "Oncology", "Phase 2", "P2b"),
        # Gamma: marketed with no model value, nothing else.
        _asset(30, 3, "Oncology", "Marketed", "Unvalued"),
        # Delta: a Phase 1 only, so not present; and an unplaced asset.
        _asset(40, 4, "Oncology", "Phase 1", "Early"),
        _asset(41, 4, None, "Marketed", "Nowhere"),
    ]
    verdicts = {
        "AAA": _verdict("USD", [_line(10, 10000.0, True), _line(12, 2000.0, False),
                                _line(13, 1000.0, False, gate="nda_to_approval"),
                                _line(14, 7000.0, True)]),
        "BBB": _verdict("DKK", [_line(20, 100000.0, True), _line(21, 20000.0, False)]),
        "CCC": _verdict("EUR", [_line(99, 500.0, True)]),
        "DDD": _verdict("USD", [_line(41, 900.0, True)]),
    }
    revenue = {10: {"value": 6e9, "unit": "USD", "fiscal_year": 2025},
               11: {"value": 4e9, "unit": "USD", "fiscal_year": 2025},
               20: {"value": 10e9, "unit": "DKK", "fiscal_year": 2025}}
    loe = {10: {"date": "2028-06-01", "basis": "compound patent"},
           11: {"date": "2029-01-01", "basis": "orphan exclusivity"},
           20: {"date": "2035-01-01", "basis": "compound patent"}}
    stakes = {
        "AAA": {"priced": [
            {"asset_id": 12, "asset_name": "P3a", "catalyst_type": "data readout",
             "expected_date": "2027-05-01", "share_swing": 3000.0},
            {"asset_id": 12, "asset_name": "P3a", "catalyst_type": "data readout",
             "expected_date": "2029-05-01", "share_swing": 9999.0},
            {"asset_id": 14, "asset_name": "Meta1", "catalyst_type": "data readout",
             "expected_date": "2027-01-01", "share_swing": 5000.0},
            {"asset_id": 13, "asset_name": "Filedx", "catalyst_type": "PDUFA",
             "expected_date": "2027-01-01", "share_swing": 4000.0}],
            "unpriced": [{"asset_id": 10, "asset_name": "Onco1",
                          "catalyst_type": "data readout", "expected_date": "2027-02-01"}]},
        "BBB": {"priced": [{"asset_id": 21, "asset_name": "P2b",
                            "catalyst_type": "data readout",
                            "expected_date": "2028-01-01", "share_swing": 10000.0}],
                "unpriced": []},
    }
    clinical = D.clinical_by_company([
        {"ticker": "AAA", "asset_id": 10, "name": "Onco1", "indication": "x", "overall": 80.0},
        {"ticker": "AAA", "asset_id": 10, "name": "Onco1", "indication": "y", "overall": 60.0},
        {"ticker": "AAA", "asset_id": 12, "name": "P3a", "indication": "x", "overall": 40.0},
        {"ticker": "BBB", "asset_id": 20, "name": "Krone1", "indication": "x", "overall": 90.0},
    ])
    return assets, verdicts, revenue, loe, stakes, clinical


def _page():
    assets, verdicts, revenue, loe, stakes, clinical = _book()
    return D.assemble("Oncology", COMPANIES, assets, verdicts, revenue, loe, stakes, clinical,
                      RATES, TODAY)


def _row(page, ticker):
    return next(r for r in page["companies"] if r["ticker"] == ticker)


def test_a_company_with_only_early_assets_is_not_present():
    page = _page()
    assert [r["ticker"] for r in page["companies"]].count("DDD") == 0
    assert page["totals"]["companies"] == 3


def test_value_today_counts_marketed_products_in_the_area_only_whole():
    a = _row(_page(), "AAA")
    # Onco1 is valued; Onco2 is marketed with no line; Meta1 is in another area.
    assert a["value"]["usd_bn"] == pytest.approx(10.0)
    assert (a["value"]["valued"], a["value"]["products"]) == (1, 2)
    # The area's share of every modelled line the company holds: 13 of 20.
    assert a["value"]["share"] == pytest.approx(13000.0 / 20000.0)


def test_values_are_converted_to_usd_at_the_books_rate():
    b = _row(_page(), "BBB")
    assert b["currency"] == "DKK"
    assert b["value"]["usd_bn"] == pytest.approx(100000.0 * 0.15 / 1000)
    assert b["pipeline"]["usd_bn"] == pytest.approx(20000.0 * 0.15 / 1000)
    assert b["durability"]["revenue_usd_bn"] == pytest.approx(10.0 * 0.15)


def test_a_currency_with_no_rate_gives_no_usd_figure():
    assets, verdicts, revenue, loe, stakes, clinical = _book()
    page = D.assemble("Oncology", COMPANIES, assets, verdicts, revenue, loe, stakes, clinical,
                      {"as_of": "2026-10-06"}, TODAY)
    b = _row(page, "BBB")
    assert b["value"]["usd_bn"] is None
    assert "rate" in b["value"]["basis"]
    assert b["scores"]["value"] is None


def test_marketed_with_no_model_value_has_no_figure_and_nothing_marketed_is_a_fact():
    page = _page()
    c = _row(page, "CCC")
    assert c["value"]["usd_bn"] is None and c["scores"]["value"] is None
    assert c["pipeline"]["usd_bn"] == 0.0 and c["pipeline"]["assets"] == 0
    # Nothing marketed is a value of nought, scored at the foot, and says why.
    assets, verdicts, revenue, loe, stakes, clinical = _book()
    assets = [a for a in assets if a["id"] not in (10, 11)]
    page = D.assemble("Oncology", COMPANIES, assets, verdicts, revenue, loe, stakes, clinical,
                      RATES, TODAY)
    a = _row(page, "AAA")
    assert a["value"]["basis"] == "none marketed" and a["value"]["usd_bn"] == 0.0
    assert a["scores"]["value"] == 0.0


def test_a_forecast_at_its_approval_gate_is_filed_and_counts_in_depth():
    a = _row(_page(), "AAA")
    assert sorted((x["name"], x["stage"]) for x in a["pipeline"]["late"]) == [
        ("Filedx", "Filed"), ("P3a", "Phase 3")]
    assert a["pipeline"]["depth"] == 2
    assert a["counts"]["filed"] == 1
    assert a["pipeline"]["usd_bn"] == pytest.approx(3.0)


def test_the_pipeline_pillar_averages_value_and_depth():
    page = _page()
    for r in page["companies"]:
        p = r["pipeline"]
        parts = [s for s in (p["value_score"], p["depth_score"]) if s is not None]
        assert r["scores"]["pipeline"] == pytest.approx(sum(parts) / len(parts))
    a = _row(page, "AAA")
    assert a["pipeline"]["depth_score"] == 100.0


def test_durability_is_the_share_losing_exclusivity_within_5_years():
    page = _page()
    a = _row(page, "AAA")
    # Onco1 (6bn) goes in 2028; Onco2 (4bn) holds only orphan exclusivity, left out.
    assert a["durability"]["share"] == pytest.approx(0.6)
    assert a["durability"]["at_risk_usd_bn"] == pytest.approx(6.0)
    assert [p["name"] for p in a["durability"]["products"]] == ["Onco1"]
    assert page["horizon_end"] == 2030
    # Beta's goes in 2035, outside the window: none at risk, which scores best.
    b = _row(page, "BBB")
    assert b["durability"]["share"] == 0.0
    assert b["scores"]["durability"] == 100.0
    # Gamma has no revenue on file: no figure, never a zero.
    c = _row(page, "CCC")
    assert c["durability"]["share"] is None and c["scores"]["durability"] is None


def test_clinical_quality_is_each_drugs_mean_then_the_companys():
    page = _page()
    a = _row(page, "AAA")
    # Onco1 (80 + 60) / 2 = 70, P3a 40: the company 55.
    assert a["clinical"]["mean"] == pytest.approx(55.0)
    assert [d["name"] for d in a["clinical"]["drugs"]] == ["Onco1", "P3a"]
    assert _row(page, "CCC")["clinical"]["mean"] is None
    assert _row(page, "CCC")["scores"]["clinical"] is None


def test_readouts_are_data_readouts_within_24_months_on_area_assets():
    page = _page()
    a = _row(page, "AAA")
    # P3a 2027 priced, Onco1 2027 unpriced; P3a 2029 is too late, Meta1 is another area
    # and the PDUFA is not a readout.
    assert a["readouts"]["count"] == 2
    assert a["readouts"]["priced"] == 1
    assert a["readouts"]["stake_usd_bn"] == pytest.approx(3.0)
    b = _row(page, "BBB")
    assert b["readouts"]["stake_usd_bn"] == pytest.approx(1.5)
    assert _row(page, "CCC")["readouts"]["stake_usd_bn"] is None
    assert page["readout_end"] == "2028-10-07"


def test_every_pillar_runs_0_to_100_and_the_ranking_follows_the_overall():
    page = _page()
    rows = page["companies"]
    for r in rows:
        for v in r["scores"].values():
            assert v is None or 0.0 <= v <= 100.0
        have = [v for v in r["scores"].values() if v is not None]
        assert r["pillars"] == len(have)
        assert r["overall"] == pytest.approx(sum(have) / len(have))
    overalls = [r["overall"] for r in rows]
    assert overalls == sorted(overalls, reverse=True)
    assert [r["rank"] for r in rows] == [1, 2, 3]


def test_the_area_totals_sum_the_companies_in_usd():
    t = _page()["totals"]
    assert t["companies"] == 3
    assert t["value_usd_bn"] == pytest.approx(10.0 + 15.0)
    assert t["pipeline_usd_bn"] == pytest.approx(3.0 + 3.0)
    assert t["risked_usd_bn"] == pytest.approx(31.0)
    assert t["revenue_usd_bn"] == pytest.approx(10.0 + 1.5)
    assert t["at_risk_share"] == pytest.approx(6.0 / 11.5)
    assert (t["marketed"], t["late"], t["filed"], t["phase2"]) == (4, 2, 1, 1)
    assert t["readouts"] == 3


def test_the_cards_are_house_style_short_and_never_print_a_made_up_zero():
    page = _page()
    kinds = [c["kind"] for c in page["cards"]]
    assert kinds == ["leader", "pipeline", "risk", "readouts"]
    for c in page["cards"]:
        text = " ".join((c["title"], c["headline"], c["detail"]))
        assert "—" not in text
        assert not any(re.search(rf"\b{w}\b", text, re.I) for w in BANNED)
        assert len(c["title"]) <= 30 and len(c["headline"]) <= 74 and len(c["detail"]) <= 132
        assert "$0.00bn" not in text and "$0.0bn" not in text
    assets, verdicts, revenue, loe, stakes, clinical = _book()
    assets = [a for a in assets if a["id"] not in (10, 11, 20, 30)]
    page = D.assemble("Oncology", COMPANIES, assets, verdicts, revenue, loe, {}, clinical,
                      RATES, TODAY)
    lead = page["cards"][0]
    assert "nothing marketed" in lead["detail"].lower()
    assert page["cards"][-1]["headline"] == "No readout here is priced"


def test_the_method_states_every_rule():
    m = D.METHOD
    for key in ("value", "pipeline", "durability", "clinical", "scale", "overall",
                "assignment", "currency", "readouts"):
        assert m[key]
        assert "—" not in m[key]
        assert not any(re.search(rf"\b{w}\b", m[key], re.I) for w in BANNED)
    assert "percentile" in m["scale"] and "50" in m["scale"]


# --- the book: area assignment and stage ----------------------------------------------
ONCOLOGY_LABEL = ("1 INDICATIONS AND USAGE TAGRISSO is indicated for metastatic non-small "
                  "cell lung cancer.")


def _seed(tmp_path):
    path = str(tmp_path / "areas.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('AZN', 'AstraZeneca PLC')")
    conn.commit()
    return path, conn


def _add(conn, brand, marketed=0, generic=None):
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                       " is_marketed) VALUES (?, ?, ?, ?)", (cid, brand, generic, marketed))
    conn.commit()
    return cur.lastrowid


def _ind(conn, asset_id, name, phase, status="Recruiting"):
    row = conn.execute("SELECT id FROM indications WHERE name = ?", (name,)).fetchone()
    iid = row["id"] if row else conn.execute(
        "INSERT INTO indications (name) VALUES (?)", (name,)).lastrowid
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase,"
                 " development_status) VALUES (?, ?, ?, ?)", (asset_id, iid, phase, status))
    conn.commit()


def test_a_product_sits_in_the_area_its_label_names_first(tmp_path):
    path, conn = _seed(tmp_path)
    tag = _add(conn, "Tagrisso", marketed=1)
    conn.execute("INSERT INTO labels (setid, asset_id, effective_time, indications_text)"
                 " VALUES ('s1', ?, '2026-01-01', ?)", (tag, ONCOLOGY_LABEL))
    # Trialled mostly in a metabolic disease, it still counts once, in oncology.
    _ind(conn, tag, "Diabetes Mellitus, Type 2", "Phase 3")
    conn.commit()
    rows = {a["name"]: a for a in D._assets(conn, [1])}
    assert rows["Tagrisso"]["area"] == "Oncology"
    assert rows["Tagrisso"]["stage"] == "Marketed"


def test_the_stage_is_the_furthest_active_phase_and_retired_programmes_leave(tmp_path):
    path, conn = _seed(tmp_path)
    a = _add(conn, None, generic="testinib")
    _ind(conn, a, "Breast Neoplasms", "Phase 2")
    _ind(conn, a, "Lung Neoplasms", "Phase 3")
    _ind(conn, a, "Ovarian Neoplasms", "Phase 4", "Discontinued")
    # Placed by what its trials study, as product_areas does for an unlabelled asset.
    conn.execute("INSERT INTO trials (nct_id, asset_id, conditions) VALUES"
                 " ('NCT0', ?, '[\"Lung Neoplasms\"]')", (a,))
    b = _add(conn, None, generic="stoppedinib")
    _ind(conn, b, "Lung Neoplasms", "Phase 3")
    conn.execute("INSERT INTO retired_programmes (asset_id, stopped_on, basis)"
                 " VALUES (?, '2026-01-01', 'test')", (b,))
    h = _add(conn, None, generic="volunteerab")
    conn.execute("INSERT INTO trials (nct_id, asset_id, conditions) VALUES"
                 " ('NCT1', ?, '[\"Healthy\"]')", (h,))
    conn.commit()
    rows = {a["name"]: a for a in D._assets(conn, [1])}
    assert rows["testinib"]["stage"] == "Phase 3"
    assert rows["testinib"]["area"] == "Oncology"
    assert "stoppedinib" not in rows
    # Healthy volunteers is not a disease area.
    assert rows["volunteerab"]["area"] is None


def test_the_index_lists_areas_with_the_companies_present(tmp_path):
    path, conn = _seed(tmp_path)
    tag = _add(conn, "Tagrisso", marketed=1)
    conn.execute("INSERT INTO labels (setid, asset_id, effective_time, indications_text)"
                 " VALUES ('s1', ?, '2026-01-01', ?)", (tag, ONCOLOGY_LABEL))
    early = _add(conn, None, generic="earlymab")
    _ind(conn, early, "Asthma", "Phase 1")
    conn.commit()
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    conn.close()
    index = D.index(path, cohort={cid})
    assert [a["area"] for a in index] == ["Oncology"]
    assert index[0]["tickers"] == ["AZN"] and index[0]["marketed"] == 1
    assert index[0]["assets_by_ticker"] == {"AZN": 1}
    assert index[0]["slug"] == "oncology"
