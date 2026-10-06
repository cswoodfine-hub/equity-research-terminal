"""The fact profile's payer row: Part D prescribing, Part D plan coverage and Medicaid
prescriptions (backend/payer_access.py).

The builders live in the Streamlit script, which runs the whole app on import, so they
are read out of its source by name and run on what the reader returned for real assets
on a copy of the book (``fixtures/payer_access/asset_*.json``): Eliquis on BMS's page,
Keytruda (Part B), Shingrix (a vaccine), Verzenio (a reused product code), Comirnaty
(Part B only) and Eliquis Sprinkle (no RxNorm code yet).
"""

from __future__ import annotations

import ast
import copy
import html
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "streamlit_app.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "payer_access"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

from components import charts  # noqa: E402
import theme  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
SHARED = ("html_escape",)
NAMES = ("eliquis", "keytruda", "shingrix", "verzenio", "comirnaty", "eliquis_sprinkle")
FILES = {"eliquis": "asset_bmy_eliquis", "keytruda": "asset_mrk_keytruda",
         "shingrix": "asset_gsk_shingrix", "verzenio": "asset_lly_verzenio",
         "comirnaty": "asset_pfe_comirnaty", "eliquis_sprinkle": "asset_bmy_eliquis_sprinkle"}


@pytest.fixture(scope="module")
def view():
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
        if name.startswith(("_payer_", "_PAYER_")) or name in SHARED:
            keep.append(node)
            names.add(name)
    assert {"_payer_prescribing_html", "_payer_formulary_html", "_payer_medicaid_html",
            "_payer_detail_html", "_payer_byline", "_payer_row"} <= names
    space = {"html": html, "re": re, "CH": charts, "T": theme}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{FILES[name]}.json").read_text())


