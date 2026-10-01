"""The Comps tab's wiring, driven server-side through Streamlit's AppTest.

The Companies view is one custom component, so what Python owns is small and exact: the
sub-tabs around it, the args it receives (the payload with its scorecard, and the company
map Python draws for the frame), and the one round trip it makes back, a new focal
company. Revision 4 of the frame (docs/design/company-scorecard.md 5.2, 6.2, 7.2). The args are read from the component's proto, which is the exact JSON the
iframe receives, and parsed strictly: Python's json accepts NaN, the browser's does not.

Needs the API on localhost:8000 (or ER_API_BASE); the app tests are skipped when it is
not up, so the suite stays green on a machine that has not started the server. The
wrapper's own checks at the foot need nothing running.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "streamlit_app.py"
RESEARCH = FRONTEND / "assets" / "research.css"
COMPONENT = "components.compsval.compsval"
BIOTECH = "ALNY"   # a biotech-engine company: no Indications view on its Comps tab
SCORECARD = (pathlib.Path(__file__).resolve().parent / "fixtures" / "company_score"
             / "sample_scorecard.json")


def _api_up() -> bool:
    base = os.getenv("ER_API_BASE", "http://localhost:8000")
    try:
        with urllib.request.urlopen(base + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


needs_api = pytest.mark.skipif(not _api_up(), reason="API not running on 8000")


def _patch_button_group_serialisation():
    """Work around a Streamlit AppTest defect, not an app one (the same patch as
    test_forecast_tab_ui.py).

    ButtonGroup.indices iterates ``self.value``, and for a single-select
    segmented_control the session value is a plain string, so it iterates characters
    and every rerun dies on the first segmented control in the app. Rebuilt here to
    treat a scalar as one value and to compare against the option protos' content,
    which is what the real frontend sends.
    """
    from streamlit.testing.v1 import element_tree

    def indices(self):
        values = self.value
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            values = [values]
        labels = [getattr(o, "content", o) for o in self.options]
        out = []
        for v in values:
            label = self.format_func(v) if self.format_func else v
            label = getattr(label, "content", label)
            if label in labels:
                out.append(labels.index(label))
        return out

    element_tree.ButtonGroup.indices = property(indices)


def _open(ticker: str):
    from streamlit.testing.v1 import AppTest

    _patch_button_group_serialisation()
    if str(FRONTEND) not in sys.path:
        sys.path.insert(0, str(FRONTEND))
    test = AppTest.from_file(str(APP), default_timeout=180)
    test.query_params["ticker"] = ticker
    test.run()
    return test


@pytest.fixture(scope="module")
def pharma_app():
    return _open("LLY")


@pytest.fixture(scope="module")
def biotech_app():
    return _open(BIOTECH)


def _direct_tabs(block) -> list:
    """The labels of the tabs directly under ``block``: its own st.tabs, not the tabs
    nested inside those (the indication landscape has views of its own)."""
    from streamlit.testing.v1.element_tree import Tab

    found = []

    def walk(node):
        for child in getattr(node, "children", {}).values():
            if isinstance(child, Tab):
                found.append(child.label)
            else:
                walk(child)

    walk(block)
    return found


def _comps_subtabs(app) -> list:
    comps = [t for t in app.tabs if t.label == "Comps"]
    assert len(comps) == 1, "no Comps tab"
    return _direct_tabs(comps[0])


def _instances(app) -> list:
    return [n for n in app.get("component_instance")
            if n.proto.component_name == COMPONENT]


def _args_by_mode(app) -> dict:
    """Every comps frame's args by mode, parsed strictly. Revision 3 of the design draws two:
    the full view on the Comps tab and the bridge alone on the Forecast tab."""
    def fail(constant):
        pytest.fail(f"non-JSON {constant} in the comps args")

    out: dict = {}
    for node in _instances(app):
        args = json.loads(node.proto.json_args, parse_constant=fail)
        mode = args.get("mode") or "full"
        assert mode not in out, f"two {mode} frames"
        out[mode] = args
    return out


def _strict_args(app) -> dict:
    by_mode = _args_by_mode(app)
    assert "full" in by_mode, f"no full comps frame among {sorted(by_mode)}"
    return by_mode["full"]


# --- 1. The sub-tabs ----------------------------------------------------------


@needs_api
def test_the_pharma_comps_tab_opens_on_companies(pharma_app):
    assert not pharma_app.exception
    assert _comps_subtabs(pharma_app) == ["Companies", "Indications", "Pipelines"]


@needs_api
def test_a_biotech_comps_tab_has_no_indications_view(biotech_app):
    assert not biotech_app.exception
    assert biotech_app.session_state["company_pick"] == BIOTECH
    assert _comps_subtabs(biotech_app) == ["Companies", "Pipelines"]


@needs_api
def test_head_to_head_and_screen_are_gone(pharma_app, biotech_app):
    for app in (pharma_app, biotech_app):
        labels = [t.label for t in app.tabs]
        assert "Head to head" not in labels and "Screen" not in labels
        body = " ".join(str(m.value) for m in app.markdown)
        assert "Head to head" not in body and 'class="h2h' not in body


# --- 2. The component and its args ----------------------------------------------


@needs_api
def test_one_component_with_strict_json_args(pharma_app):
    args = _strict_args(pharma_app)
    assert args["focal"] == pharma_app.session_state["company_pick"] == "LLY"
    assert args["engine"] == "pharma"
    assert args["live"] is True
    assert args["default"] is None and args["key"] == "compsval"
    assert len(args["payload"]["companies"]) == 70
    assert isinstance(args["digest"], str) and len(args["digest"]) == 12


@needs_api
def test_the_tokens_are_the_terminals_palette_and_not_the_filed_phase(pharma_app):
    tokens = _strict_args(pharma_app)["tokens"]
    # Selection and focus are derived from the palette in research.css, so the view wears
    # the colours of every other tab and carries no colour of its own.
    assert "active" not in tokens and "active-wash" not in tokens
    assert "up" in tokens and "text" in tokens
    assert "phase-filed" not in tokens
    for name in ("ground", "panel", "rule-faint", "font-ui-narrow", "phase-approved"):
        assert name in tokens
    assert (tokens["space"], tokens["radius"], tokens["radius-small"]) == (
        "8px", "0px", "2px")


@needs_api
def test_the_shared_css_is_the_research_stylesheet(pharma_app):
    assert _strict_args(pharma_app)["shared_css"] == RESEARCH.read_text()


@needs_api
def test_the_top_bar_names_the_exchange(pharma_app):
    """The identity line read a key the company list does not carry, so the exchange
    never printed. Lilly lists on the NYSE."""
    body = " ".join(str(m.value) for m in pharma_app.markdown)
    exchange = next(
        (c["primary_exchange"] for c in _companies() if c["ticker"] == "LLY"), None)
    if not exchange:
        pytest.skip("no primary exchange on file for LLY")
    assert f'<span class="meta">{exchange}' in body


def _companies() -> list:
    base = os.getenv("ER_API_BASE", "http://localhost:8000")
    with urllib.request.urlopen(base + "/companies", timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, list) else data.get("companies", [])


# --- 3. The focal-company round trip --------------------------------------------


@pytest.fixture(scope="module")
def focus_app():
    return _open("LLY")


@needs_api
def test_a_focus_action_moves_the_whole_page_once(focus_app):
    app = focus_app
    app.session_state["compsval"] = {"action": "focus", "ticker": "AZN", "nonce": 1}
    app.run()
    assert not app.exception
    assert app.session_state["company_pick"] == "AZN"
    assert _strict_args(app)["focal"] == "AZN"

    # The component's value persists after the click. The same nonce again, after the
    # analyst has moved back to Lilly in the top bar, must not drag the page to AZN.
    app.session_state["company_pick"] = "LLY"
    app.session_state["compsval"] = {"action": "focus", "ticker": "AZN", "nonce": 1}
    app.run()
    assert not app.exception
    assert app.session_state["company_pick"] == "LLY"


@needs_api
def test_a_focal_company_from_another_engine_opens_that_engine(focus_app):
    app = focus_app
    app.session_state["compsval"] = {"action": "focus", "ticker": BIOTECH, "nonce": 2}
    app.run()
    assert not app.exception
    assert app.session_state["company_pick"] == BIOTECH
    assert app.session_state["engine"] == "biotech"
    assert _comps_subtabs(app) == ["Companies", "Pipelines"]
    assert _strict_args(app)["engine"] == "biotech"


@needs_api
def test_an_unknown_ticker_is_dropped(focus_app):
    app = focus_app
    before = app.session_state["company_pick"]
    app.session_state["compsval"] = {"action": "focus", "ticker": "NOPE", "nonce": 3}
    app.run()
    assert not app.exception
    assert app.session_state["company_pick"] == before


# --- The wrapper, with nothing running ------------------------------------------


def _wrapper():
    if str(FRONTEND) not in sys.path:
        sys.path.insert(0, str(FRONTEND))
    from components import compsval

    return compsval


def test_jsonable_nulls_what_json_cannot_carry():
    compsval = _wrapper()
    clean = compsval._jsonable({"a": float("nan"), "b": [1, 2.5, float("inf")],
                                "c": (float("-inf"), None, "x"), 7: True})
    assert clean == {"a": None, "b": [1, 2.5, None], "c": [None, None, "x"], "7": True}
    json.dumps(clean, allow_nan=False)


def test_jsonable_unwraps_numpy_scalars():
    np = pytest.importorskip("numpy")
    compsval = _wrapper()
    clean = compsval._jsonable({"n": np.int64(3), "f": np.float64("nan"),
                                "g": np.float32(1.5)})
    assert clean == {"n": 3, "f": None, "g": 1.5}
    assert type(clean["n"]) is int


def test_the_digest_fails_loud_on_a_non_finite_number():
    compsval = _wrapper()
    with pytest.raises(ValueError):
        compsval._digest({"x": math.nan})
    assert compsval._digest({"a": 1, "b": 2}) == compsval._digest({"b": 2, "a": 1})


def test_the_wrapper_passes_the_contract_args(monkeypatch):
    compsval = _wrapper()
    captured = {}
    monkeypatch.setattr(compsval, "_component", lambda **kw: captured.update(kw))
    compsval.comps_valuation({"companies": [{"x": float("nan")}]}, focal="AZN",
                             engine="", tokens={"active": "a"}, live=False)
    assert captured["payload"] == {"companies": [{"x": None}]}
    assert captured["focal"] == "AZN" and captured["engine"] == ""
    assert captured["live"] is False and captured["height"] == 900
    assert captured["key"] == "compsval" and captured["default"] is None
    assert captured["tab_index"] == 0
    assert captured["digest"] == compsval._digest(captured["payload"])


# --- Revision 3: the bridge on the Forecast tab -----------------------------------


@needs_api
def test_the_forecast_tab_draws_the_bridge_alone(pharma_app):
    by_mode = _args_by_mode(pharma_app)
    assert set(by_mode) == {"full", "bridge"}
    bridge = by_mode["bridge"]
    assert bridge["focal"] == by_mode["full"]["focal"]
    assert "context" not in bridge                        # the bridge reads no catalysts
    assert all("detail" not in c for c in bridge["payload"]["companies"])


@needs_api
def test_the_full_view_carries_the_scorecard_and_the_company_map(pharma_app):
    """Revision 4 (6.2): the payload carries the scorecard, the frame gets the company map
    Python drew for the focal company's cohort, and no catalyst context, since Drivers and
    risks moved to the Catalysts tab."""
    args = _strict_args(pharma_app)
    assert "context" not in args and "context_digest" not in args
    scorecard = args["payload"]["scorecard"]
    assert scorecard["schema"] == 2 and not scorecard.get("error")
    assert args["focal"] in scorecard["companies"]
    svg = args["chart_svg"]
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    cohort = scorecard["companies"][args["focal"]]["cohort"]
    charted = [t for t, r in scorecard["companies"].items()
               if r["cohort"] == cohort and r.get("chart") and r.get("rank") is not None]
    assert svg.count('class="cm-pt"') == len(charted)
    assert f'data-ticker="{args["focal"]}"' in svg
    assert re.fullmatch(r"[0-9a-f]{12}", args["chart_digest"])
    bridge = _args_by_mode(pharma_app)["bridge"]
    assert "scorecard" not in bridge["payload"] and "chart_svg" not in bridge


# --- Revision 4: the company map and its points, with nothing running ------------------------


def _charts():
    if str(FRONTEND) not in sys.path:
        sys.path.insert(0, str(FRONTEND))
    from components import charts as CH
    from components import tokens as TK

    return CH, TK


def _points_fn():
    """``_company_map_points`` and its helper, read out of the app script and compiled alone:
    the script itself draws the page when imported."""
    tree = ast.parse(APP.read_text())
    wanted = {"_cm_ordinal", "_company_map_points"}
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in nodes} == wanted
    ns = {"dt": dt}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP), "exec"), ns)
    return ns["_company_map_points"]


@pytest.fixture(scope="module")
def sample():
    return json.loads(SCORECARD.read_text())


def test_the_map_points_are_the_cohorts_scored_companies(sample):
    points = _points_fn()
    azn = points(sample, "AZN")
    assert [p["ticker"] for p in azn] == [t for t, r in sample["companies"].items()
                                         if r["cohort"] == "big_pharma"]
    assert len(azn) == 18
    one = next(p for p in azn if p["ticker"] == "AZN")
    chart = sample["companies"]["AZN"]["chart"]
    assert (one["x"], one["y"], one["size"], one["complete"], one["rank"]) == (
        chart["x"], chart["y"], chart["size"], True, 7)
    assert one["tip"] == ("AZN AstraZeneca PLC. Company score 58, 7th of 18, range 2–11. "
                          "Value 46. Growth 77, profitability 31, balance sheet 55, "
                          "pipeline 65, durability 62.")
    assert one["aria"] == "AZN, rank 7, range 2 to 11, company score 58, value 46"
    rog = next(p for p in azn if p["ticker"] == "ROG")
    assert rog["complete"] is False and rog["tip"].endswith("(on 4 of 5 pillars).")
    # The commercial cohort: the company not ranked and those with no value measure have no
    # bubble; the clinical cohort is drawn whole.
    com = {p["ticker"] for p in points(sample, "BNTX")}
    assert "ADAPY" not in com and not com & {x["ticker"] for x in
                                             sample["cohorts"]["commercial"]["not_on_chart"]}
    assert len(points(sample, "CRSP")) == 30
    # A failed scorecard or an unknown company gives no points.
    assert points({"error": "boom", "companies": {}, "cohorts": {}}, "AZN") == []
    assert points(sample, "NOPE") == []
    # A price date behind the cohort's latest is named.
    records = [{"ticker": t, "market": {"price_as_of": "2026-09-30"}} for t in sample["companies"]]
    records[[r["ticker"] for r in records].index("PFE")]["market"]["price_as_of"] = "2026-09-29"
    pfe = next(p for p in points(sample, "AZN", records) if p["ticker"] == "PFE")
    assert pfe["tip"].endswith("Price of 29 Sep 2026.")


def test_company_map_draws_one_clickable_group_a_company(sample):
    CH, TK = _charts()
    pts = _points_fn()(sample, "AZN")
    svg = CH.company_map(pts, open_ticker="AZN")
    assert svg.startswith('<svg viewBox="0 0 760 480"')
    groups = re.findall(r'<g class="cm-pt" data-ticker="([A-Z]+)" tabindex="0" role="button"', svg)
    assert sorted(groups) == sorted(p["ticker"] for p in pts)
    # Largest bubble first, the open company last, on top.
    sizes = {p["ticker"]: p["size"] for p in pts}
    others = [t for t in groups if t != "AZN"]
    assert others == sorted(others, key=lambda t: -sizes[t])
    assert groups[-1] == "AZN"
    # Every big pharma ticker is labelled by default, a cohort of 20 or fewer.
    assert sorted(re.findall(r'class="cm-label" data-ticker="([A-Z]+)"', svg)) == sorted(groups)
    # The open company in UP with a ground gap ring; the others muted.
    azn = svg[svg.index('data-ticker="AZN" tabindex'):]
    azn = azn[:azn.index("</g>")]
    assert f'stroke="{TK.UP}"' in azn and f'stroke="{TK.GROUND}" stroke-width="2.4"' in azn
    lly = svg[svg.index('data-ticker="LLY" tabindex'):]
    lly = lly[:lly.index("</g>")]
    assert f'stroke="{TK.MUTED}"' in lly and TK.UP not in lly
    # ROG misses a pillar: hollow. A complete bubble is solid.
    rog = svg[svg.index('data-ticker="ROG" tabindex'):]
    assert 'class="cm-dot"' in rog[:rog.index("</g>")] and 'fill="none" fill-opacity="1"' in rog[:rog.index("</g>")]
    assert 'fill-opacity="0.9"' in lly
    # The ring the frame shows, hidden until then; the rank inside each bubble.
    assert svg.count('class="cm-ring"') == len(groups) and 'opacity="0"' in lly
    assert '>7</text>' in azn
    # Four corner captions and the axis titles; no line beyond the grid's ten but the leaders.
    for text in ("stronger, lower multiples", "weaker, lower multiples", "stronger, higher multiples",
                 "weaker, higher multiples", "company score  →  stronger",
                 "value score  →  lower multiples", "every pillar scored", "some pillars missing",
                 "bigger: larger market cap"):
        assert f">{text}</text>" in svg, text
    assert svg.count("<line") - svg.count('<line class="cm-leader"') == 10
    # Colours from the tokens only, and none of them blue or red.
    used = set(re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]+)"', svg))
    assert used <= {TK.UP, TK.MUTED, TK.TEXT, TK.GROUND, TK.PANEL, TK.RULE, TK.RULE_STRONG}, used
    assert CH.company_map([]) == ""


def test_company_map_caps_the_labels_in_a_larger_cohort(sample):
    CH, _ = _charts()
    pts = _points_fn()(sample, "CRSP")
    svg = CH.company_map(pts, open_ticker="CRSP")
    labels = re.findall(r'class="cm-label" data-ticker="([A-Z]+)"', svg)
    assert len(labels) <= 12 and "CRSP" in labels
    top5 = [p["ticker"] for p in sorted(pts, key=lambda p: p["rank"])[:5]]
    assert set(top5) <= set(labels)
    assert svg.count('class="cm-pt"') == 30


def test_the_score_map_is_drawn_by_the_shared_routine_unchanged():
    CH, _ = _charts()
    pts = [{"name": "Alpha", "ticker": "AAA", "x": 80, "y": 70, "evidence": 60, "stage": "Marketed",
            "boxed": True, "rank": 1, "tip": "Alpha"},
           {"name": "Beta", "ticker": "BBB", "x": 30, "y": 20, "evidence": None, "stage": "Phase 2",
            "rank": 2, "nosize": True}]
    svg = CH.score_map(pts, highlight="AAA")
    assert 'class="cm-' not in svg and "<g " not in svg
    assert svg.count("<line") == 10 + svg.count("stroke-width=\"0.6\"")
    assert ">stronger and safer</text>" in svg and "† size not compared" in svg


def test_the_wrapper_passes_the_chart_and_strips_the_bridge(monkeypatch):
    compsval = _wrapper()
    assert compsval.REVISION == 4
    captured = {}
    monkeypatch.setattr(compsval, "_component", lambda **kw: captured.update(kw))
    payload = {"companies": [{"ticker": "AZN", "detail": {"x": 1}}], "scorecard": {"schema": 2}}
    compsval.comps_valuation(payload, focal="AZN", engine="pharma", tokens={}, live=True,
                             chart_svg="<svg></svg>")
    assert captured["chart_svg"] == "<svg></svg>"
    assert captured["chart_digest"] == compsval._svg_digest("<svg></svg>")
    assert len(captured["chart_digest"]) == 12
    assert captured["payload"]["scorecard"] == {"schema": 2}
    captured.clear()
    compsval.comps_valuation(payload, focal="AZN", engine="pharma", tokens={}, live=True)
    assert captured["chart_svg"] == "" and len(captured["chart_digest"]) == 12
    captured.clear()
    compsval.comps_valuation(payload, focal="AZN", engine="pharma", tokens={}, live=True,
                             mode="bridge", chart_svg="<svg></svg>")
    assert "chart_svg" not in captured and "chart_digest" not in captured
    assert "scorecard" not in captured["payload"]
    assert captured["payload"]["companies"] == [{"ticker": "AZN"}]
    assert "context" not in captured
