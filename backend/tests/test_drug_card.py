"""The drug card of Comps > Indications: the backend assembly (drug_card.py) on a tmp_path
book, its route, and the frontend card and click wiring on saved payloads."""

from __future__ import annotations

import ast
import html
import json
import pathlib
import re
import sys

import pytest

import db
import drug_card
import forecast_view
import landscape as L
from test_landscape import _book

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
APP = FRONTEND / "streamlit_app.py"
sys.path.insert(0, str(FRONTEND))

import drug_card_view as DCV  # noqa: E402
from components import charts  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
TODAY = "2026-10-07"


def text_of(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"drug_card_{name}.json").read_text())


# --- the backend assembly -------------------------------------------------------------
@pytest.fixture
def book(tmp_path, monkeypatch):
    path = _book(tmp_path)
    monkeypatch.setattr(L, "_big_pharma_ids", lambda conn: {1, 2})
    monkeypatch.setattr(L, "_model_lines", lambda db_path, tickers, verdict_for=None: {})
    return path, L.landscape(path, 1)


STAKES = {"priced": [
    {"asset_id": 2, "expected_date": "2027-03-01", "catalyst_type": "data readout",
     "description": "NCT9", "priced": True, "per_share": 1.5, "gate_label": "Phase 3 readout"},
    {"asset_id": 2, "expected_date": "2020-01-01", "catalyst_type": "data readout",
     "priced": True, "per_share": 9.0},                             # past: left off
    {"asset_id": 7, "expected_date": "2027-01-01", "priced": True, "per_share": 3.0}],
    "unpriced": []}


def test_a_marketed_drug_carries_every_section_from_its_sources(book):
    path, land = book
    c = drug_card.card(path, land, 1, scorecard=None, stakes_for=lambda t: STAKES,
                       today=TODAY)
    assert c["head"]["name"] == "Tirzepatide" and c["head"]["brands"] == ["Zepbound"]
    assert c["head"]["mechanisms"][0]["value"].startswith("Glucagon-like")
    # Its posted arm, against the same trial's placebo.
    row = c["efficacy"]["groups"][0]["rows"][0]
    assert (row["value"], row["placebo"], row["delta"]) == (-20.9, -2.4, pytest.approx(-18.5))
    assert c["safety"]["serious_rate"] == pytest.approx(40 / 630)
    assert c["trials"] == [dict(c["trials"][0], nct_id="NCT1", has_results=True)]
    # Marketed: the product profile's commercial block is there; the company's other
    # asset's catalysts are not.
    assert c["commercial"] is not None and c["commercial"]["brand"] == "Zepbound"
    assert c["catalysts"] == []


def test_missing_stays_missing(book):
    path, land = book
    c = drug_card.card(path, land, 2, scorecard={"assets": []}, stakes_for=lambda t: STAKES,
                       today=TODAY)
    # Not modelled, not scored, no trial posted, not marketed: nothing is filled in.
    assert c["model"] is None and c["valuation"] == [] and c["patients"] == []
    assert c["score"] is None and c["safety"] is None and c["commercial"] is None
    assert c["efficacy"] == {"groups": [], "rows": 0, "shown": 0}
    # Its own future catalyst only, next first.
    assert [x["expected_date"] for x in c["catalysts"]] == ["2027-03-01"]
    assert drug_card.card(path, land, 99, stakes_for=lambda t: STAKES) is None


VERDICT = {"ok": True, "asset_id": 2, "name": "Cagrilintide", "mode": "chronic",
           "per_share": 0.42, "pct_of_price": 0.004, "close_date": "2026-10-06",
           "peak_revenue": 900.0, "peak_year": 2038, "pos": 0.55, "pos_basis": "published",
           "loe_year": 2041, "loe_basis": "12 years from launch", "wacc": 0.075,
           "gate": {"label": "Phase 3 readout", "date": "2027-03-01", "p_gate": 0.6,
                    "per_share_now": 0.42, "per_share_success": 0.7,
                    "per_share_failure": 0.0, "basis": "BIO 2011-2020"},
           "launch": {"seed_year": 2029, "seed_source": "two years after readout"}}


