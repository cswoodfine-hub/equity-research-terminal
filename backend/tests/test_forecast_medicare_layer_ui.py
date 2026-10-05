"""The Forecast tab's Medicare layer (docs/design/medicare-demand-split.md).

The builders live in the Streamlit script, which runs the whole app on import, so they
are read out of its source by name and run on payloads the split returned for real
assets on a copy of the book (``fixtures/medicare_split``): BMY's Eliquis, Pfizer's
Eliquis held on BMY's record, Amgen's Prolia in two parts, Tremfya with a container
change and Naglazyme with no patient counts. Then the tab itself through AppTest,
skipped when the API is not up.
"""

from __future__ import annotations

import ast
import copy
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "streamlit_app.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "medicare_split"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

from components import charts  # noqa: E402
import theme  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
SHARED = ("html_escape",)


def builders():
    """The Medicare builders and what they call, compiled out of the app's source."""
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep, names = [], set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        else:
            continue
        if name.startswith(("_mc_", "_MC_", "_medicare_")) or name in SHARED:
            keep.append(node)
            names.add(name)
    assert "_medicare_layer_html" in names
    space = {"html": html, "re": re, "CH": charts, "T": theme}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


@pytest.fixture(scope="module")
def view():
    return builders()


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def text_of(markup: str) -> str:
    no_svg = re.sub(r"<svg.*?</svg>", " ", markup, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", no_svg))).strip()


def house_style(text: str) -> None:
    assert EM_DASH not in text, text
    low = text.lower()
    assert not [w for w in BANNED if re.search(rf"\b{w}\b", low)], text


# --- the builder -----------------------------------------------------------------------
def test_part_d_names_fills_and_part_b_names_claims(view):
    d = view["_medicare_layer_html"](load("asset_bmy_eliquis"))
    assert "Fills per patient" in d and "Cost per fill" in d
    b = view["_medicare_layer_html"](load("asset_amgn_prolia"))
    assert "Claims per patient" in b and "Cost per claim" in b
    assert "Fills per patient" in b                       # Prolia's Part D table


def test_the_layer_leads_with_the_label_and_the_sentence(view):
    out = view["_medicare_layer_html"](load("asset_bmy_eliquis"))
    words = text_of(out)
    assert words.startswith("Medicare only.")
    assert "Medicare patients on Eliquis rose 12.7% in 2024" in words
    assert out.index("mc-label") < out.index("mc-sentence") < out.index("<svg")
    assert out.count("<svg") == 1
    assert "<table" in out and out.index("<svg") < out.index("<table")


def test_the_copy_keeps_house_style(view):
    for name in ("asset_bmy_eliquis", "asset_amgn_prolia", "asset_pfe_eliquis",
                 "asset_bmrn_naglazyme", "asset_jnj_tremfya"):
        house_style(text_of(view["_medicare_layer_html"](load(name))))


def test_a_held_brand_names_the_record_it_is_read_from(view):
    out = text_of(view["_medicare_layer_html"](load("asset_pfe_eliquis")))
    assert "Medicare reports the brand, held on BMY's record" in out
    own = text_of(view["_medicare_layer_html"](load("asset_bmy_eliquis")))
    assert "held on" not in own
    assert "The brand is also modelled by PFE" in own


def test_a_step_with_no_patient_count_shows_two_factors_and_its_note(view):
    split = load("asset_bmrn_naglazyme")
    out = view["_medicare_layer_html"](split)
    assert "no patient count" in out
    assert "CMS gives no patient count for one of the two years" in text_of(out)
    assert re.search(r"<sup>\d+</sup>", out)
    assert 'class="seg seg-claims' in out and 'class="seg seg-patients' not in out


def test_the_model_row_only_when_the_model_has_a_growth_rate(view):
    split = load("asset_bmy_eliquis")
    out = text_of(view["_medicare_layer_html"](split))
    assert "Model from FY2025: growth +18.9% a year fading to 0.0% over 5 years" in out
    bare = copy.deepcopy(split)
    bare["beside"]["model_growth"] = None
    assert "Model from" not in text_of(view["_medicare_layer_html"](bare))


def test_two_material_parts_draw_two_charts_and_never_add_patients(view):
    out = view["_medicare_layer_html"](load("asset_amgn_prolia"))
    assert out.count("<svg") == 2
    assert "Patients are not added across parts" in text_of(out)


def test_a_container_change_is_hatched_and_footnoted(view):
    out = view["_medicare_layer_html"](load("asset_jnj_tremfya"))
    assert 'class="nlfl"' in out
    assert "CMS changed the containers it lists" in text_of(out)


def test_no_series_draws_nothing(view):
    assert view["_medicare_layer_html"]({"ok": False, "reason": "not in the CMS files"}) == ""
    assert view["_medicare_layer_html"](None) == ""


def test_missing_figures_are_dots_never_zero(view):
    assert view["_mc_pct"](None) == "·" and view["_mc_pct"](0.0) == "0.0%"
    assert view["_mc_pct"](-0.025) == "−2.5%" and view["_mc_pct"](0.137) == "+13.7%"


# --- the tab, through AppTest ----------------------------------------------------------
# Opt in with ER_TOOL_APPTEST=1 against a running API: a plain test run never calls it.
API = os.environ.get("ER_TOOL_API", "http://localhost:8000")


def api_up() -> bool:
    if os.environ.get("ER_TOOL_APPTEST") != "1":
        return False
    try:
        with urllib.request.urlopen(API + "/health", timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False


@pytest.mark.skipif(not api_up(), reason="ER_TOOL_APPTEST is unset or the API is down")
def test_the_forecast_tab_shows_a_medicare_layer_for_eliquis_only():
    from streamlit.testing.v1 import AppTest

    def tabs_for(asset_id):
        at = AppTest.from_file(str(APP), default_timeout=180)
        at.query_params["ticker"] = "BMY"
        at.session_state["fc_pick_BMY"] = asset_id
        at.run()
        return [t.label for t in at.tabs]

    assert "Medicare" in tabs_for(198)                  # Eliquis
    with urllib.request.urlopen(API + "/companies/BMY/forecast", timeout=60) as resp:
        pickable = json.loads(resp.read())["pickable"]
    for a in pickable:
        with urllib.request.urlopen(API + f"/companies/BMY/forecast/{a['asset_id']}/demand",
                                    timeout=60) as resp:
            if not json.loads(resp.read())["ok"]:
                assert "Medicare" not in tabs_for(a["asset_id"])
                break
