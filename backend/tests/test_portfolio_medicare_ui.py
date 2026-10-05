"""The Portfolio tab's Medicare demand layer and the fact profile's Medicare tile
(docs/design/medicare-demand-split.md).

The builders are read out of the Streamlit script by name, as the Forecast layer's are,
and run on the company split the API returned for BMY and AMGN on a copy of the book
(``fixtures/medicare_split``). Then the tab through AppTest, opt-in against a running
API.
"""

from __future__ import annotations

import copy
import json
import re
import urllib.request

import pytest

from test_forecast_medicare_layer_ui import (API, APP, api_up, builders, house_style,
                                             load, text_of)


@pytest.fixture(scope="module")
def view():
    return builders()


def _brands_in_order(markup: str) -> list[str]:
    body = markup.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [re.sub(r"<[^>]+>.*", "", cell) for cell in
            re.findall(r"<tr[^>]*><td>(.*?)</td>", body)]


def test_rows_run_by_latest_spend_and_fold_after_fifteen(view):
    split = load("company_bmy")
    out = view["_medicare_book_html"](split)
    shown = _brands_in_order(out)
    assert shown[0] == "Eliquis" and len(shown) == 15
    spends = [r["spending"] for r in split["brands"]]
    assert spends == sorted(spends, reverse=True)
    assert f"{len(split['brands']) - 15} more" in out and "<details" in out


def test_a_minor_part_is_one_muted_row_not_split(view):
    split = load("company_amgn")
    assert any(not r["material"] for r in split["brands"])
    out = view["_medicare_book_html"](split)
    assert 'class="mc-minor"' in out
    assert "not split" in text_of(out)


def test_the_median_line_names_its_count_and_floor(view):
    split = load("company_bmy")
    words = text_of(view["_medicare_book_html"](split))
    n = split["baseline"]["D"]["n"]
    assert f"Tracked Part D median 2024: patients" in words
    assert f"{n} brands over $50mm" in words
    assert "fills per patient" in words and "cost per fill" in words
    assert "Tracked Part B median 2024" in words and "claims per patient" in words


def test_the_label_sits_above_the_table_and_disagreement_is_marked(view):
    out = view["_medicare_book_html"](load("company_bmy"))
    assert out.index("mc-label") < out.index("<table")
    assert text_of(out).startswith("Medicare only.")
    assert 'class="mc-dis"' in out                     # Revlimid's model against Medicare


def test_a_patient_count_that_is_not_like_for_like_says_so(view):
    split = copy.deepcopy(load("company_bmy"))
    first = split["brands"][0]
    assert "not like for like" not in text_of(view["_medicare_book_html"](split))
    first["like_for_like"] = False                 # as Cosentyx's 2024 step on the copy
    words = text_of(view["_medicare_book_html"](split))
    assert "not like for like" in words


def test_house_style_and_dollar_signs_that_markdown_cannot_pair(view):
    for name in ("company_amgn", "company_bmy"):
        out = view["_medicare_book_html"](load(name))
        house_style(text_of(out))
        assert "$" not in out                          # written as an entity


def test_no_brands_draws_nothing(view):
    assert view["_medicare_book_html"](load("company_crsp")) == ""
    assert view["_medicare_book_html"](None) == ""


# --- the fact profile tile -------------------------------------------------------------
DEM = {"year": 2024, "spend": 20.77e9, "spend_growth": 0.1369, "prior_year": 2023,
       "parts": [{"part": "D", "patient_growth": 0.1265, "like_for_like": True}]}


def test_the_tile_shows_patients_only_when_like_for_like(view):
    sub = view["_medicare_tile_sub"]
    assert sub(DEM) == "US 2024, +13.7% YoY, patients +12.7%"
    changed = copy.deepcopy(DEM)
    changed["parts"][0]["like_for_like"] = False
    assert sub(changed) == "US 2024, +13.7% YoY"
    no_count = copy.deepcopy(DEM)
    no_count["parts"][0]["patient_growth"] = None
    assert sub(no_count) == "US 2024, +13.7% YoY"
    assert sub({"year": 2024, "spend": 1.0, "spend_growth": None}) == "US 2024"
    assert sub(None) == "not in Part D/B"
    two = copy.deepcopy(DEM)
    two["parts"].append({"part": "B", "patient_growth": 0.03, "like_for_like": True})
    assert sub(two).endswith("patients +12.7% in Part D")


# --- the tab, through AppTest ----------------------------------------------------------
@pytest.mark.skipif(not api_up(), reason="ER_TOOL_APPTEST is unset or the API is down")
def test_the_portfolio_has_a_medicare_layer_for_bmy_and_not_crispr():
    from streamlit.testing.v1 import AppTest

    def tabs_for(ticker):
        at = AppTest.from_file(str(APP), default_timeout=180)
        at.query_params["ticker"] = ticker
        at.run()
        return [t.label for t in at.tabs]

    with urllib.request.urlopen(API + "/companies/CRSP/demand/split", timeout=60) as resp:
        assert json.loads(resp.read())["brands"] == []
    assert "Medicare demand" in tabs_for("BMY")
    assert "Medicare demand" not in tabs_for("CRSP")