def test_a_modelled_pipeline_drug_carries_its_value_gate_and_patient_build(book, monkeypatch):
    path, land = book
    monkeypatch.setattr(L, "_model_lines", lambda db_path, tickers, verdict_for=None: {
        2: {"per_share": 0.42, "currency": "USD"}})
    inputs = {"scalars": {"list_price_per_patient": 0.012, "gross_to_net_pct": 0.5},
              "indications": [{"name": "Obesity", "indication_id": 1,
                               "scalars": {"prevalence": 1000.0, "eligible_pct": 0.3,
                                           "penetration_peak_pct": 0.1}}],
              "crowding": [{"indication": "Obesity", "factor": 0.8, "stated": 0.1,
                            "applied": 0.08}]}
    rows = [{"key": "eligible_pct", "indication_id": 1, "year": None, "region": "US",
             "unit": "share", "source": "a cited trial", "evidence": "published"},
            {"key": "list_price_per_patient", "indication_id": None, "year": None,
             "region": "US", "unit": "mm USD per year", "source": "CMS", "evidence": "measured"}]
    monkeypatch.setattr(drug_card.assumptions_module, "load", lambda conn, a, s: inputs)
    monkeypatch.setattr(drug_card.assumptions_module, "rows", lambda conn, a, s: rows)
    monkeypatch.setattr(drug_card.epidemiology, "for_indication",
                        lambda name: {"source": "the disease's own row"})
    c = drug_card.card(path, land, 2, verdict_of=lambda t, a: VERDICT,
                       stakes_for=lambda t: STAKES, today=TODAY)
    v = c["valuation"][0]
    assert (v["per_share"], v["pos"], v["loe_year"], v["launch_year"]) == (0.42, 0.55, 2041, 2029)
    assert v["gate"]["per_share_success"] == 0.7
    build = c["patients"][0]
    assert build["indication"] == "Obesity"
    got = {i["key"]: i for i in build["inputs"]}
    assert got["eligible_pct"]["source"] == "a cited trial"
    assert got["prevalence"]["source"] == "the disease's own row"      # filled, sourced
    assert got["prevalence"]["evidence"] is None                         # never a made-up grade
    assert build["net_price"] == pytest.approx(0.006)
    assert build["crowding"]["factor"] == 0.8


