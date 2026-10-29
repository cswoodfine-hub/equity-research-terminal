"""The fact profile's stack behind the LOE date (plan step 7): the range valued at each
end, the erosion row with its sample, and the FDA Paragraph IV list.

The builders live in the Streamlit script, which runs the whole app on import, so they
are read out of its source by name and run on what the profile returned for two real
products on a copy of the book (``fixtures/patent_stack/``): Rinvoq, whose molecule
patent and latest patent differ, and Farxiga, whose first generic launched in 2026.
"""

from __future__ import annotations

import ast
import html
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "frontend" / "streamlit_app.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "patent_stack"

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
NAMES = ("_loe_range_html", "_money_mm", "_erosion_html", "_paragraph_iv_html",
         "_prof_rows", "html_escape")


@pytest.fixture(scope="module")
def view():
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = [node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in NAMES]
    assert {node.name for node in keep} == set(NAMES)
    space = {"html": html, "re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def text_of(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _house_style(text: str) -> None:
    assert EM_DASH not in text
    assert not any(word in text.lower() for word in BANNED)


def test_the_range_shows_each_end_with_its_value(view):
    prof = load("abbv_rinvoq")
    text = text_of("".join(view["_loe_range_html"](prof["loe_range"])))
    rng = prof["loe_range"]
    assert rng["bear"]["date"] != rng["base"]["date"]
    for end in ("bear", "base"):
        assert f'{end} {rng[end]["date"][:10]} · NPV' in text
    assert rng["why_bear"] in text
    # Rinvoq's latest patent is the base date, so the bull end says so instead of
    # printing the same value twice under a basis of "the base".
    assert rng["bull"]["date"] == rng["base"]["date"]
    assert "bull same as base" in text and "bull basis" not in text
    _house_style(text)


def test_a_range_of_one_date_says_so_rather_than_drawing_three(view):
    prof = load("azn_farxiga")
    text = text_of("".join(view["_loe_range_html"](prof["loe_range"])))
    assert "one date" in text and "bear" not in text
    assert view["_loe_range_html"](None) == []


def test_the_erosion_row_names_its_sample(view):
    text = text_of("".join(view["_erosion_html"](load("abbv_rinvoq")["erosion"])))
    assert "small molecule" in text and "year one -71%" in text
    assert "fitted to 134 launches" in text
    stated = text_of("".join(view["_erosion_html"](
        {"row": "stated", "year1_pct": 0.5, "decay_pct": None, "sample_n": None})))
    assert "stated on the asset" in stated and "fitted" not in stated
    assert view["_erosion_html"](None) == []


def test_paragraph_iv_lists_each_strength_and_never_dates_the_stay(view):
    prof = load("azn_farxiga")
    text = text_of("".join(view["_paragraph_iv_html"](prof["paragraph_iv"])))
    row = prof["paragraph_iv"][0]
    assert row["submission_date"][:10] in text
    assert f'{row["anda_count"]} filers' in text
    assert f'generic sold from {row["first_marketing"][:10]}' in text
    assert "does not date" in text
    rinvoq = text_of("".join(view["_paragraph_iv_html"](load("abbv_rinvoq")["paragraph_iv"])))
    assert "generic sold" not in rinvoq
    _house_style(text + rinvoq)


def test_the_fixture_stack_carries_extension_and_use_codes():
    """What the patent rows draw from: Farxiga's molecule patent carries its five-year
    certificate, and its method-of-use patents their codes."""
    patents = load("azn_farxiga")["patents"]
    governing = next(p for p in patents if p["governs"])
    assert governing["term_extension"]["extension"] == "5 years"
    assert any(p["use_codes"] for p in patents if p["kind"] == "method of use")