def text_of(markup: str) -> str:
    no_svg = re.sub(r"<svg.*?</svg>", " ", markup, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", no_svg))).strip()


def house_style(text: str) -> None:
    assert EM_DASH not in text, text
    low = text.lower()
    assert not [w for w in BANNED if re.search(rf"\b{w}\b", low)], text


def _panels(view, access) -> dict:
    return {key: view[f"_payer_{key}_html"](access)
            for key in ("prescribing", "formulary", "medicaid")}


# --- each panel leads with a figure and one picture -----------------------------------
def test_eliquis_prescribing_leads_with_prescribers_and_the_decile_strip(view):
    out = view["_payer_prescribing_html"](load("eliquis"))
    words = text_of(out)
    assert words.startswith("Medicare Part D only, 2024 556,431 prescribers, 24,054,695 claims")
    assert "Top 10% of the file population write 49% of its claims" in words
    assert out.count("<svg") == 1 and "prescribers with 11 or more claims" in words
    assert ("Days supplied cover 72% of each beneficiary's year. A proxy, not a PDC"
            in words)


def test_a_proxy_above_one_is_printed_as_it_is_and_explained(view):
    access = copy.deepcopy(load("eliquis"))
    access["prescribing"]["days_covered"]["value"] = 1.53      # Fabrazyme, every 2 weeks
    words = text_of(view["_payer_prescribing_html"](access))
    assert "1.53 times each beneficiary's year" in words
    assert "given more often than monthly" in words


def test_a_vaccine_says_the_proxy_does_not_apply(view):
    words = text_of(view["_payer_prescribing_html"](load("shingrix")))
    assert "says nothing about adherence" in words
    assert "Days supplied cover" not in words


def test_formulary_reads_listing_restrictions_and_the_tier_mix(view):
    out = view["_payer_formulary_html"](load("eliquis"))
    words = text_of(out)
    assert words.startswith("Medicare Part D plans only, Sep 2026 release, contract year 2026 "
                            "Listed on 328 of 328 formularies")
    assert "Prior authorisation on 0, step therapy on 0" in words
    assert out.count("<svg") == 1 and 'aria-label="tier mix"' in out


def test_medicaid_leads_with_the_latest_quarter_and_its_floor(view):
    out = view["_payer_medicaid_html"](load("eliquis"))
    words = text_of(out)
    assert words.startswith("Medicaid only, before rebates At least 556,404 prescriptions in "
                            "2025 Q4, up 6.9% on a year")
    assert "Gross of Medicaid rebates, so this is volume, not revenue." in words
    assert out.count("<svg") == 1


# --- empty states print the reason, never a placeholder -------------------------------
def test_a_part_b_brand_names_part_b_not_no_free_data(view):
    key = _panels(view, load("keytruda"))
    assert "Part D plans do not list it" in text_of(key["formulary"])
    assert "Part B is 98% of Medicare's spend" in text_of(key["prescribing"])
    only = _panels(view, load("comirnaty"))
    reason = "Given in the clinic under Part B, so the Part D files do not carry it"
    assert text_of(only["prescribing"]) == f"Medicare Part D only {reason}"
    assert text_of(only["formulary"]) == f"Medicare Part D plans only {reason}"
    # Nothing lists it, so no restriction count reads as an open door.
    assert "Prior authorisation on" not in text_of(key["formulary"])
    for markup in (*key.values(), *only.values()):
        assert "no free data" not in text_of(markup)


def test_empty_states_print_why_empty_verbatim(view):
    access = load("eliquis_sprinkle")
    panels = _panels(view, access)
    for key, markup in panels.items():
        scope = view["_PAYER_SCOPE"][key]
        assert text_of(markup) == f'{scope} {access["why_empty"][key]}'
        assert 'class="state"' in markup


def test_the_section_chip_is_short_and_the_scope_is_the_first_line(view):
    eliquis = load("eliquis")
    chips = [view["_payer_chip"](eliquis, k) for k in ("prescribing", "formulary", "medicaid")]
    assert chips == ["2024", "2026-09 release", "before rebates"]
    assert max(len(c) for c in chips) <= 16
    assert view["_payer_chip"](load("comirnaty"), "formulary") == "Medicare"
    for key in ("prescribing", "formulary", "medicaid"):
        assert view[f"_payer_{key}_html"](eliquis).startswith('<div class="byline pa-scope">')


# --- the label, the detail and the byline ---------------------------------------------
def test_a_co_marketed_brand_says_whose_totals_these_are(view):
    line = text_of(view["_payer_co_line"](load("eliquis")))
    assert line == "Brand totals, not this company's share. The same brand shows on PFE's page."
    assert view["_payer_co_line"](load("keytruda")) == ""


def test_the_detail_holds_the_figures_behind_each_lead(view):
    words = text_of(view["_payer_detail_html"](load("eliquis")))
    for phrase in ("Part D prescribing, 2024", "file prescribers, 11 or more claims",
                   "Prescriber specialty, share of file claims", "Internal Medicine",
                   "MA-PD plans: listing, PA, ST, QL", "selected for Medicare negotiation",
                   "Medicaid prescriptions by year", "2025 at least 2,188,265, +6.8%",
                   "Not computed: CMS does not say whether its national prescriber count",
                   "Excludes employer, PACE and demonstration plans"):
        assert phrase in words, phrase
    assert view["_payer_detail_html"](load("comirnaty")) == ""


def test_a_reused_code_is_named_in_the_detail(view):
    words = text_of(view["_payer_detail_html"](load("verzenio")))
    assert "665 prescriptions on 00002-4415" in words


def test_the_byline_names_the_three_sources_and_carries_the_nlm_statement(view):
    text = view["_payer_byline"](load("eliquis"))
    assert "Medicare Part D Prescribers" in text and "State Drug Utilization Data" in text
    assert "RxNav" in text
    assert ("NLM is not responsible for the product and does not endorse or recommend "
            "this or any other product.") in text


def test_house_style_in_every_builder(view):
    for name in NAMES:
        access = load(name)
        for markup in (*_panels(view, access).values(), view["_payer_detail_html"](access),
                       view["_payer_co_line"](access), view["_payer_byline"](access)):
            house_style(text_of(markup))


def test_the_panel_titles_and_scopes_are_sentence_case(view):
    titles = [t for _, t in view["_PAYER_PANELS"]]
    assert titles == ["Part D prescribing", "Part D plan coverage", "Medicaid prescriptions"]
    for scope in (*view["_PAYER_SCOPE"].values(), load("eliquis")["formulary"]["scope_label"]):
        house_style(scope)
    assert load("eliquis")["prescribing"]["scope_label"] == "Medicare Part D only, 2024"


def test_the_row_is_drawn_for_a_marketed_product_only(view):
    shows = view["_payer_shows"]
    assert shows({"is_marketed": True, "access": load("eliquis")})
    assert not shows({"is_marketed": False, "access": load("eliquis")})
    assert not shows({"is_marketed": True, "access": None})
    assert not shows({})