def test_the_route_serves_the_card_and_refuses_a_stranger(book, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    path, land = book
    monkeypatch.setattr(db, "DB_PATH", pathlib.Path(path))
    monkeypatch.setattr(main.landscape_module, "landscape",
                        lambda db_path, i, verdict_for=None: land if i == 1 else None)
    monkeypatch.setattr(main.landscape_score, "scorecard", lambda land: {"assets": []})
    monkeypatch.setattr(forecast_view, "catalyst_stakes", lambda db_path, t: STAKES)
    client = TestClient(main.app)
    ok = client.get("/indications/1/drug/1")
    assert ok.status_code == 200 and ok.json()["head"]["name"] == "Tirzepatide"
    assert client.get("/indications/1/drug/99").status_code == 404
    assert client.get("/indications/5/drug/1").status_code == 404


# --- the card ------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["osimertinib", "amg510", "tozorakimab"])
def test_the_card_keeps_house_style(name):
    head, panes = DCV.card_html(load(name))
    text = text_of(head + "".join(m for _, m in panes))
    assert EM_DASH not in text
    assert not [w for w in BANNED if re.search(rf"\b{w}", text, re.I)]
    for label, _ in panes:
        assert label[:1].isupper() and label[1:] == label[1:].lower()      # sentence case


def test_a_marketed_drug_opens_on_four_panes_and_a_pipeline_drug_on_three():
    _, marketed = DCV.card_html(load("osimertinib"))
    _, pipeline = DCV.card_html(load("tozorakimab"))
    assert [p[0] for p in marketed] == ["Clinical", "Patient pool", "Valuation", "Commercial"]
    assert [p[0] for p in pipeline] == ["Clinical", "Patient pool", "Valuation"]


def test_the_figures_are_the_payloads_own():
    c = load("osimertinib")
    head, panes = DCV.card_html(c)
    text = text_of(head + "".join(m for _, m in panes))
    s, v = c["score"], c["valuation"][0]
    nat = c["commercial"]["access"]["prescribing"]["national"]
    for want in (f'rank {s["rank"]} of {s["of"]}', f'{s["overall"]:.0f}',
                 f'${v["per_share"]:,.2f}', f'${v["peak_revenue"]:,.0f}mm',
                 str(v["loe_year"]), f'{nat["prescribers"]:,}',
                 "Medicare Part D only", "gross of rebates, not revenue",
                 "Medicaid only, before rebates", c["commercial"]["access"]["attribution"]):
        assert want in text, want


def test_a_drug_with_no_model_says_no_free_data_rather_than_a_zero():
    c = load("amg510")
    head, panes = DCV.card_html(c)
    pane = dict(panes)
    assert c["model"] is None
    assert "no free data" in text_of(head)
    assert "$0.00" not in text_of(head) and "0%" not in text_of(head)
    assert "The book does not value this drug" in text_of(pane["Valuation"])
    assert "no patient build is on file" in text_of(pane["Patient pool"])


def test_the_patient_build_names_each_inputs_source_and_grade():
    _, panes = DCV.card_html(load("tozorakimab"))
    pool = text_of(dict(panes)["Patient pool"])
    for want in ("prevalence", "eligible share", "peak penetration", "list price",
                 "net price", "judgement", "published"):
        assert want in pool, want


# --- the click wiring -----------------------------------------------------------------
def _app_functions(*names):
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))
            and (getattr(n, "name", None) in names
                 or (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                     and n.targets[0].id in names))]
    space = {"html": html, "re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


def test_each_bubble_and_label_carries_its_drug():
    svg = charts.score_map([{"name": "Osimertinib", "ticker": "AZN", "x": 80, "y": 80,
                             "evidence": 70, "stage": "Marketed", "rank": 1, "id": 315},
                            {"name": "Other", "ticker": "MRK", "x": 40, "y": 40,
                             "evidence": 50, "stage": "Phase 3", "rank": 2}], 720, 480)
    assert re.search(r'<g class="sc-pt" data-drug="315" tabindex="0" role="button"', svg)
    assert 'class="sc-label" data-drug="315"' in svg
    assert svg.count("data-drug=") == 2                 # a point with no id stays plain


def test_each_table_row_carries_its_drug():
    space = _app_functions("html_escape", "_score_cell", "_plain_cell", "_stage_short",
                           "_STAGE_SHORT", "_score_rows")
    a = {"asset_id": 315, "name": "Osimertinib", "ticker": "AZN", "stage": "Marketed",
         "rank": 1, "rank_range": [1, 8], "overall": 78.0,
         "efficacy": {"score": 81.0}, "safety": {"score": 82.0}, "evidence": {"score": 72.0},
         "regimen": {}}
    rows = space["_score_rows"]([a], "AZN")
    assert re.search(r'<tr class="sc-mine" data-drug="315" tabindex="0"', rows)


def test_the_overview_listens_on_the_scorecard_and_opens_a_dialog():
    src = APP.read_text()
    body = src[src.index("def _drug_click("):src.index("def _stage_chip(")]
    assert 'scope: str = ".st-key-sc_map"' in body and "drugclick.drug_click(scope" in body
    assert "@st.dialog(" in body and "DCV.card_html(card)" in body
    assert '/indications/{pick}/drug/{asset_id}' in body
    over = src[src.index("def _landscape_overview("):src.index("def _drug_click(")]
    assert "_drug_click(api_base, pick," in over
    frame = (FRONTEND / "components" / "drugclick" / "index.html").read_text()
    assert "[data-drug]" in frame and "window.parent" in frame and "Streamlit.height(0)" in frame
    css = (FRONTEND / "assets" / "drugcard.css").read_text()
    assert ".st-key-sc_click, .st-key-cand_click { display: none !important; }" in css
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "a hex colour in drugcard.css"
    import theme
    assert ".st-key-sc_click" in theme.css()


def test_a_candidates_row_opens_the_card_too():
    src = APP.read_text()
    body = src[src.index("def _landscape_candidates("):src.index("def _landscape_efficacy(")]
    assert 'data-drug="{c["asset_id"]}" tabindex="0"' in body
    assert 'with st.container(key="land_cands"):' in body
    assert 'scope=".st-key-land_cands", box="cand_click"' in body
    assert "_landscape_candidates(cands, api_base, pick)" in src
    css = (FRONTEND / "assets" / "drugcard.css").read_text()
    assert ".st-key-land_cands tr[data-drug] { cursor: pointer; }" in css


# --- arms named by a code or a development name ----------------------------------------
@pytest.mark.parametrize("name, codes", [
    ("AZD9291 80 mg/40 mg", ["AZD9291", "AZD-9291", "AZD 9291"]),
    ("PF-08634404", ["PF08634404", "PF-08634404", "PF 08634404"]),
    ("LY3295668 Erbumine", ["LY3295668", "LY-3295668", "LY 3295668"]),
    ("Osimertinib Mesylate", []),
    ("NDA208065", []),                                            # an application number
    ("AZD9291 in combination with AZD6094", []),                 # a combination's code
    ("Pneumococcal Conjugate Vaccine (Diphtheria CRM197 Protein)", []),   # not its opener
])
def test_a_development_code_is_read_the_three_ways_a_registry_writes_it(name, codes):
    assert L._codes(name) == codes


def test_an_arm_named_by_a_code_or_development_name_is_the_drugs_arm(tmp_path, monkeypatch):
    path = _book(tmp_path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO asset_aliases (internal_code, asset_id, note)"
                 " VALUES ('LY3298176', 1, 'development code')")
    for gid, title, value in (("OG000", "Placebo", -1.0), ("OG001", "LY3298176 15 mg", -9.0)):
        conn.execute("INSERT INTO trial_result_outcomes (nct_id, outcome_index, outcome_type,"
                     " title, time_frame, unit, param_type, group_id, group_title, value,"
                     " n_analysed) VALUES ('NCT1', 1, 'PRIMARY', 'Change in Waist',"
                     " 'Week 72', 'cm', 'MEAN', ?, ?, ?, 100)", (gid, title, value))
    conn.commit()
    conn.close()
    monkeypatch.setattr(L, "_big_pharma_ids", lambda conn: {1, 2})
    monkeypatch.setattr(L, "_model_lines", lambda db_path, tickers, verdict_for=None: {})
    land = L.landscape(path, 1)
    row = next(r for g in land["endpoints"] for r in g["rows"] if r["arm"] == "LY3298176 15 mg")
    assert row["arm_is_drug"] and row["arm_names_drug"]
    assert DCV.arm_tag(row) == ""
    assert "other arm" in DCV.arm_tag({"arm": "Arm B"})
    assert "control arm" in DCV.arm_tag({"arm_is_control": True})
    # The Efficacy view tags its rows by the card's rule.
    assert 'DCV.arm_tag(r, "tag")' in APP.read_text()


# --- the card's charts ----------------------------------------------------------------
def _svgs(markup: str) -> list:
    return re.findall(r"<svg.*?</svg>", markup, flags=re.S)


def _sizes(svg: str) -> list:
    return [float(x) for x in re.findall(r'font-size="([\d.]+)"', svg)]


def test_the_card_draws_its_charts_where_the_data_supports_them():
    head, panes = DCV.card_html(load("osimertinib"))
    pane = dict(panes)
    clinical = _svgs(pane["Clinical"])
    assert any("effects against their comparators" in x for x in clinical)        # forest
    assert any("the drug's figures against its control" in x for x in clinical)   # safety
    assert any("line chart" in x for x in _svgs(pane["Valuation"]))               # path
    assert any("dated events" in x for x in _svgs(pane["Valuation"]))             # catalysts
    assert len(_svgs(pane["Commercial"])) == 3        # revenue, Part D patients and claims
    every = [x for m in pane.values() for x in _svgs(m)]
    assert min(min(_sizes(x)) for x in every) >= 9                                # legible
    for x in every:                                                               # drawn 1:1
        w = re.search(r'viewBox="0 0 (\d+) \d+" width="(\d+)"', x)
        assert w and w.group(1) == w.group(2) and int(w.group(1)) in (DCV.FULL, DCV.HALF)


def test_no_chart_where_a_figure_is_missing():
    _, panes = DCV.card_html(load("amg510"))
    pane = dict(panes)
    assert _svgs(pane["Valuation"]) == [] and _svgs(pane["Patient pool"]) == []
    # A drug that does not share the pool gets no share chart; one that does, does.
    c = load("sacituzumab_tirumotecan")
    assert c["pool_path"]["pooled"] and _svgs(dict(DCV.card_html(c)[1])["Patient pool"])
    c["pool_path"]["pooled"] = False
    assert not _svgs(dict(DCV.card_html(c)[1])["Patient pool"])


def test_a_pipeline_drugs_path_is_drawn_risked_beside_unrisked():
    c = load("sacituzumab_tirumotecan")
    path = c["paths"][0]
    assert path["pos"] < 1
    assert path["risked"] == pytest.approx([v * path["pos"] for v in path["revenue"]])
    svg = _svgs(dict(DCV.card_html(c)[1])["Valuation"])[0]
    assert ">risked<" in svg and ">unrisked<" in svg


def test_the_chart_primitives_never_draw_a_missing_value():
    assert charts.forest([{"label": "a", "value": None}], 500) == ""
    hr = charts.forest([{"label": "PFS", "value": 0.46, "lo": 0.28, "hi": 0.75}], 700,
                       ratio=True)
    assert "0.46 (0.28 to 0.75)" in hr
    one = charts.forest([{"label": "x", "value": 3.0}], 700)      # no interval: point alone
    assert "to" not in re.sub(r"<title>.*?</title>", "", one).split("x</text>")[-1]
    bars = charts.paired_bars([{"label": "deaths", "value": 46.0, "reference": None}])
    assert "no control figure" in bars
    strip = charts.date_strip([{"date": None, "label": "undated"},
                               {"date": "2027-03-01", "label": "readout"}], "2026-10-07")
    assert "undated" not in strip and "readout" in strip
    assert charts.date_strip([], "2026-10-07") == ""


def test_the_pool_figure_names_a_years_diagnoses():
    c = load("sacituzumab_tirumotecan")
    ind = c["pool"]["indication"]
    assert ind["pool"] > 0 and ind["per_year"] and ind["pooled"] <= ind["claimants"]
    text = text_of(dict(DCV.card_html(c)[1])["Patient pool"])
    assert DCV.pool_size(ind["pool"]) in text and "a year" in text
