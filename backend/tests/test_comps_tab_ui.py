"""The Comps tab's wiring, driven server-side through Streamlit's AppTest.

The valuation view is one custom component, so what Python owns is small and exact: the
sub-tabs around it, the args it receives, and the one round trip it makes back, a new
focal company. The args are read from the component's proto, which is the exact JSON the
iframe receives, and parsed strictly: Python's json accepts NaN, the browser's does not.

Needs the API on localhost:8000 (or ER_API_BASE); the app tests are skipped when it is
not up, so the suite stays green on a machine that has not started the server. The
wrapper's own checks at the foot need nothing running.
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import sys
import urllib.error
import urllib.request

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
APP = FRONTEND / "streamlit_app.py"
RESEARCH = FRONTEND / "assets" / "research.css"
COMPONENT = "components.compsval.compsval"
BIOTECH = "ALNY"   # a biotech-engine company: no Indications view on its Comps tab


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


def _strict_args(app) -> dict:
    nodes = _instances(app)
    assert len(nodes) == 1, f"{len(nodes)} {COMPONENT} instances"

    def fail(constant):
        pytest.fail(f"non-JSON {constant} in the comps args")

    return json.loads(nodes[0].proto.json_args, parse_constant=fail)


# --- 1. The sub-tabs ----------------------------------------------------------


@needs_api
def test_the_pharma_comps_tab_opens_on_valuation(pharma_app):
    assert not pharma_app.exception
    assert _comps_subtabs(pharma_app) == ["Valuation", "Indications", "Pipelines"]


@needs_api
def test_a_biotech_comps_tab_has_no_indications_view(biotech_app):
    assert not biotech_app.exception
    assert biotech_app.session_state["company_pick"] == BIOTECH
    assert _comps_subtabs(biotech_app) == ["Valuation", "Pipelines"]


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
def test_the_tokens_carry_the_active_colour_and_not_the_filed_phase(pharma_app):
    tokens = _strict_args(pharma_app)["tokens"]
    assert "active" in tokens and "active-wash" in tokens
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
    assert _comps_subtabs(app) == ["Valuation", "Pipelines"]
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
