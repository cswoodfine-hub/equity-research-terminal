"""Key insights, the company on one page (docs/design/key-insights.md).

Three layers.

The tab's string builders live in the Streamlit script, which runs the whole app on
import, so they are read out of its source by name and run on the sample scorecard
(``fixtures/company_score/sample_scorecard.json``), the saved comps-context answers and
change feeds of ``fixtures/drivers`` (``ctx_*.json``, ``feed_*.json``) and small dicts
built here; none of them touches Streamlit. They are tested in the order the page draws
them: the call beside the price, with the market row and the business row under it; the
morning note, which opens the second band and is reasoned from every figure on the page;
the readouts and decisions under it; the key assets, five marketed and five pipeline, and
the losses of exclusivity under them; where the twelve-month value comes from and the
business against its cohort; then what changed.

The pictures the tab draws (``price_call``, ``peer_dots``, the bridge's ``waterfall``) and
``pillar_bars`` are tested as the chart primitives they are.

Then the tab itself, driven in-process through AppTest against the API, which is skipped
when the API is not up, like the other tab tests.

A test marked xfail(strict=True) pins what the page should do where the builder does not
yet do it; its reason names the defect.
"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "streamlit_app.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SAMPLE = FIXTURES / "company_score" / "sample_scorecard.json"
DRIVERS = FIXTURES / "drivers"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

from components import charts, tokens  # noqa: E402
import drivers  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
# A move is never given a cause: the month's news is set beside it, not behind it.
CAUSAL = ("because", "due to", "drove", "driven by", "caused", "thanks to", "on the back of",
          "as a result of")
# The extra names the builders call, read out of the script with them: the launch floor's
# flag is one mark shared with the Pipeline tab and the Forecast tab's Next gate block.
SHARED = ("html_escape", "change_row", "_launch_flag", "_launch_flagged", "_LAUNCH_TONES")


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
        if name.startswith(("_ki_", "_KI_")) or name in SHARED:
            keep.append(node)
            names.add(name)
    assert set(SHARED) <= names
    assert "_key_insights_tab" not in names           # the renderer is not pure
    space = {"html": html, "re": re, "dt": dt}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


@pytest.fixture(scope="module")
def board():
    return json.loads(SAMPLE.read_text())


def _ctx(ticker):
    return json.loads((DRIVERS / f"ctx_{ticker}.json").read_text())


def _saved_feed(ticker):
    return json.loads((DRIVERS / f"feed_{ticker}.json").read_text())


def _today(board) -> dt.date:
    return dt.date.fromisoformat(board["today"])


def _text(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _house_style(text: str) -> None:
    assert EM_DASH not in text, text
    low = text.lower()
    assert not [w for w in BANNED if re.search(rf"\b{w}\b", low)], text


def _sentence_case(text: str, allowed=("Forecast", "Catalysts", "News", "Comps",
                                         "Portfolio")) -> None:
    """Opens on a capital and carries no other title case, bar the names of the tabs."""
    words = text.split()
    assert words[0][0].isupper(), text
    assert not [w for w in words[1:] if w.isalpha() and w[0].isupper()
                and w not in allowed], text


# --- the call ------------------------------------------------------------------------------
AZN_RATED = {"ok": True, "rating": "Buy", "close": 157.70, "forward_12m": 192.4919244,
             "forward_low": 163.4447396, "forward_high": 230.9862652,
             "upside_12m": 0.2206209774, "cost_of_equity": 0.076084, "dps": 3.1770097,
             "basis": "the range the sum of the parts spans"}
AZN_STREET = {"value": 211.631972238, "low": 155.13849, "high": 267.84594,
              "as_of": "2026-10-02", "ratings": {"buy": 14, "hold": 2, "sell": 0}}


def _points(n_days=400, last="2026-10-01", start=100.0, end=110.0, prev=None):
    last_d = dt.date.fromisoformat(last)
    pts = []
    for k in range(n_days, -1, -1):
        d = last_d - dt.timedelta(days=k)
        pts.append({"as_of": d.isoformat(), "close": start + (end - start) * (n_days - k) / n_days})
    if prev is not None:
        pts[-2]["close"] = prev
    return pts


def test_the_year_series_is_the_last_year_and_its_moves(view):
    series = view["_ki_year_series"](_points(400, prev=112.0))
    assert series["dates"][0] == "2025-10-01" and series["dates"][-1] == "2026-10-01"
    assert series["close"] == pytest.approx(110.0)
    assert series["day_move"] == pytest.approx(110.0 / 112.0 - 1)
    assert series["year_move"] == pytest.approx(110.0 / series["closes"][0] - 1)
    # Less than a year of prices: no year move rather than a part-year one called a year.
    short = view["_ki_year_series"](_points(200))
    assert short["year_move"] is None and short["close"] is not None
    assert view["_ki_year_series"]([])["close"] is None


def test_the_call_leads_with_the_models_value_its_word_and_its_range(view):
    series = {"close": 157.70}
    call = view["_ki_call"](AZN_RATED, None, series, AZN_STREET)
    assert (call["source"], call["word"], call["word_tone"]) == ("model", "Buy", "up")
    assert (call["value"], call["move"], call["move_tone"]) == ("192.49", "+22.1%", "up")
    assert call["sub"] == "against 157.70 · 163 to 231 in 12 months"
    assert call["tip"] == "rolled a year at the 7.6% cost of equity, less the 3.18 dividend"
    markup = view["_ki_call_html"](call, [])
    assert 'class="pos ki-call"' in markup
    text = _text(markup)
    assert text.index("Buy") < text.index("192.49") < text.index("+22.1%")
    sell = view["_ki_call"](dict(AZN_RATED, rating="Sell", upside_12m=-0.52), None,
                            {"close": 1149.85}, None)
    assert sell["word_tone"] == "down" and sell["move"] == "−52.0%"


def test_without_a_model_the_call_is_the_street_or_a_dot_with_its_reason(view):
    series = {"close": 50.0}
    street = view["_ki_call"]({"ok": False, "reason": "no sum of the parts"}, None, series,
                              {"value": 60.0})
    assert (street["source"], street["key"], street["value"]) == (
        "street", "12-month street target", "60.00")
    assert street["move"] == "+20.0%" and street["note"] == "not rated"
    none = view["_ki_call"]({}, "no value against a price", series, None)
    # No lone dot: the reason leads, in words, with the detail on hover.
    assert none["source"] is None and none["value"] == ""
    assert none["sub"] == "Not modelled, and no consensus on file."
    assert none["tip"] == "no value against a price; no consensus on file"
    markup = view["_ki_call_html"](none, [])
    assert '<span class="ki-fig' not in markup and "ki-sub-lead" in markup


def test_a_rating_that_did_not_load_is_said_to_have_failed_not_replaced(view):
    call = view["_ki_call_failed"]("timed out")
    assert call["source"] is None and call["value"] == ""
    assert call["sub"] == "The rating did not load; reload in a minute."


def test_a_range_is_whole_figures_only_where_its_low_end_is_100_or_more(view):
    """MRNA's 12-month range is 18.82 to 19.12: whole figures read it as "19 to 19"."""
    fmt = view["_ki_range_fmt"]
    assert (fmt(18.82, 18.82), fmt(19.12, 18.82)) == ("18.82", "19.12")
    assert (fmt(163.44, 163.44), fmt(230.99, 163.44)) == ("163", "231")
    assert fmt(150.0, 99.0) == "150.00"             # the low end sets the precision
    assert fmt(None, 18.82) == "·"
    call = view["_ki_call"](dict(AZN_RATED, forward_12m=18.97, forward_low=18.82,
                                 forward_high=19.12, upside_12m=0.01), None,
                            {"close": 18.78}, None)
    assert call["sub"] == "against 18.78 · 18.82 to 19.12 in 12 months"


def _azn_series(view):
    return view["_ki_year_series"](_points(400, start=168.7, end=157.70, prev=161.47))


def test_the_market_row_is_five_cells_the_close_the_day_the_year_the_street_and_the_multiple(
        view, board):
    azn = board["companies"]["AZN"]
    series = _azn_series(view)
    call = view["_ki_call"](AZN_RATED, None, series, AZN_STREET)
    mom = view["_ki_metric"](azn, ("rel_1y",))
    mult = azn["facts"]["multiple"]
    place = view["_ki_metric"](azn, (mult["metric"],))
    cells = view["_ki_figures"](series, call, mom, AZN_STREET, mult, place)
    assert all(len(c) == 4 for c in cells)
    assert [c[:3] for c in cells] == [
        ("157.70", "close", ""),
        ("−2.3%", "24 hours", "down"),                 # the day's move, signed and toned
        ("−6.0%", f"1 year · {mom['text']} vs XLV", "down"),
        ("211.63", "street target", ""),
        (mult["text"], f"{mult['label']} · median {mult['median_text']}", "")]
    assert cells[0][3] == "as of 2026-10-01"
    assert cells[2][3] == f"{mom['place']} of {mom['n']} against XLV"
    assert "14 buy, 2 hold" in cells[3][3] and "sell" not in cells[3][3]  # a zero is left out
    assert cells[4][3] == f"{place['place']} of {place['n']}"
    up = view["_ki_figures"](dict(series, day_move=0.012), call, mom, AZN_STREET, mult, place)
    assert up[1][:3] == ("+1.2%", "24 hours", "up")
    # Every empty cell is a dot whose key says why, never a zero or a lone dot.
    empty = view["_ki_figures"]({}, {"source": None}, None, None, None, None)
    assert [c[0] for c in empty] == ["·"] * 5
    assert [c[1] for c in empty] == [
        "close · no price on file", "24 hours · no prior close",
        "1 year · under a year of prices", "street · no consensus on file",
        "multiple · none on file"]
    assert all(c[2] == "none" and c[3] for c in empty)
    # A street lead puts the year's range in the street's place, so it is not said twice.
    led = view["_ki_figures"](series, {"source": "street"}, mom, AZN_STREET, mult, None)
    assert led[3][:3] == ("158 to 168", "52 weeks", "small")
    assert "211.63" not in [c[0] for c in led]
    bare = view["_ki_figures"]({"close": 50.0}, {"source": "street"}, None, AZN_STREET, None,
                               None)
    assert bare[3][:3] == ("·", "52 weeks · no price on file", "none")


# --- the business row ------------------------------------------------------------------------
AZN_REVENUE = {"reported_revenue": [{"fiscal_year": 2024, "value": 54073.0},
                                    {"fiscal_year": 2025, "value": 58739.0}]}


def _business_record(**kw):
    rec = _record()
    rec["market"] = {"market_cap_usd_m": 245512.0,
                     "market_cap_basis_text": "shares on file at the close"}
    rec.update(kw)
    return rec


def test_revenue_is_the_latest_year_as_filed_with_its_growth(view):
    rev = view["_ki_revenue"](AZN_REVENUE, {"reporting_currency": "USD", "row_currency": "EUR"})
    assert (rev["figure"], rev["currency"], rev["fy"]) == ("58.7bn", "EUR", "FY2025")
    assert rev["growth"] == pytest.approx(58739.0 / 54073.0 - 1)
    # Two years apart is no year's growth: none rather than two years called one.
    gap = view["_ki_revenue"]({"reported_revenue": [{"fiscal_year": 2023, "value": 45811.0},
                                                    {"fiscal_year": 2025, "value": 58739.0}]},
                              {"reporting_currency": "USD"})
    assert gap["growth"] is None and gap["currency"] == "USD"
    # No reported rows: the payload's FY0, in dollars, with no growth.
    assert view["_ki_revenue"]({}, _record()) == {"figure": "58.7bn", "currency": "USD",
                                                  "fy": "FY2025", "growth": None}
    assert view["_ki_revenue"]({}, {}) == {} and view["_ki_revenue"](None, None) == {}
    level = view["_ki_level"]
    assert level(0) == ("0", "") and level(940.4) == ("940", "mm")
    assert level(58739.0) == ("58.7", "bn") and level(None) == ("·", "")


def test_revenue_older_than_the_latest_year_is_a_dot_that_says_which_year_it_is(view):
    """A filer whose last revenue is FY2022 against an FY2025 record had no revenue for
    FY2025: the old figure is never printed under the new year's key."""
    old = {"reported_revenue": [{"fiscal_year": 2021, "value": 410.0},
                                {"fiscal_year": 2022, "value": 520.0}]}
    rev = view["_ki_revenue"](old, _record())
    assert rev == {"figure": "", "currency": "", "fy": "FY2025", "growth": None,
                   "stale": "FY2022"}
    cell = view["_ki_business_figures"](_record(), old, None, False, None)[1]
    assert cell == ("·", "FY2025 revenue", "none",
                    "no revenue filed for FY2025; the last filed is FY2022")
    # With no latest year on file to set it against, the last filed year is its own key.
    assert view["_ki_business_figures"]({}, old, None, False, None)[1][:2] == (
        "520mm", "FY2022 revenue · +26.8%")


def test_revenue_under_a_million_prints_in_thousands_and_gives_no_growth(view):
    level = view["_ki_level"]
    assert level(0.041) == ("41", "k") and level(0.9994) == ("999", "k")
    assert level(1.0) == ("1", "mm")
    tiny = {"reported_revenue": [{"fiscal_year": 2024, "value": 0.2},
                                 {"fiscal_year": 2025, "value": 0.041}]}
    rev = view["_ki_revenue"](tiny, {"reporting_currency": "USD"})
    assert (rev["figure"], rev["growth"]) == ("41k", None)
    # Off a base under a million, growth is noise; the other way round too.
    up = {"reported_revenue": [{"fiscal_year": 2024, "value": 0.3},
                               {"fiscal_year": 2025, "value": 12.0}]}
    assert view["_ki_revenue"](up, {})["growth"] is None
    whole = {"reported_revenue": [{"fiscal_year": 2024, "value": 1.0},
                                  {"fiscal_year": 2025, "value": 2.0}]}
    assert view["_ki_revenue"](whole, {})["growth"] == pytest.approx(1.0)
    cell = view["_ki_business_figures"]({"reporting_currency": "USD"}, tiny, None, False, None)[1]
    assert cell[:2] == ("$41k", "FY2025 revenue")


def test_the_business_row_is_market_value_revenue_products_and_the_pipeline(view, board):
    azn = board["companies"]["AZN"]
    verdict = dict(AZN_REVENUE, sotp={"marketed": {"n": 32, "per_share": 89.61}})
    cells = view["_ki_business_figures"](_business_record(), verdict, azn, True,
                                         AZN_EXCLUSIVITIES)
    assert all(len(c) == 4 for c in cells)
    assert [c[:3] for c in cells] == [
        ("$245.5bn", "market cap", ""),
        ("$58.7bn", "FY2025 revenue · +8.6%", ""),
        ("32", "products on sale", ""),            # the products the model counts
        ("23", "late-stage", ""),                  # Phase 3 and Phase 2/3
        ("90", "in trials", "")]                   # Phase 1 to 3: a Phase 4 is on sale
    assert cells[4][3] == "every compound in Phase 1 to Phase 3 with a trial on file"
    assert cells[0][3] == "shares on file at the close"
    assert cells[1][3] == "FY2025 revenue as filed, in USD"
    late = view["_ki_metric"](azn, ("late_compounds",))
    assert cells[3][3] == f"compounds in Phase 3 or Phase 2/3 · {late['place']} of {late['n']}"
    # Not modelled: the approved products on file, one product however many applications.
    plain = view["_ki_business_figures"](_business_record(row_currency="EUR"), AZN_REVENUE, azn,
                                         False, EXPIRY_EXCLUSIVITIES)
    assert plain[1][:2] == ("€58.7bn", "FY2025 revenue · +8.6%")
    assert plain[2][:2] == ("5", "approved products")       # Farxiga's two are one
    # A product is its molecule: a new formulation under another brand counts once.
    nbix = [{"asset_id": 1, "brand_name": "Ingrezza", "generic_name": "valbenazine"},
            {"asset_id": 2, "brand_name": "Ingrezza Sprinkle", "generic_name": "valbenazine"},
            {"asset_id": 3, "brand_name": "Crenessity", "generic_name": "crinecerfont"}]
    counted = view["_ki_business_figures"](_business_record(), AZN_REVENUE, azn, False, nbix)
    assert counted[2][:2] == ("2", "approved products")
    assert "a new formulation counted once" in counted[2][3]
    # Modelled with no count of products on sale: the approvals too.
    uncounted = view["_ki_business_figures"](_business_record(), {"sotp": {}}, azn, True,
                                             AZN_EXCLUSIVITIES)
    assert uncounted[2][:2] == ("3", "approved products")
    # A currency with a short sign carries it; any other is named in the key.
    for code, sign in (("GBP", "£"), ("JPY", "¥")):
        cell = view["_ki_business_figures"](_business_record(row_currency=code), AZN_REVENUE,
                                            azn, False, [])[1]
        assert cell[:2] == (f"{sign}58.7bn", "FY2025 revenue · +8.6%")
    chf = view["_ki_business_figures"](_business_record(row_currency="CHF"), AZN_REVENUE, azn,
                                       False, [])
    assert chf[1][:2] == ("58.7bn", "FY2025 revenue CHF · +8.6%")
    assert chf[2][:3] == ("·", "products on sale", "none")
    # Nothing on file: five dots, each with its reason on hover.
    none = view["_ki_business_figures"]({}, {}, None, False, None)
    assert [c[:3] for c in none] == [
        ("·", "market cap", "none"), ("·", "revenue", "none"),
        ("·", "products on sale", "none"), ("·", "late-stage", "none"),
        ("·", "in trials", "none")]
    assert all(c[3] for c in none)


def test_revenue_in_an_unknown_currency_is_never_said_to_be_dollars(view):
    """The verdict's reported rows loaded, the record that names their currency did not."""
    cell = view["_ki_business_figures"]({}, AZN_REVENUE, None, False, None)[1]
    assert cell[0] == "58.7bn"                      # no sign: the currency is not known
    assert cell[3] == "FY2025 revenue as filed"     # and no currency named on hover
    assert "USD" not in cell[3]


def test_the_call_draws_the_market_row_then_the_business_row(view, board):
    series = _azn_series(view)
    call = view["_ki_call"](AZN_RATED, None, series, AZN_STREET)
    figures = view["_ki_figures"](series, call, None, AZN_STREET, None, None)
    business = view["_ki_business_figures"](_business_record(), AZN_REVENUE,
                                            board["companies"]["AZN"], False, [])
    markup = view["_ki_call_html"](call, figures, business)
    assert markup.count('<div class="ki-figs">') == 1
    assert markup.count('<div class="ki-figs ki-biz">') == 1
    assert markup.index('<div class="ki-figs">') < markup.index("ki-biz")
    cells = re.findall(r'<div class="ki-f" title="[^"]*"><span class="v ?([a-z]*)">([^<]*)'
                       r'</span><span class="k">([^<]*)</span></div>', markup)
    assert [c[1] for c in cells] == [f[0] for f in figures] + [b[0] for b in business]
    assert cells[1] == ("down", "−2.3%", "24 hours")
    assert cells[7] == ("none", "·", "products on sale")
    # Without a business row, one grid.
    assert "ki-biz" not in view["_ki_call_html"](call, figures)


# --- where the value comes from ---------------------------------------------------------------
AZN_SOTP = {"close": 157.70, "marketed": {"n": 32, "per_share": 89.61},
            "pipeline": {"n": 22, "per_share": 12.32}, "lines": {"n": 0, "per_share": 0.0},
            "future": {"per_share": 88.76}, "carry_per_share": 10.58,
            "growth_investment": {"per_share": -3.62}, "net_cash_per_share": -15.28,
            "other_claims_per_share": -0.54, "cost_of_equity": 0.076, "dps": 3.17,
            "valuation_anchor": "2025-12-31", "years_to_price": 0.75,
            "price_date": "2026-10-01"}
AZN_SOTP["equity_per_share"] = 89.61 + 12.32 + 88.76 + 10.58 - 3.62 - 15.28 - 0.54
AZN_SOTP["forward_12m"] = AZN_SOTP["equity_per_share"] * 1.076 - 3.17

# The breakpoints answer: today's value is above the price, so the call holds while the
# nearest levers stay on the right side of their breaks.
AZN_BP = {"ok": True, "direction": "down", "equity_per_share": 181.83, "close": 157.70,
          "sentence": {"body": ["AZN holds while..."]},
          "levers": [
              {"name": "AZN", "lever": "launch productivity", "scope": "company",
               "kind": "rate", "key": "launch_rate", "model": 0.364, "break": 0.312,
               "reachable": True, "distance": 0.72},
              {"name": "AZN", "lever": "every discount rate", "scope": "company",
               "kind": "rate", "key": "wacc_shift", "model": 0.0747, "break": 0.0835,
               "reachable": True, "distance": 0.59},
              {"name": "Tagrisso", "lever": "discount rate", "scope": "asset", "kind": "rate",
               "key": "wacc", "model": 0.0747, "break": 0.1469, "reachable": True,
               "distance": 4.8},
              {"name": "AZN", "lever": "never", "scope": "company", "kind": "rate",
               "model": 0.1, "break": None, "reachable": False, "distance": 0.1}]}


def test_the_bridge_runs_from_what_is_sold_to_the_twelve_month_value_and_adds_up(view):
    b = view["_ki_bridge"](AZN_SOTP, AZN_SOTP["forward_12m"])
    assert b["ok"]
    assert [x["label"] for x in b["steps"]] == [
        "marketed", "pipeline", "launches", "to today", "growth capital", "net debt", "today",
        "a year on", "12 months"]
    debt = next(x for x in b["steps"] if x["label"] == "net debt")
    assert debt["value"] == pytest.approx(-15.28 - 0.54)
    assert debt["tip"] == "net debt −15.28, other claims −0.54"
    assert b["end"] == pytest.approx(AZN_SOTP["forward_12m"])
    # The chart draws it; its ends are the equity and the twelve-month value.
    svg = charts.waterfall(b["steps"], 800, 200, value_fmt=lambda x: f"{x:,.2f}")
    ET.fromstring(svg)
    assert f">{AZN_SOTP['equity_per_share']:,.2f}<" in svg
    assert f">{AZN_SOTP['forward_12m']:,.2f}<" in svg
    assert "<title>net debt −15.28, other claims −0.54" in svg   # the merge lists its parts


def test_a_bridge_that_does_not_add_up_is_not_drawn(view):
    off = dict(AZN_SOTP, equity_per_share=AZN_SOTP["equity_per_share"] + 1)
    assert not view["_ki_bridge"](off)["ok"]
    assert not view["_ki_bridge"](AZN_SOTP, AZN_SOTP["forward_12m"] + 0.5)["ok"]
    assert not view["_ki_bridge"]({"marketed": {"per_share": None}})["ok"]
    # No debt on file: the sum stops at enterprise value, and must reach the one on file.
    # Viking's bar read 32.87 against an enterprise value of 20.56: growth capital was left
    # out and nothing checked.
    ev_run = 89.61 + 12.32 + 88.76 + 10.58 - 3.62 - 0.54
    ev = view["_ki_bridge"](dict(AZN_SOTP, net_cash_per_share=None,
                                 enterprise_today_per_share=ev_run))
    assert ev["ok"] and ev["steps"][-1]["label"] == "EV today"
    assert [x["label"] for x in ev["steps"]][-3:-1] == ["growth capital", "other claims"]
    assert ev["end"] == pytest.approx(ev_run)
    assert not view["_ki_bridge"](dict(AZN_SOTP, net_cash_per_share=None,
                                       enterprise_today_per_share=ev_run + 12.3))["ok"]
    assert not view["_ki_bridge"](dict(AZN_SOTP, net_cash_per_share=None))["ok"]


def test_net_cash_is_named_as_cash_and_never_as_a_cost(view):
    """Six companies hold more cash than debt; their merged step read "debt and costs" over
    a green bar."""
    cash = dict(AZN_SOTP, net_cash_per_share=19.77, other_claims_per_share=0.0)
    cash["equity_per_share"] = 89.61 + 12.32 + 88.76 + 10.58 - 3.62 + 19.77
    cash["forward_12m"] = cash["equity_per_share"] * 1.076 - 3.17
    b = view["_ki_bridge"](cash)
    labels = [x["label"] for x in b["steps"]]
    assert "net cash" in labels and "debt and costs" not in labels
    assert next(x for x in b["steps"] if x["label"] == "growth capital")["value"] < 0


def test_the_breaks_are_the_two_nearest_levers_that_reach_the_price(view):
    """The note says what would break the call; the levers are read here."""
    b = view["_ki_breaks"](AZN_BP)
    assert b["head"] == "Today's 181.83 meets the 157.70 price at"
    assert [(r["glyph"], r["name"], r["model"], r["brk"]) for r in b["rows"]] == [
        ("▲", "every discount rate", "7.47%", "8.35%"),
        ("▼", "launch productivity", "0.364 per R&D $", "0.312 per R&D $")]
    up = view["_ki_breaks"](dict(AZN_BP, direction="up"))
    assert up["head"] == "The 157.70 price needs"
    assert view["_ki_breaks"]({"ok": False}) == {}
    assert view["_ki_breaks"](dict(AZN_BP, levers=AZN_BP["levers"][3:])) == {}  # none reach
    asset = view["_ki_breaks"](dict(AZN_BP, levers=AZN_BP["levers"][2:3]))
    assert asset["rows"][0]["name"] == "Tagrisso's discount rate"
    bracket = view["_ki_breaks"](dict(AZN_BP, levers=[dict(AZN_BP["levers"][2],
                                                           name="Trikafta (Copackaged)")]))
    assert bracket["rows"][0]["name"] == "Trikafta's discount rate"


@pytest.mark.parametrize("kind, value, key, text", [
    ("rate", 0.0835, "wacc_shift", "8.35%"),
    ("rate", -0.9327, "", "−93.27%"),                 # the page's minus
    ("rate", 0.312, "launch_rate", "0.312 per R&D $"),  # productivity says its unit
    ("rate", -0.312, "launch_rate", "−0.312 per R&D $"),
    ("year", 2031.0, "", "2031"),
    ("years", 4.0, "", "4y"),
    ("years", 4.5, "", "4.5y"),
    ("level", 1200.0, "", "$1,200mm"),
    ("scale", 1.1, "", "×1.10"),
    ("price", 0.00125, "", "$1,250"),
    ("rate", None, "", "·"),
])
def test_a_lever_prints_in_its_own_unit(view, kind, value, key, text):
    assert view["_ki_lever_text"](kind, value, key) == text


def test_with_nothing_modelled_the_street_expects_its_eps_and_nothing_is_chained(view):
    rec = {"street": {"eps_first": {"FY1": {"value": 9.16}, "FY2": {"value": 10.44}}},
           "periods": {"FY1": {"label": "FY2026"}, "FY2": {"label": "FY2027"}}}
    assert view["_ki_street_expects"](rec) == [("9.16", "FY2026 EPS, street"),
                                               ("10.44", "FY2027 EPS, street")]
    assert view["_ki_street_expects"]({}) == []


def test_a_failed_forecast_read_is_not_called_nothing_modelled(view):
    assert view["_ki_forecast_state"](None, "timed out") == "failed"
    assert view["_ki_forecast_state"]({"ok": True, "per_share": 0.0, "sotp": {
        "marketed": {"per_share": 0.0}}}) == "not_modelled"
    assert view["_ki_forecast_state"]({"ok": True, "per_share": 5.0, "sotp": {
        "marketed": {"per_share": 4.0}}}) == "modelled"


# --- the morning note: its words -----------------------------------------------------------
def test_a_short_day_drops_the_year_and_anything_that_is_not_a_day_is_empty(view):
    day = view["_ki_short_day"]
    assert day("2026-09-28 07:37:14") == "28 Sep"
    assert day("2026-01-05") == "5 Jan"
    assert day("2026-09") == "" and day("2026-13-01") == "" and day(None) == ""


def test_a_slip_is_measured_between_the_headlines_two_dates(view):
    slip = view["_ki_slip_days"]
    assert slip({"headline": "AZN trial NCT1: primary completion slips 2027-05-14 -> "
                             "2028-01-10"}) == 241
    # A month alone is read as its first day, on either side.
    assert slip({"headline": "LLY trial NCT1: primary completion slips 2026-08 -> 2026-11"}) == 92
    assert slip({"headline": "LLY trial NCT1: primary completion slips 2026-08 -> "
                             "2026-08-27"}) == 26
    # No two dates, or a date that is not one: no figure rather than a wrong one.
    assert slip({"headline": "AZN trial NCT1: status Recruiting -> Active"}) is None
    assert slip({"headline": "slips 2026-02-30 -> 2026-03-01"}) is None
    assert slip(None) is None


def test_counts_are_words_to_ten_and_figures_above(view):
    assert [view["_ki_count_word"](n) for n in (0, 1, 3, 10, 11)] == [
        "no", "one", "three", "ten", "11"]


def test_a_change_reads_as_a_clause_of_prose_with_its_day(view):
    words = view["_ki_event_words"]

    def said(headline, date="2026-09-04", cut=True):
        return words({"headline": headline, "date": date}, "AZN", cut)

    # A new indication is dated by its approval, not by the day it was detected; a headline
    # with no approval date falls back to the day.
    assert said("AZN efficacy supplement: Truqap approved 2026-09-16",
                "2026-09-23 09:07:03") == "a new FDA indication for Truqap (16 Sep)"
    assert said("AZN efficacy supplement: Truqap approved",
                "2026-09-23 09:07:03") == "a new FDA indication for Truqap (23 Sep)"
    assert said("AZN FDA approval: Etcamah (NDA220359)") == "FDA approval of Etcamah (4 Sep)"
    assert said("AZN FDA approval: Etcamah") == "FDA approval of Etcamah (4 Sep)"
    # A filing names its first item, lower-cased, and counts the rest; two are both said.
    assert said("AZN 8-K: Material agreement signed") == (
        "an 8-K filing (material agreement signed) (4 Sep)")
    assert said("AZN 8-K: Material agreement signed, Material impairment") == (
        "an 8-K filing (material agreement signed and material impairment) (4 Sep)")
    assert said("AZN 8-K: Material agreement signed, Material impairment, Change in "
                "control") == "an 8-K filing (material agreement signed, 2 other items) (4 Sep)"
    assert said("AZN trial NCT06455449: Phase 2 -> Phase 2/3") == (
        "a trial (NCT06455449) moved from Phase 2 to Phase 2/3 (4 Sep)")
    assert said("AZN trial NCT06455449: endpoint_change") == (
        "a trial (NCT06455449) changed its primary endpoint (4 Sep)")
    assert said("AZN trial NCT06455449: primary completion slips 2027-05-14 -> 2028-01-10",
                "2026-09-25 05:35:23") == "a readout (NCT06455449) slipped 241 days (25 Sep)"
    # A press headline is said as it was published, without the ticker or a bracketed
    # preamble, cut at a clause or else a word.
    assert said("AZN [Press release] Imfinzi approved in Japan", "2026-09-10") == (
        "Imfinzi approved in Japan (10 Sep)")
    assert view["_KI_NEWS_CHARS"] == 72
    # Cut, the company's own "announces" goes first, so what happened survives the cut.
    long = ("AZN AstraZeneca announces strategic equity investment and clinical  "
            "collaboration with Summit Therapeutics to advance  leading ADC combination "
            "strategy in cancer")
    deal = said(long, "2026-09-28")
    assert deal == ("Strategic equity investment and clinical collaboration with Summit… "
                    "(28 Sep)")
    assert len(deal.split(" (")[0]) <= view["_KI_NEWS_CHARS"]
    assert said("AZN Imfinzi approved in the US for bladder cancer, the first perioperative "
                "immunotherapy for it", "2026-09-10") == (
        "Imfinzi approved in the US for bladder cancer… (10 Sep)")               # a clause
    assert said("AZN Trixeo Aerosphere approved in the EU for the maintenance treatment of "
                "uncontrolled asthma in adults", "2026-09-23") == (
        "Trixeo Aerosphere approved in the EU for the maintenance treatment of… "
        "(23 Sep)")                                                               # a word
    # Never cut inside an open bracket: the bracket goes with what it holds.
    assert said("AZN Truqap approved in the US with Faslodex (fulvestrant, a selective "
                "estrogen receptor degrader) for HR-positive breast cancer", "2026-09-10") == (
        "Truqap approved in the US with Faslodex… (10 Sep)")
    # Kept whole for the note model's facts.
    assert said(long, "2026-09-28", cut=False) == (
        "AstraZeneca announces strategic equity investment and clinical collaboration with "
        "Summit Therapeutics to advance leading ADC combination strategy in cancer (28 Sep)")
    assert said("AZN Short headline", None) == "Short headline"           # no day, no ()


def test_a_filing_takes_the_article_its_form_is_read_with(view):
    words = view["_ki_event_words"]
    for form in ("6-K", "10-Q", "10-K", "20-F"):
        said = words({"headline": f"AZN {form}: Material agreement signed",
                      "date": "2026-09-04"}, "AZN")
        assert said == f"a {form} filing (material agreement signed) (4 Sep)", said
    assert words({"headline": "AZN 8-K: Material agreement signed", "date": "2026-09-04"},
                 "AZN").startswith("an 8-K filing")


def test_a_filing_cut_to_three_items_counts_every_other_item(view):
    """edgar_items.describe ends a title past three items with ", and N more": the tail is
    a count of items, not one more item."""
    def said(headline):
        return view["_ki_event_words"]({"headline": headline, "date": "2026-09-04"}, "AZN")

    assert said("AZN 8-K: Material agreement signed, Acquisition or disposition completed, "
                "Material impairment, and 2 more") == (
        "an 8-K filing (material agreement signed, 4 other items) (4 Sep)")
    assert said("AZN 8-K: Material agreement signed, Acquisition or disposition completed, "
                "Material impairment, Change in control, and 2 more") == (
        "an 8-K filing (material agreement signed, 5 other items) (4 Sep)")
    # One item and a count is never "a and b": the count is said as other items.
    assert said("AZN 8-K: Material agreement signed, and 1 more") == (
        "an 8-K filing (material agreement signed, 1 other item) (4 Sep)")


def test_a_long_filing_is_cut_inside_its_items_never_to_the_bare_filing(view):
    long_item = ("Entry into a material definitive agreement with a counterparty named at "
                 "length in the filing and its affiliates")
    said = view["_ki_event_words"]({"headline": f"AZN 8-K: {long_item}, Material impairment",
                                    "date": "2026-09-04"}, "AZN")
    body = said[:-len(" (4 Sep)")]
    assert said.endswith("…) (4 Sep)") and body.startswith("an 8-K filing (entry into a ")
    assert len(body) <= view["_KI_NEWS_CHARS"] + 18
    assert not said.startswith("an 8-K filing…")
    # Whole for the note model's facts.
    assert view["_ki_event_words"]({"headline": f"AZN 8-K: {long_item}", "date": "2026-09-04"},
                                   "AZN", False) == (
        f"an 8-K filing ({long_item[:1].lower() + long_item[1:]}) (4 Sep)")


def test_a_release_is_said_in_plain_words(view):
    """Trademark signs, the analyst's review note, a release's long names and a word house
    style never uses all go, cut or whole."""
    def said(headline, cut=True):
        return view["_ki_event_words"]({"headline": headline, "date": "2026-09-10"}, "AZN", cut)

    assert said("AZN Imfinzi® and Imjudo™ approved in Japan") == (
        "Imfinzi and Imjudo approved in Japan (10 Sep)")
    for cut in (True, False):
        assert said("AZN Imfinzi approved in Japan. Review: check the indication", cut) == (
            "Imfinzi approved in Japan (10 Sep)")
    assert said("AZN FDA accepts Biologics License Application for Datroway") == (
        "FDA accepts BLA for Datroway (10 Sep)")
    assert said("AZN U.S. Food and Drug Administration accepts New Drug Application for "
                "Baxdrostat") == "FDA accepts NDA for Baxdrostat (10 Sep)"
    assert said("AZN Marketing Authorization Application for Datroway validated") == (
        "MAA for Datroway validated (10 Sep)")
    assert said("AZN Pivotal Phase 3 trial of Baxdrostat met its primary endpoint") == (
        "Phase 3 trial of Baxdrostat met its primary endpoint (10 Sep)")
    assert said("AZN Positive pivotal results for Baxdrostat", False) == (
        "Positive results for Baxdrostat (10 Sep)")


def test_a_headline_in_capitals_is_put_in_sentence_case_with_its_acronyms(view):
    def said(headline):
        return view["_ki_event_words"]({"headline": headline, "date": "2026-09-10"}, "AZN")

    assert said("AZN FDA APPROVES EU-BASED GLP-1 BLA FOR OBESITY") == (
        "FDA approves EU-based GLP-1 BLA for obesity (10 Sep)")
    assert said("AZN IMFINZI APPROVED IN THE EU AND US FOR BLADDER CANCER") == (
        "Imfinzi approved in the EU and US for bladder cancer (10 Sep)")
    # Mixed case is left as published.
    assert said("AZN Imfinzi approved by the FDA") == "Imfinzi approved by the FDA (10 Sep)"


def test_cut_a_release_loses_its_preamble_and_an_appositive_that_holds_the_result_back(view):
    def said(headline, cut=True):
        return view["_ki_event_words"]({"headline": headline, "date": "2026-09-10"}, "AZN", cut)

    assert view["_KI_PREAMBLE"].sub("", "AstraZeneca announces X", count=1) == "X"
    assert said("AZN AstraZeneca reports Imfinzi met its primary endpoint") == (
        "Imfinzi met its primary endpoint (10 Sep)")
    assert said("AZN Incyte and Syndax Announce FDA approval of Niktimvo for chronic "
                "graft-versus-host disease") == (
        "FDA approval of Niktimvo for chronic graft-versus-host disease (10 Sep)")
    head = ("AZN Remigromig, a tri-specific agonist of three receptors, met its primary "
            "endpoint in obesity")
    assert said(head) == "Remigromig met its primary endpoint in obesity (10 Sep)"
    # Whole, for the note model's facts, the release keeps both.
    assert said(head, False) == (
        "Remigromig, a tri-specific agonist of three receptors, met its primary endpoint in "
        "obesity (10 Sep)")
    assert said("AZN AstraZeneca reports Imfinzi met its primary endpoint", False) == (
        "AstraZeneca reports Imfinzi met its primary endpoint (10 Sep)")
    # A preamble that would leave next to nothing stays.
    assert said("AZN AstraZeneca announces results") == "AstraZeneca announces results (10 Sep)"


def test_medicare_selection_and_deselection_read_as_what_cms_did(view):
    def said(ticker, headline, cut=True):
        return view["_ki_event_words"]({"headline": headline, "date": "2026-09-10"}, ticker,
                                       cut)

    # The headlines diff.py writes.
    assert said("ABBV", "ABBV CMS selects 1 drug(s) for Medicare price negotiation, IPAY "
                        "2028: BOTOX") == (
        "CMS chose Botox for Medicare price negotiation, with prices from 2028 (10 Sep)")
    assert said("ABBV", "ABBV CMS selects 2 drug(s) for Medicare price negotiation, IPAY "
                        "2028: BOTOX, VRAYLAR", False) == (
        "CMS chose Botox and Vraylar for Medicare price negotiation, with prices from 2028 "
        "(10 Sep)")
    desel = ("NVS CMS has deselected ENTRESTO; ENTRESTO SPRINKLE from Medicare price "
             "negotiation (5 NDCs). Review: a deselection date belongs in the curated file "
             "before it moves an LOE")
    assert said("NVS", desel, False) == (
        "CMS dropped Entresto and Entresto Sprinkle from Medicare price negotiation (10 Sep)")
    assert said("NVS", "NVS CMS has deselected TASIGNA from Medicare price negotiation (3 "
                       "NDCs). Review: x") == (
        "CMS dropped Tasigna from Medicare price negotiation (10 Sep)")
    assert view["_ki_soft_caps"]("JAKAVI") == "Jakavi"
    assert view["_ki_soft_caps"]("ADC") == "ADC" and view["_ki_soft_caps"]("Mounjaro") == "Mounjaro"


@pytest.mark.parametrize("change_type, headline, tone", [
    ("new_approval", "AZN FDA approval: Etcamah (NDA220359)", "up"),
    ("press_approval", "AZN Trixeo approved in the EU for asthma", "up"),
    # Filed as an approval but reporting none: neither way.
    ("press_approval", "AZN AstraZeneca appoints a director to guide Baxdrostat toward "
                       "potential FDA approval", ""),
    ("press_approval", "AZN FDA accepts the filing for Baxdrostat, seeks approval in 2027", ""),
    ("efficacy_supplement", "AZN efficacy supplement: Truqap approved 2026-09-16", "up"),
    # A deselection follows a generic's entry: a loss of exclusivity, not good news.
    ("ira_deselected", "AZN Farxiga removed from Medicare negotiation", ""),
    ("ira_selected", "AZN Farxiga selected for Medicare negotiation", "down"),
    ("date_slip", "AZN trial NCT1: primary completion slips 2027-05-14 -> 2028-01-10", "down"),
    ("press_data_readout", "AZN Imfinzi met its primary endpoint in lung cancer", "up"),
    ("press_data_readout", "AZN Datroway showed statistically significant survival", "up"),
    ("press_data_readout", "AZN Enhertu improved survival in breast cancer", "up"),
    ("press_data_readout", "AZN Baxdrostat superior to placebo", "up"),
    ("press_data_readout", "AZN Tozorakimab did not meet its primary endpoint", "down"),
    ("press_data_readout", "AZN Phase 3 trial of X failed to show a benefit", "down"),
    ("press_data_readout", "AZN Phase 2 trial of Y discontinued for futility", "down"),
    ("press_data_readout", "AZN Phase 3 trial of Z halted", "down"),
    ("press_data_readout", "AZN Ceralasertib unlikely to meet its endpoint", "down"),
    ("press_data_readout", "AZN Data from a Phase 3 trial of W presented", ""),
    ("press_deal", "AZN AstraZeneca acquires Summit", ""),
    ("material event", "AZN 8-K: Material agreement signed", ""),
    ("status_change", "AZN trial NCT1: Phase 2 -> Phase 3", ""),
])
def test_news_reads_up_down_or_neither_for_the_holder(view, change_type, headline, tone):
    """A judgement on the news, from its kind and, for a readout, its own words."""
    assert view["_ki_news_tone"]({"change_type": change_type, "headline": headline}) == tone
    assert view["_ki_news_tone"](None) == ""


def _news(change_type, headline, date, kind="change"):
    return {"kind": kind, "significance": "high", "ticker": "AZN", "date": date,
            "change_type": change_type, "headline": headline}


def _month():
    return [
        _news("efficacy_supplement", "AZN efficacy supplement: Truqap approved 2026-09-16",
              "2026-09-23 09:07:03"),
        _news("efficacy_supplement", "AZN efficacy supplement: Tagrisso approved 2026-09-14",
              "2026-09-23 09:07:03"),
        _news("press_approval", "AZN Etcamah approved in the US for 1st-line breast cancer",
              "2026-09-04"),
        _news("new_approval", "AZN FDA approval: Etcamah (NDA220359)", "2026-09-04"),
        _news("new_approval", "AZN FDA approval: Newdrug (NDA123456)", "2026-09-05"),
        _news("press_deal", "AZN AstraZeneca acquires Summit", "2026-09-28"),
        _news("press_data_readout", "AZN Imfinzi improved survival in small cell lung cancer",
              "2026-09-10"),
        _news("date_slip", "AZN trial NCT06455449: primary completion slips 2027-05-14 -> "
                           "2028-01-10", "2026-09-25 05:35:23"),
        _news("date_slip", "AZN trial NCT07363642: primary completion slips 2027-08-07 -> "
                           "2028-02-07", "2026-09-04 11:09:14"),
        _news("rate_move", "The 10-year Treasury 5.26%", "2026-10-01", kind="market"),
    ]


def test_the_months_news_leads_with_results_then_deals_then_approvals_then_supplements(view):
    news = view["_ki_month_news"](_month(), "AZN", limit=10)
    assert news["said"] == [
        "Imfinzi improved survival in small cell lung cancer (10 Sep)",
        "AstraZeneca acquires Summit (28 Sep)",
        # Approvals newest first. Etcamah's FDA approval is the press release's own news,
        # so it is said once, as the company put it.
        "FDA approval of Newdrug (5 Sep)",
        "Etcamah approved in the US for 1st-line breast cancer (4 Sep)",
        # New indications are one clause, dated by the span they were approved over.
        "new FDA indications for Truqap and Tagrisso (14 to 16 Sep)"]
    assert news["full"] == news["said"]                  # nothing here is long enough to cut
    assert news["tones"] == ["up", "", "up", "up", "up"]
    assert not [s for s in news["said"] if "NCT" in s or "Treasury" in s]
    # Slips are counted, not listed, with the longest.
    assert (news["slips"], news["longest"], news["more"]) == (2, 241, 0)


def test_policy_ranks_with_deals_and_filings_come_before_other_changes(view):
    rows = [
        _news("status_change", "AZN trial NCT06455449: Phase 2 -> Phase 2/3", "2026-09-29"),
        _news("new_filing", "AZN 8-K: Material agreement signed", "2026-09-27"),
        _news("efficacy_supplement", "AZN efficacy supplement: Truqap approved 2026-09-16",
              "2026-09-23"),
        _news("ira_selected", "AZN Farxiga selected for Medicare negotiation", "2026-09-20"),
        _news("press_deal", "AZN AstraZeneca acquires Summit", "2026-09-12"),
        _news("press_data_readout", "AZN Tozorakimab did not meet its primary endpoint",
              "2026-09-02")]
    news = view["_ki_month_news"](rows, "AZN", limit=10)
    assert news["said"] == [
        "Tozorakimab did not meet its primary endpoint (2 Sep)",          # results
        "Farxiga selected for Medicare negotiation (20 Sep)",             # policy, newest
        "AstraZeneca acquires Summit (12 Sep)",                           # and deals
        "a new FDA indication for Truqap (16 Sep)",                       # supplements
        "an 8-K filing (material agreement signed) (27 Sep)",             # filings
        "a trial (NCT06455449) moved from Phase 2 to Phase 2/3 (29 Sep)"]  # the rest
    assert news["tones"] == ["down", "down", "", "up", "", ""]


def test_a_material_filing_in_the_feed_ranks_as_a_filing(view):
    """The material filings the feed carries (whatchanged._material_filings) are change_type
    "material event": they rank with filings, ahead of a later trial change."""
    assert view["_KI_NEWS_ORDER"]["material event"] == view["_KI_NEWS_ORDER"]["new_filing"]
    rows = [
        _news("status_change", "AZN trial NCT06455449: Phase 2 -> Phase 2/3", "2026-09-29"),
        _news("material event", "AZN 8-K: Material agreement signed", "2026-09-27",
              kind="filing")]
    news = view["_ki_month_news"](rows, "AZN")
    assert news["said"] == ["an 8-K filing (material agreement signed) (27 Sep)",
                            "a trial (NCT06455449) moved from Phase 2 to Phase 2/3 (29 Sep)"]


def test_the_note_says_at_most_two_pieces_of_news_and_counts_the_rest(view):
    news = view["_ki_month_news"](_month(), "AZN")
    assert view["_KI_NEWS_SAID"] == 2
    assert news["said"] == ["Imfinzi improved survival in small cell lung cancer (10 Sep)",
                            "AstraZeneca acquires Summit (28 Sep)"]
    assert len(news["full"]) == len(news["tones"]) == 2
    assert news["more"] == 3
    assert view["_ki_month_news"]([], "AZN") == {"said": [], "full": [], "tones": [],
                                                 "more": 0, "slips": 0, "longest": None,
                                                 "quiet": 0}
    # The limit is the caller's: the note rebuilt short asks for one.
    one = view["_ki_month_news"](_month(), "AZN", 1)
    assert one["said"] == ["Imfinzi improved survival in small cell lung cancer (10 Sep)"]
    assert one["more"] == 4


def test_news_the_feed_carries_twice_is_said_once(view):
    deal = _news("press_deal", "AZN AstraZeneca acquires Summit", "2026-09-28")
    news = view["_ki_month_news"]([deal, dict(deal), _news(
        "press_deal", "AZN AstraZeneca licenses X", "2026-09-20")], "AZN")
    assert news["said"] == ["AstraZeneca acquires Summit (28 Sep)",
                            "AstraZeneca licenses X (20 Sep)"]
    assert news["more"] == 0


def test_supplements_are_one_clause_over_the_span_they_were_approved_in(view, board):
    one = view["_ki_month_news"](_month()[:1], "AZN")
    assert one["said"] == ["a new FDA indication for Truqap (16 Sep)"]
    same_day = view["_ki_month_news"]([
        _news("efficacy_supplement", "AZN efficacy supplement: Truqap approved 2026-09-16",
              "2026-09-23"),
        _news("efficacy_supplement", "AZN efficacy supplement: Imfinzi approved 2026-09-16",
              "2026-09-23")], "AZN")
    assert same_day["said"] == ["new FDA indications for Truqap and Imfinzi (16 Sep)"]
    # LLY's month: six supplements over two months, Mounjaro twice; named once each.
    rows = view["_ki_changes"](_saved_feed("LLY"), "LLY", _today(board))
    news = view["_ki_month_news"](rows, "LLY", limit=10)
    assert news["said"][-1] == ("new FDA indications for Olumiant, Inluriyo, Verzenio, "
                                "Mounjaro and Zepbound (26 Aug to 25 Sep)")
    assert "acquisition of ataibeckley" in news["said"][0].lower()
    assert news["full"][0].startswith("Lilly completes acquisition of AtaiBeckley")
    assert news["slips"] == 0 and news["longest"] is None


def test_the_saved_azn_month_says_the_deal_and_the_latest_approval_and_counts_three_slips(
        view, board):
    rows = view["_ki_changes"](_saved_feed("AZN"), "AZN", _today(board))
    news = view["_ki_month_news"](rows, "AZN")
    assert news["said"] == [
        "Strategic equity investment and clinical collaboration with Summit… (28 Sep)",
        "Trixeo approved in the EU for the maintenance treatment of asthma (23 Sep)"]
    # The note model is given each headline whole.
    assert news["full"] == [
        "AstraZeneca announces strategic equity investment and clinical collaboration with "
        "Summit Therapeutics to advance leading ADC combination strategy in cancer (28 Sep)",
        "Trixeo approved in the EU for the maintenance treatment of asthma (23 Sep)"]
    assert news["tones"] == ["", "up"]
    assert (news["slips"], news["longest"], news["more"]) == (3, 364, 3)


def test_with_nothing_rated_high_a_months_releases_and_fda_news_are_said(view):
    """A month whose company news is all rated medium still says its press releases, FDA
    approvals and Medicare news: "none on file" would be false."""
    def medium(change_type, headline, date):
        return dict(_news(change_type, headline, date), significance="medium")

    rows = [medium("press_deal", "AZN AstraZeneca licenses X", "2026-09-20"),
            medium("new_approval", "AZN FDA approval: Newdrug (NDA123456)", "2026-09-05"),
            medium("ira_selected", "AZN Farxiga selected for Medicare negotiation", "2026-09-12"),
            medium("efficacy_supplement", "AZN efficacy supplement: Truqap approved 2026-09-16",
                   "2026-09-23"),
            medium("status_change", "AZN trial NCT1: Phase 2 -> Phase 3", "2026-09-29"),
            medium("new_filing", "AZN 8-K: Material agreement signed", "2026-09-27"),
            # A slip rated high is counted, never said: it does not hold the medium back.
            _news("date_slip", "AZN trial NCT06455449: primary completion slips 2027-05-14 -> "
                               "2028-01-10", "2026-09-25")]
    news = view["_ki_month_news"](rows, "AZN", limit=10)
    assert news["said"] == ["AstraZeneca licenses X (20 Sep)",                # deals and policy
                            "Farxiga selected for Medicare negotiation (12 Sep)",
                            "FDA approval of Newdrug (5 Sep)",
                            "a new FDA indication for Truqap (16 Sep)"]
    assert news["slips"] == 1 and news["quiet"] == 0
    # One item rated high: the medium are not said beside it.
    high = view["_ki_month_news"](rows + [_news("press_deal", "AZN AstraZeneca acquires Y",
                                                "2026-09-02")], "AZN", limit=10)
    assert high["said"] == ["AstraZeneca acquires Y (2 Sep)"]
    # An item with no rating counts as high.
    unrated = {k: v for k, v in _news("press_deal", "AZN AstraZeneca acquires Y",
                                      "2026-09-02").items() if k != "significance"}
    assert view["_ki_month_news"](rows + [unrated], "AZN", limit=10)["said"] == [
        "AstraZeneca acquires Y (2 Sep)"]


def test_a_month_with_only_lower_rated_news_counts_it_as_quiet(view):
    rows = [dict(_news("status_change", "AZN trial NCT1: Phase 2 -> Phase 3", "2026-09-29"),
                 significance="medium"),
            dict(_news("new_filing", "AZN 10-Q: Quarterly report", "2026-09-20"),
                 significance="low"),
            _news("date_slip", "AZN trial NCT06455449: primary completion slips 2027-05-14 -> "
                               "2028-01-10", "2026-09-25")]
    news = view["_ki_month_news"](rows, "AZN")
    assert news["said"] == [] and news["quiet"] == 2     # the slip is not news
    assert news["slips"] == 1


def test_one_clause_on_two_days_is_said_once(view):
    rows = [_news("press_deal", "AZN AstraZeneca acquires Summit", "2026-09-28"),
            _news("press_deal", "AZN AstraZeneca acquires Summit", "2026-09-27")]
    news = view["_ki_month_news"](rows, "AZN", limit=10)
    assert news["said"] == ["AstraZeneca acquires Summit (28 Sep)"] and news["more"] == 0


def test_an_fda_approval_goes_only_where_a_release_already_says_it(view):
    press = _news("press_approval", "AZN Etcamah approved in the US for 1st-line breast cancer",
                  "2026-09-04")
    fda = _news("new_approval", "AZN FDA approval: Etcamah (NDA220359)", "2026-09-04")
    other = _news("new_approval", "AZN FDA approval: Newdrug (NDA123456)", "2026-09-05")
    news = view["_ki_month_news"]([press, fda, other], "AZN", limit=10)
    assert news["said"] == ["FDA approval of Newdrug (5 Sep)",
                            "Etcamah approved in the US for 1st-line breast cancer (4 Sep)"]
    # A release filed as an approval that reports none (a board appointment "toward
    # potential FDA approval") neither stands in for the approval nor ranks as one.
    board_news = _news("press_approval", "AZN AstraZeneca appoints a director to steer Etcamah "
                                         "toward potential FDA approval", "2026-09-06")
    news = view["_ki_month_news"]([board_news, fda,
                                   _news("new_filing", "AZN 8-K: Material agreement signed",
                                         "2026-09-01")], "AZN", limit=10)
    assert news["said"] == [
        "FDA approval of Etcamah (4 Sep)",
        "an 8-K filing (material agreement signed) (1 Sep)",
        "AstraZeneca appoints a director to steer Etcamah toward potential FDA… (6 Sep)"]
    assert news["tones"] == ["up", "", ""]


def test_a_slip_is_one_a_trial_over_its_whole_move_and_never_a_date_already_past(view):
    def slip(nct, old, new, seen):
        return _news("date_slip", f"AZN trial {nct}: primary completion slips {old} -> {new}",
                     seen)

    rows = [slip("NCT00000001", "2027-01-01", "2027-03-01", "2026-09-05"),
            slip("NCT00000001", "2027-03-01", "2027-06-01", "2026-09-20"),   # the same trial
            slip("NCT00000002", "2027-05-01", "2027-06-01", "2026-09-10"),
            # The readout was due before the slip was seen: a correction, not a slip.
            slip("NCT00000003", "2026-08-01", "2027-08-01", "2026-09-12"),
            slip("NCT00000004", "2026-09", "2026-12", "2026-09-15")]          # due that month
    news = view["_ki_month_news"](rows, "AZN")
    assert news["slips"] == 3
    assert news["longest"] == (dt.date(2027, 6, 1) - dt.date(2027, 1, 1)).days   # 151
    assert news["said"] == [] and news["quiet"] == 0
    # A slip whose headline gives no dates still counts, with no length.
    undated = view["_ki_month_news"]([_news("date_slip", "AZN trial NCT1: primary completion "
                                                         "slips", "2026-09-25")], "AZN")
    assert (undated["slips"], undated["longest"]) == (1, None)


def test_the_month_move_is_read_from_the_first_close_inside_the_month(view):
    move = view["_ki_month_move"]
    series = {"dates": ["2026-08-01", "2026-09-01", "2026-09-15", "2026-10-01"],
              "closes": [90.0, 100.0, 105.0, 110.0]}
    assert move(series) == pytest.approx(0.10)
    # No close inside the month before the last one: no move.
    assert move({"dates": ["2026-08-01", "2026-10-01"], "closes": [100.0, 110.0]}) is None
    assert move({"dates": ["2026-10-01"], "closes": [100.0]}) is None
    assert move({}) is None and move(None) is None


def test_the_move_against_the_sector_is_said_in_points(view):
    rel = view["_ki_rel_words"]
    assert rel({"value": -0.24}) == "24 points behind the sector (XLV)"
    assert rel({"value": 0.031}) == "3 points ahead of the sector (XLV)"
    assert rel({"value": 0.004}) == "in line with the sector (XLV)"
    assert rel({"value": None}) == "" and rel(None) == ""


# --- the morning note: the note -------------------------------------------------------------
def _brief(view, ticker="XYZ", **kw):
    args = dict(series={"close": 50.0, "day_move": 0.01}, rated={}, call={}, rel_3m=None,
                rel_1y=None, changes=[], sotp={}, assets={}, breaks={}, events=[], risks=[],
                company={}, cohort={}, street=None, modelled=True, unrated="", failed="",
                rel_1m=None, expiries=None, rating_failed="")
    args.update(kw)
    return view["_ki_brief"](ticker, **args)


def _rated(close=50.0, fwd=60.0, word="Buy", mid=56.0):
    return {"ok": True, "rating": word, "forward_12m": fwd, "upside_12m": fwd / close - 1,
            "value_today": mid}


# Today's value is what is sold and the cash, plus 16.00 for what is ahead: 10.00 of
# launches past the pipeline and 6.00 of pipeline after its chance of approval.
SOTP_AHEAD = {"future": {"per_share": 10.0}, "pipeline": {"per_share": 6.0},
              "net_cash_per_share": 2.0}


def _azn_verdict():
    def asset(i, name, per_share, marketed, **kw):
        return dict(asset_id=i, name=name, per_share=per_share, counted=True,
                    is_marketed=marketed, **kw)

    return {"sotp": {"marketed": {"n": 7, "per_share": 50.0},
                     "pipeline": {"n": 7, "per_share": 20.0}},
            "modelled": [
                asset(1, "Tagrisso", 10.29, True, loe_year=2032, loe_in_base=False),
                asset(2, "Imfinzi", 8.89, True, loe_year=2031, loe_in_base=False),
                asset(3, "Symbicort", 7.04, True, loe_year=None, loe_in_base=True),
                asset(4, "Farxiga", 5.47, True, loe_year=2032, loe_in_base=False),
                asset(5, "Breztri Aerosphere (Inhaler)", 3.27, True, loe_year=2038,
                      loe_in_base=False),
                asset(6, "Small", 1.0, True, loe_year=2030, loe_in_base=False),
                asset(7, "Tiny", 0.5, True),
                asset(11, "Elecoglipron", 4.66, False, pos=0.5537),
                asset(12, "AZD6234", 3.74, False, pos=0.5537),
                asset(13, "Compound C", 3.0, False, pos=0.3),
                asset(14, "Compound D", 2.0, False, pos=0.2),
                asset(15, "Compound E", 1.5, False),
                asset(16, "Compound F", 1.0, False),
                asset(17, "Compound G", 0.5, False),
                dict(asset_id=99, name="Not counted", per_share=50.0, counted=False,
                     is_marketed=True),
                dict(asset_id=97, name="No value", per_share=None, counted=True,
                     is_marketed=True),
                dict(asset_id=98, name="Zero", per_share=0.0, counted=True, is_marketed=True)]}


AZN_EXCLUSIVITIES = [
    {"asset_id": 1, "brand_name": "Tagrisso", "loe": "2032-08-15",
     "loe_basis": "drug substance patent"},
    {"asset_id": 2, "brand_name": "Imfinzi", "loe": "2031-12-31",
     "loe_basis": "AstraZeneca 20-F, U.S. new molecular entity patent (2031)"},
    {"asset_id": 4, "brand_name": "Farxiga", "loe": "2026-04-04", "loe_basis": "compound patent"}]

AZN_PROGRAMMES = [
    {"asset_id": 11, "name": "Elecoglipron", "stage": "Phase 3", "studies": [
        {"phase": "Phase 2", "due": "2026-12-01", "nct_id": "NCT2"},
        {"phase": "Phase 3", "due": "2027-06-04", "nct_id": "NCT3"},
        {"phase": "Phase 3", "due": "2028-01-01", "nct_id": "NCT4"},
        {"phase": "Phase 3", "due": "2026-01-01", "nct_id": "NCT5"}]}]


def _azn_brief(view, board, **kw):
    """The note for AZN as the renderer writes it, from the saved answers."""
    azn = board["companies"]["AZN"]
    today = _today(board)
    series = _azn_series(view)
    rated = dict(AZN_RATED, value_today=181.83, low_today=154.84, high_today=217.60)
    call = view["_ki_call"](rated, None, series, AZN_STREET)
    readouts = view["_ki_readouts"](_ctx("AZN")["catalysts"]["items"], today,
                                    prose=drivers.indication_prose,
                                    min_pct=drivers.DRIVER_MIN_PCT)
    assets = view["_ki_key_assets"](_azn_verdict(), {}, AZN_PROGRAMMES, AZN_EXCLUSIVITIES,
                                    today, True)
    expiries = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, EXPIRY_VERDICT, _expiry_record(),
                                    azn["exclusivity_losses"], today, True)
    return view["_ki_brief"](
        "AZN", series, rated, call, view["_ki_metric"](azn, ("rel_3m",)),
        view["_ki_metric"](azn, ("rel_1y",)),
        view["_ki_changes"](_saved_feed("AZN"), "AZN", today), AZN_SOTP, assets,
        view["_ki_breaks"](AZN_BP), readouts["rows"], [], azn,
        board["cohorts"]["big_pharma"], AZN_STREET, True, rel_1m=-0.03, expiries=expiries,
        **kw)


def test_the_note_reads_the_call_the_trading_then_what_drives_it(view, board):
    brief = _azn_brief(view, board)
    call, trading, drives = brief["paragraphs"]
    # 1. The call, and what the price pays for against the model.
    assert brief["lead"] == "Buy, with a 12-month value of 192.49, 22.1% above the 157.70 close."
    assert call == (
        "Buy, with a 12-month value of 192.49, 22.1% above the 157.70 close. The price pays "
        "for the products on sale net of debt (80.75) and 76% of the model's 101.08 for the "
        "pipeline and future launches, leaving 24.13 a share unpriced.")
    # 2. The trading against the sector, the month's news beside it, the slips counted.
    # With two pieces of news the note runs past _KI_NOTE_WORDS, so it is rebuilt with one.
    assert trading == (
        "The shares are down 0.5% this month and 6.0% over the year, 18 points behind the "
        "sector (XLV). The month's news: Strategic equity investment and clinical "
        "collaboration with Summit… (28 Sep). Three late-stage readouts slipped, the "
        "longest by 12 months.")
    assert "NCT" not in trading
    # 3. What the value rests on and what breaks it, what the readouts test, the nearest
    # loss of exclusivity, and the standing against the cohort.
    assert drives == (
        "The value rests on 88.76 a share of launches past the pipeline, Tagrisso (10.29, "
        "protected to Aug 2032) and Imfinzi (8.89, protected to 2031); the call holds while "
        "every discount rate stays below 8.35% (7.47% now). The next readouts, Truqap, "
        "Saphnelo and Enhertu (by est. Nov 2026), extend products already sold rather than "
        "test the pipeline; the nearest loss of exclusivity, Farxiga on 4 Apr 2027, is 8.0% "
        "of revenue. It ranks 7th of 18 big pharma: growth 4th best but operating margin "
        "3rd worst, growth bought at the cost of margin.")
    assert sum(len(p.split()) for p in brief["paragraphs"]) <= view["_KI_NOTE_WORDS"] == 180


def test_a_note_over_its_length_is_rebuilt_with_one_piece_of_news(view, board):
    """The AZN note with both of its month's headlines runs past 180 words: the rebuilt
    note says the first and leaves the rest to News."""
    built = _azn_brief(view, board)
    once = _azn_brief(view, board, news_said=1)
    assert built == once
    second = "; Trixeo approved in the EU for the maintenance treatment of asthma (23 Sep)"
    assert second[2:] not in built["paragraphs"][1]
    words = sum(len(p.split()) for p in built["paragraphs"])
    assert words <= view["_KI_NOTE_WORDS"] < words + len(second.split())
    assert [f for f in built["facts"].splitlines() if f.startswith("news: ")] == [
        "news: AstraZeneca announces strategic equity investment and clinical collaboration "
        "with Summit Therapeutics to advance leading ADC combination strategy in cancer "
        "(28 Sep)"]
    # A note inside its length keeps two.
    short = _brief(view, "AZN", series=_trading(-0.029, -0.065), changes=GOOD + BAD)
    assert ("Drugy did not meet its primary endpoint (12 Sep); Drugx approved in the EU for "
            "asthma (10 Sep)") in short["paragraphs"][1]


def test_the_facts_carry_every_figure_whole_and_keep_est_on_estimated_dates(view, board):
    facts = _azn_brief(view, board)["facts"].splitlines()
    for fact in (
            "rating: Buy; 12-month value 192.49, +22.1% on the close 157.70",
            "today's value 181.83: the products on sale net of debt 80.75, pipeline and "
            "future launches 101.08; the price implies 76.95 for the pipeline and launches",
            "day move −2.3%", "one-month move −0.5%", "one-year move −6.0%",
            "one year against the sector: 18 points behind the sector (XLV)",
            "three months against the sector: 21 points behind the sector (XLV)",
            "one month against the sector: −3.0%",
            # The headline the page cuts is given whole.
            "news: AstraZeneca announces strategic equity investment and clinical "
            "collaboration with Summit Therapeutics to advance leading ADC combination "
            "strategy in cancer (28 Sep)",
            "late-stage readouts that slipped this month: 3, longest 12 months",
            "value rests on: launches 88.76", "value rests on: Tagrisso 10.29, Aug 2032",
            # Only the nearest break is said, and only it is given.
            "break lever: every discount rate 7.47% now, breaks at 8.35%",
            # An estimated date keeps its est.
            "readout: Truqap Phase 3 readout in breast neoplasms (est. Oct 2026)",
            "risk: Farxiga loses exclusivity 4 Apr 2027, 8.0% of revenue",
            "peer rank: 7th of 18 big pharma; growth 4th best but operating margin 3rd worst"):
        assert fact in facts, fact
    assert not [f for f in facts if "…" in f]
    assert not [f for f in facts if f.startswith("break lever: launch productivity")]


@pytest.mark.parametrize("close, mid, net, judgement", [
    # The price covers what is sold and part of what is ahead: the rest is unpriced.
    (50.0, 56.0, 2.0,
     "The price pays for the products on sale and net cash (40.00) and 62% of the model's "
     "16.00 for the pipeline and future launches, leaving 6.00 a share unpriced."),
    (50.0, 56.0, -3.0,
     "The price pays for the products on sale net of debt (40.00) and 62% of the model's "
     "16.00 for the pipeline and future launches, leaving 6.00 a share unpriced."),
    # The price is under what is sold: it gives nothing for what is ahead.
    (38.0, 56.0, 2.0,
     "The price is below the 40.00 of the products on sale and net cash, so it gives nothing "
     "for the 16.00 the model puts on the pipeline and future launches."),
    # The price asks more for what is ahead than the model gives it.
    (70.0, 56.0, 2.0,
     "After 40.00 for the products on sale and net cash, the price asks 30.00 for the "
     "pipeline and future launches, 1.9 times the model's 16.00."),
    # Debt outweighs what is sold: the price is all pipeline and launches.
    (50.0, 15.0, -30.0,
     "Debt outweighs the products on sale, so the price is a bet on the pipeline and future "
     "launches, which the model puts at 16.00 a share."),
])
def test_the_note_says_what_the_price_pays_for_against_the_model(view, close, mid, net,
                                                                  judgement):
    word = "Buy" if close < 60.0 else "Sell"
    brief = _brief(view, series={"close": close}, rated=_rated(close, 60.0, word, mid),
                   sotp=dict(SOTP_AHEAD, net_cash_per_share=net))
    side = "above" if close < 60.0 else "below"
    lead = (f"{word}, with a 12-month value of 60.00, {abs(60.0 / close - 1) * 100:.1f}% "
            f"{side} the {close:,.2f} close.")
    assert brief["lead"] == lead
    assert brief["paragraphs"][0] == f"{lead} {judgement}"
    implied = view["_ki_money"](close - (mid - 16.0))
    assert (f"pipeline and future launches 16.00; the price implies {implied} for the "
            "pipeline and launches") in brief["facts"]


def test_without_todays_value_or_anything_ahead_the_call_stands_alone(view):
    bare = _brief(view, rated=dict(_rated(), value_today=None), sotp=SOTP_AHEAD)
    assert bare["paragraphs"][0] == bare["lead"] == (
        "Buy, with a 12-month value of 60.00, 20.0% above the 50.00 close.")
    nothing_ahead = _brief(view, rated=_rated(), sotp={"net_cash_per_share": 2.0})
    assert nothing_ahead["paragraphs"][0] == nothing_ahead["lead"]
    assert "today's value" not in nothing_ahead["facts"]
    unworded = _brief(view, rated=dict(_rated(), rating=None))
    assert unworded["lead"] == "A 12-month value of 60.00, 20.0% above the 50.00 close."


def test_a_rated_note_with_no_price_on_file_never_prints_a_dot_for_the_close(view):
    """The prices read failed: the close is the rating's own, as the fair value carries it."""
    brief = _brief(view, series={}, rated=dict(_rated(), close=50.0))
    assert "·" not in brief["paragraphs"][0]
    assert brief["lead"] == "Buy, with a 12-month value of 60.00, 20.0% above the 50.00 close."
    # The series' close, where there is one, is the close.
    assert "the 51.00 close" in _brief(view, series={"close": 51.0},
                                       rated=dict(_rated(), close=50.0))["lead"]


def test_a_model_that_values_nothing_on_sale_says_what_its_value_is(view):
    """With no product on sale valued, a price-implied split would set the price against net
    cash and the pipeline alone: the note says what the value is made of instead."""
    sotp = {"marketed": {"n": 0, "per_share": 0.0}, "pipeline": {"n": 3, "per_share": 0.58},
            "future": {"per_share": 0.52}, "net_cash_per_share": 16.24}
    assets = {"pipeline": _asset_rows(("Lead", 0.58, "Ph 2 · Mar 2027", "pipeline"))}
    brief = _brief(view, series={"close": 15.0}, rated=_rated(15.0, 18.0, "Buy", 17.34),
                   sotp=sotp, assets=assets)
    assert brief["paragraphs"][0] == (
        "Buy, with a 12-month value of 18.00, 20.0% above the 15.00 close. The model values "
        "none of the products on sale: its value is net cash (16.24 a share), the pipeline "
        "(0.58) and future launches (0.52).")
    assert "the model values none of the products on sale" in brief["facts"].splitlines()
    assert "the price implies" not in brief["facts"]
    assert not [p for p in brief["paragraphs"] if "The value rests on" in p]
    # Only the parts on file are named.
    bare = _brief(view, series={"close": 15.0}, rated=_rated(15.0, 18.0, "Buy", 16.24),
                  sotp={"marketed": {"n": 0}, "net_cash_per_share": 16.24})
    assert bare["paragraphs"][0].endswith(
        "The model values none of the products on sale: its value is net cash (16.24 a share).")


def test_a_model_short_of_revenue_says_how_much_of_it_is_not_in_the_value(view):
    sotp = dict(SOTP_AHEAD, marketed={"n": 5, "per_share": 30.0})
    brief = _brief(view, rated=_rated(), sotp=sotp, coverage={"share": 0.72})
    assert brief["paragraphs"][0].endswith(
        "leaving 6.00 a share unpriced. The model covers 72% of revenue, so 28% of it is not "
        "in the value.")
    assert "the model covers 72% of revenue" in brief["facts"].splitlines()
    # Nine tenths or more is the business; nothing is said.
    for share in (0.9, 0.97):
        full = _brief(view, rated=_rated(), sotp=sotp, coverage={"share": share})
        assert "covers" not in full["paragraphs"][0]
    assert "covers" not in _brief(view, rated=_rated(), sotp=sotp)["paragraphs"][0]


def test_modelled_but_unrated_says_why_and_is_never_called_not_modelled(view):
    brief = _brief(view, rated={"ok": False, "reason": "no share price on file"},
                   street={"value": 60.0}, unrated="not used")
    assert brief["paragraphs"][0] == (
        "The model gives XYZ no 12-month value (no share price on file). The street's mean "
        "target is 60.00, up 20.0% on the 50.00 close.")
    assert brief["lead"] == "The model gives XYZ no 12-month value (no share price on file)."
    facts = brief["facts"].splitlines()
    assert "no 12-month value: no share price on file" in facts
    assert "street target 60.00" in facts
    # The fair value's own reason, else the one the page was given, else a plain one.
    given = _brief(view, rated={}, unrated="no sum of the parts on file.")
    assert given["paragraphs"][0] == (
        "The model gives XYZ no 12-month value (no sum of the parts on file).")
    plain = _brief(view, rated={})
    assert plain["paragraphs"][0] == (
        "The model gives XYZ no 12-month value (no value against the price is on file).")
    for b in (brief, given, plain):
        assert "not modelled" not in " ".join(b["paragraphs"])


def test_a_rating_that_did_not_load_says_so_and_does_not_fall_back_to_the_street(view):
    brief = _brief(view, rating_failed="timed out.", street={"value": 60.0})
    assert brief["paragraphs"][0] == brief["lead"] == (
        "The rating did not load (timed out), so the note has no 12-month value to set "
        "against the price.")
    assert "rating: did not load" in brief["facts"].splitlines()
    assert "street" not in brief["paragraphs"][0] and "not modelled" not in brief["paragraphs"][0]


@pytest.mark.parametrize("sotp, shares, reason", [
    ({"net_cash": None}, 100.0, "net cash is not on file"),
    ({"close": None}, 100.0, "the close is not on file"),
    ({}, None, "the share count is not on file"),
    ({"equity_per_share": None}, 100.0, "equity is not on file"),
    ({"enterprise": None}, 100.0, "enterprise value is not on file"),
    ({"enterprise": 0.0}, 100.0, "enterprise value is not on file"),
    # Equity is not asked for where net cash, which it is built from, is the gap.
    ({"net_cash": None, "equity_per_share": None}, 100.0, "net cash is not on file"),
    ({"close": None, "net_cash": None}, None,
     "the close, the share count and net cash are not on file"),
])
def test_the_unrated_reason_names_what_is_missing(monkeypatch, sotp, shares, reason):
    """The page beside the note shows the close and a market value, so "equity, shares or
    the close is not on file" read as a contradiction: the reason names the gap, which is
    usually the balance sheet."""
    import breakpoints

    full = {"close": 50.0, "equity_per_share": 40.0, "enterprise": 4000.0, "net_cash": 100.0}
    verdict = {"ticker": "XYZ", "name": "XYZ", "diluted_shares": shares,
               "sotp": dict(full, **sotp)}
    monkeypatch.setattr(breakpoints.V, "company_verdict", lambda path, ticker: verdict)
    book = breakpoints.Book(None, "XYZ")
    assert not book.ok
    assert book.reason == f"no value against a price: {reason}"


def test_a_forecast_that_did_not_load_is_said_to_have_failed(view):
    brief = _brief(view, modelled=False, failed="timed out", street={"value": 60.0})
    assert brief["paragraphs"][0] == brief["lead"] == (
        "The forecast did not load (timed out), so the note has no value to set against the "
        "price.")
    assert "not modelled" not in " ".join(brief["paragraphs"])
    assert "forecast: did not load" in brief["facts"]


def test_a_company_not_modelled_reads_the_street_or_says_there_is_none(view):
    street = _brief(view, modelled=False, street={"value": 60.0})
    assert street["paragraphs"][0] == ("XYZ is not modelled. The street's mean target is "
                                       "60.00, up 20.0% on the 50.00 close.")
    assert street["lead"] == "XYZ is not modelled."
    assert "not modelled; street target 60.00" in street["facts"]
    none = _brief(view, modelled=False)
    assert none["paragraphs"][0] == "XYZ is not modelled and no consensus is on file."
    assert "not modelled; no consensus on file" in none["facts"]


def test_with_nothing_else_to_say_the_note_reads_the_business_row(view):
    """Not modelled and no consensus: the note says it reads the price and the business,
    and its third paragraph is the business row as a sentence."""
    verdict = {"reported_revenue": [{"fiscal_year": 2023, "value": 60.27},
                                    {"fiscal_year": 2024, "value": 178.0}]}
    business = view["_ki_business_figures"]({"reporting_currency": "USD"}, verdict, None,
                                            False, [])
    assert view["_ki_business_line"](business) == (
        "It reports $178mm of revenue for FY2024 (+195.3%).")
    brief = _brief(view, modelled=False, business=business)
    assert brief["paragraphs"][0] == (
        "XYZ is not modelled and no consensus is on file, so the note reads the price and "
        "the business only.")
    assert brief["paragraphs"][2] == "It reports $178mm of revenue for FY2024 (+195.3%)."
    assert "business: It reports $178mm of revenue for FY2024 (+195.3%)" in brief["facts"]
    # The whole row.
    full = view["_ki_business_figures"](_business_record(), AZN_REVENUE, None, False,
                                        EXPIRY_EXCLUSIVITIES)
    assert view["_ki_business_line"](full) == (
        "It reports $58.7bn of revenue for FY2025 (+8.6%), with 5 approved products and 90 "
        "compounds in trials, 23 of them late-stage.")
    # A row of dots says nothing, so the note does not claim to read it.
    dots = view["_ki_business_figures"]({}, {}, None, False, None)
    assert view["_ki_business_line"](dots) == ""
    assert _brief(view, modelled=False, business=dots)["paragraphs"][0] == (
        "XYZ is not modelled and no consensus is on file.")
    # Something else to say in the third paragraph: the business line is not added.
    company = {"rank": 3, "ranked_of": 18}
    ranked = _brief(view, modelled=False, business=business, company=company,
                    cohort={"noun": "big pharma"})
    assert ranked["paragraphs"][2] == "It ranks 3rd of 18 big pharma."


def test_a_street_target_on_file_is_never_said_to_be_missing(view):
    """Not modelled, a street target on file but no price series: the target is said, with
    no move against a close the page does not have."""
    brief = _brief(view, modelled=False, series={}, street={"value": 60.0})
    assert "no consensus" not in brief["paragraphs"][0]
    assert brief["paragraphs"][0] == "XYZ is not modelled. The street's mean target is 60.00."
    assert "not modelled; street target 60.00" in brief["facts"]


def _trading(month, year):
    """A series whose move over the month is ``month`` and over the year ``year``."""
    last = 100.0 * (1 + month)
    return {"close": last, "day_move": 0.0, "year_move": year,
            "dates": ["2026-08-01", "2026-09-01", "2026-10-01"],
            "closes": [90.0, 100.0, last]}


GOOD = [_news("press_approval", "AZN Drugx approved in the EU for asthma", "2026-09-10")]
BAD = [_news("press_data_readout", "AZN Drugy did not meet its primary endpoint", "2026-09-12")]
DEAL = [_news("press_deal", "AZN AstraZeneca acquires Smallco", "2026-09-10")]


@pytest.mark.parametrize("month, year, changes, rel_1m, said", [
    # Down on good news, behind the sector (or with no month's relative on file): the news
    # is set against the move.
    (-0.029, -0.065, GOOD, None,
     "The shares are down 2.9% this month and 6.5% over the year, 6 points behind the sector "
     "(XLV). The fall came despite the month's news: Drugx approved in the EU for asthma "
     "(10 Sep)."),
    (-0.029, -0.065, GOOD, -0.03,
     "The shares are down 2.9% this month and 6.5% over the year, 6 points behind the sector "
     "(XLV). The fall came despite the month's news: Drugx approved in the EU for asthma "
     "(10 Sep)."),
    # A fall the sector shared is not one the news failed to stop: set down plain.
    (-0.029, -0.065, GOOD, -0.005,
     "The shares are down 2.9% this month and 6.5% over the year, 6 points behind the sector "
     "(XLV). The month's news: Drugx approved in the EU for asthma (10 Sep)."),
    # Up on good news, not behind the sector: beside it.
    (0.03, 0.10, GOOD, None,
     "The shares are up 3.0% this month and 10.0% over the year, 6 points behind the sector "
     "(XLV). The rise came with the month's news: Drugx approved in the EU for asthma "
     "(10 Sep)."),
    (0.03, 0.10, GOOD, 0.02,
     "The shares are up 3.0% this month and 10.0% over the year, 6 points behind the sector "
     "(XLV). The rise came with the month's news: Drugx approved in the EU for asthma "
     "(10 Sep)."),
    (0.03, 0.10, GOOD, -0.005,
     "The shares are up 3.0% this month and 10.0% over the year, 6 points behind the sector "
     "(XLV). The rise came with the month's news: Drugx approved in the EU for asthma "
     "(10 Sep)."),
    # A rise that trailed the sector did not come with the news: set down plain.
    (0.03, 0.10, GOOD, -0.03,
     "The shares are up 3.0% this month and 10.0% over the year, 6 points behind the sector "
     "(XLV). The month's news: Drugx approved in the EU for asthma (10 Sep)."),
    # Down on bad news: alongside, never because, whatever the sector did.
    (-0.029, -0.065, BAD, None,
     "The shares are down 2.9% this month and 6.5% over the year, 6 points behind the sector "
     "(XLV). The fall came alongside the month's news: Drugy did not meet its primary "
     "endpoint (12 Sep)."),
    (-0.029, -0.065, BAD, 0.01,
     "The shares are down 2.9% this month and 6.5% over the year, 6 points behind the sector "
     "(XLV). The fall came alongside the month's news: Drugy did not meet its primary "
     "endpoint (12 Sep)."),
    (-0.029, -0.065, GOOD + BAD, None,
     "The shares are down 2.9% this month and 6.5% over the year, 6 points behind the sector "
     "(XLV). The fall came alongside the month's news: Drugy did not meet its primary "
     "endpoint (12 Sep); Drugx approved in the EU for asthma (10 Sep)."),
    # Up on bad news, a move inside a point, or news that reads neither way: set down plain.
    (0.03, -0.065, BAD, None,
     "The shares are up 3.0% this month and down 6.5% over the year, 6 points behind the "
     "sector (XLV). The month's news: Drugy did not meet its primary endpoint (12 Sep)."),
    (-0.005, 0.05, GOOD, None,
     "The shares are down 0.5% this month and up 5.0% over the year, 6 points behind the "
     "sector (XLV). The month's news: Drugx approved in the EU for asthma (10 Sep)."),
    (-0.029, 0.05, DEAL, None,
     "The shares are down 2.9% this month and up 5.0% over the year, 6 points behind the "
     "sector (XLV). The month's news: AstraZeneca acquires Smallco (10 Sep)."),
])
def test_the_months_news_is_set_beside_the_move_never_behind_it(view, month, year, changes,
                                                                 rel_1m, said):
    brief = _brief(view, "AZN", series=_trading(month, year), changes=changes,
                   rel_1y={"value": -0.06}, rel_1m=rel_1m)
    assert brief["paragraphs"][1] == said
    assert not [w for w in CAUSAL if w in said.lower()]


def test_with_no_price_the_months_news_is_said_alone(view):
    assert _brief(view, "AZN", series={}, changes=GOOD)["paragraphs"][1] == (
        "The month's news: Drugx approved in the EU for asthma (10 Sep).")
    assert _brief(view, series={})["paragraphs"][1] == "No company news is on file for the month."
    flat = _brief(view, series=_trading(0.0, 0.0))["paragraphs"][1]
    assert flat == "The shares are flat this month and flat over the year. No company news is " \
                   "on file for the month."


def test_the_years_relative_is_never_set_beside_the_months_move(view):
    """Under a year of prices, a one-year relative on file is not said beside the month."""
    para = _brief(view, series=_trading(-0.029, None), rel_1y={"value": -0.06})["paragraphs"][1]
    assert "this month, 6 points" not in para
    assert para == "The shares are down 2.9% this month. No company news is on file for the month."
    # A point is singular.
    one = _brief(view, series=_trading(-0.029, -0.065), rel_1y={"value": 0.01})["paragraphs"][1]
    assert one.startswith("The shares are down 2.9% this month and 6.5% over the year, 1 point "
                          "ahead of the sector (XLV).")
    assert (view["_ki_points"](1), view["_ki_points"](2)) == ("1 point", "2 points")


@pytest.mark.parametrize("rel_1m, line, fact", [
    (0.015, "With no company news on file, the month's move is the sector's.",
     "news: none on file; the month in line with the sector"),
    (-0.02, "With no company news on file, the month's move is the sector's.",
     "news: none on file; the month in line with the sector"),
    (0.05, "No company news is on file for a month 5 points ahead of the sector.",
     "news: none on file for the month"),
    (-0.04, "No company news is on file for a month 4 points behind the sector.",
     "news: none on file for the month"),
    (None, "No company news is on file for the month.", "news: none on file for the month"),
])
def test_with_no_news_the_month_is_read_against_the_sector(view, rel_1m, line, fact):
    brief = _brief(view, series=_trading(-0.029, -0.065), rel_1m=rel_1m)
    assert brief["paragraphs"][1] == (
        f"The shares are down 2.9% this month and 6.5% over the year. {line}")
    facts = brief["facts"].splitlines()
    assert fact in facts
    if rel_1m is not None:
        assert f"one month against the sector: {view['_ki_signed_pct'](rel_1m)}" in facts


@pytest.mark.parametrize("rel_1m, line", [
    (None, "None of the month's company news is rated high."),
    (0.015, "None of the month's company news is rated high, and the month's move is the "
            "sector's."),
    (-0.02, "None of the month's company news is rated high, and the month's move is the "
            "sector's."),
    (0.05, "None of the month's company news is rated high, in a month 5 points ahead of the "
           "sector."),
    (-0.03, "None of the month's company news is rated high, in a month 3 points behind the "
            "sector."),
    (-0.04, "None of the month's company news is rated high, in a month 4 points behind the "
            "sector."),
])
def test_a_month_of_lower_rated_news_is_never_called_a_month_without_news(view, rel_1m, line):
    medium = [dict(_news("status_change", "AZN trial NCT1: Phase 2 -> Phase 3", "2026-09-10"),
                   significance="medium")]
    brief = _brief(view, series=_trading(-0.029, -0.065), changes=medium, rel_1m=rel_1m)
    assert brief["paragraphs"][1] == (
        f"The shares are down 2.9% this month and 6.5% over the year. {line}")
    assert "news: none rated high this month" in brief["facts"].splitlines()
    assert "No company news" not in brief["paragraphs"][1]


def test_the_saved_crsp_month_has_no_news_and_says_so(view, board):
    rows = view["_ki_changes"](_saved_feed("CRSP"), "CRSP", _today(board))
    brief = _brief(view, "CRSP", changes=rows)
    assert brief["paragraphs"][1] == "No company news is on file for the month."
    assert "news: none on file for the month" in brief["facts"]


def test_slipped_late_stage_readouts_are_counted_with_the_longest(view):
    two = _brief(view, "AZN", changes=_month())
    assert two["paragraphs"][1].endswith(
        "Two late-stage readouts slipped, the longest by 8 months.")            # 241 days
    assert "late-stage readouts that slipped this month: 2, longest 8 months" in two["facts"]
    one = _brief(view, "AZN", changes=_month()[7:8])
    assert one["paragraphs"][1] == ("No company news is on file for the month. One late-stage "
                                    "readout slipped, by 8 months.")
    undated = _brief(view, "AZN", changes=[_news(
        "date_slip", "AZN trial NCT06455449: primary completion slips", "2026-09-25")])
    assert undated["paragraphs"][1].endswith("One late-stage readout slipped.")
    many = _brief(view, "AZN", changes=[_news(
        "date_slip", f"AZN trial NCT{i:08d}: primary completion slips 2027-01-01 -> "
                     f"2027-03-{i + 1:02d}", "2026-09-25") for i in range(11)])
    assert many["paragraphs"][1].endswith("11 late-stage readouts slipped, the longest by "
                                          "2 months.")                          # 69 days
    short = _brief(view, "AZN", changes=[_news(
        "date_slip", "AZN trial NCT06455449: primary completion slips 2027-05-14 -> 2027-06-01",
        "2026-09-25")])
    assert short["paragraphs"][1].endswith("One late-stage readout slipped, by 18 days.")


@pytest.mark.parametrize("days, words", [
    (1, "1 day"), (18, "18 days"), (59, "59 days"),       # under 60 days, in days
    (60, "2 months"), (241, "8 months"), (364, "12 months"), (729, "24 months"),
    (730, "2 years"), (1100, "3 years"), (800, "2.2 years"), (None, "")])
def test_a_slip_is_said_at_the_scale_a_reader_thinks_in(view, days, words):
    assert view["_ki_span_words"](days) == words


def _asset_rows(*rows):
    return {"rows": [dict(zip(("name", "value", "meta", "kind"), r)) for r in rows]}


def test_the_value_rests_on_its_three_largest_legs_each_with_its_figure(view):
    assets = {"marketed": _asset_rows(("Alpha", 8.0, "Mar 2031", "marketed"),
                                      ("Beta", 2.0, "lapsed", "marketed")),
              "pipeline": _asset_rows(("Delta", 6.0, "Ph 3 · Apr 2028", "pipeline"),
                                      ("Eps", 1.0, "", "pipeline"))}
    brief = _brief(view, assets=assets, sotp={"future": {"per_share": 3.0},
                                              "net_cash_per_share": 7.0})
    # Net cash and a pipeline compound are legs like any product.
    assert brief["paragraphs"][2] == (
        "The value rests on Alpha (8.00, protected to Mar 2031), 7.00 a share of net cash and "
        "Delta (6.00 after its chance of approval).")
    facts = brief["facts"].splitlines()
    assert facts[-3:] == ["value rests on: Alpha 8.00, Mar 2031", "value rests on: cash 7.00",
                          "value rests on: Delta 6.00, Ph 3 · Apr 2028"]
    # A product past its LOE says so; launches past the pipeline are a leg; net debt is not.
    lapsed = {"marketed": _asset_rows(("Beta", 9.0, "lapsed", "marketed"),
                                      ("Gamma", 4.0, "", "marketed"))}
    para = _brief(view, assets=lapsed, sotp={"future": {"per_share": 5.0},
                                             "net_cash_per_share": -2.0})["paragraphs"][2]
    assert para == ("The value rests on Beta (9.00, past its LOE), 5.00 a share of launches "
                    "past the pipeline and Gamma (4.00).")
    # Only the two largest of each part are legs, and a compound with no value is none.
    third = {"marketed": _asset_rows(("A", 5.0, "", "marketed"), ("B", 4.0, "", "marketed"),
                                     ("C", 3.9, "", "marketed")),
             "pipeline": _asset_rows(("P", None, "Ph 3 · Nov 2026", "pipeline"))}
    assert _brief(view, assets=third)["paragraphs"][2] == (
        "The value rests on A (5.00) and B (4.00).")
    # Not modelled, nothing rests on a model.
    assert len(_brief(view, modelled=False, assets=assets)["paragraphs"]) == 2


def test_a_leg_is_said_once_and_never_beside_its_own_loss_of_exclusivity(view):
    # One product listed twice, or as a compound too, is one leg.
    dup = {"marketed": _asset_rows(("Alpha", 8.0, "Mar 2031", "marketed"),
                                   ("Alpha", 8.0, "Mar 2031", "marketed")),
           "pipeline": _asset_rows(("Alpha", 6.0, "", "pipeline"))}
    assert _brief(view, assets=dup)["paragraphs"][2] == (
        "The value rests on Alpha (8.00, protected to Mar 2031).")
    # A product whose loss of exclusivity the note names below is not said to be protected.
    assets = {"marketed": _asset_rows(("Alpha", 8.0, "Mar 2031", "marketed"),
                                      ("Beta", 2.0, "lapsed", "marketed")),
              "pipeline": _asset_rows(("Delta", 6.0, "Ph 3 · Apr 2028", "pipeline"))}
    alpha = {"asset": "Alpha", "when": "8 Sep 2027", "date": "2027-09-08",
             "share_text": "5.6%", "share": 0.056}
    assert _brief(view, assets=assets, expiries={"rows": [alpha]})["paragraphs"][2] == (
        "The value rests on Alpha (8.00), Delta (6.00 after its chance of approval) and Beta "
        "(2.00, past its LOE). The nearest loss of exclusivity, Alpha on 8 Sep 2027, is 5.6% "
        "of revenue.")


def test_the_call_holds_while_its_nearest_lever_stays_on_its_side(view):
    """One break, the nearest: a second lever made the sentence a list."""
    assets = {"marketed": _asset_rows(("Tagrisso", 10.29, "Aug 2032", "marketed"))}
    holds = _brief(view, rated=_rated(), assets=assets, breaks=view["_ki_breaks"](AZN_BP))
    assert holds["paragraphs"][2] == (
        "The value rests on Tagrisso (10.29, protected to Aug 2032); the call holds while "
        "every discount rate stays below 8.35% (7.47% now).")
    facts = holds["facts"].splitlines()
    assert "break lever: every discount rate 7.47% now, breaks at 8.35%" in facts
    assert not [f for f in facts if f.startswith("break lever: launch productivity")]
    needs = _brief(view, rated=_rated(), assets=assets,
                   breaks=view["_ki_breaks"](dict(AZN_BP, direction="up")))
    assert needs["paragraphs"][2] == (
        "The value rests on Tagrisso (10.29, protected to Aug 2032); to justify the price the "
        "model would need every discount rate at 8.35% against 7.47% now.")
    # The model's figure drops the unit the break-point beside it already says.
    launch = dict(AZN_BP, levers=AZN_BP["levers"][:1])
    holds = _brief(view, rated=_rated(), assets=assets, breaks=view["_ki_breaks"](launch))
    assert holds["paragraphs"][2] == (
        "The value rests on Tagrisso (10.29, protected to Aug 2032); the call holds while "
        "launch productivity stays above 0.312 per R&D $ (0.364 now).")
    # The facts keep both units whole.
    assert ("break lever: launch productivity 0.364 per R&D $ now, breaks at 0.312 per R&D $"
            in holds["facts"].splitlines())
    needs = _brief(view, rated=_rated(), assets=assets,
                   breaks=view["_ki_breaks"](dict(launch, direction="up")))
    assert needs["paragraphs"][2].endswith(
        "to justify the price the model would need launch productivity at 0.312 per R&D $ "
        "against 0.364 now.")
    # With nothing to rest on, the clause is its own sentence.
    alone = _brief(view, rated=_rated(), breaks=view["_ki_breaks"](AZN_BP))["paragraphs"][2]
    assert alone == "The call holds while every discount rate stays below 8.35% (7.47% now)."
    # Unrated, there is no call to hold.
    unrated = _brief(view, assets=assets, breaks=view["_ki_breaks"](AZN_BP))
    assert unrated["paragraphs"][2] == "The value rests on Tagrisso (10.29, protected to Aug 2032)."
    assert "break lever" not in unrated["facts"]


@pytest.mark.parametrize("model, brk, said", [
    ("0.362 per R&D $", "0.307 per R&D $", "0.362"),
    ("−0.364 per R&D $", "0.307 per R&D $", "−0.364"),
    ("7.47%", "8.35%", "7.47%"),                    # a percent is part of the figure
    ("4y", "4.5y", "4y"),
    ("$1,200mm", "$1,500mm", "$1,200mm"),
    ("×1.10", "×1.20", "×1.10"),
    ("2031", "2030", "2031"),
    ("", "0.307 per R&D $", ""), (None, None, "")])
def test_a_lever_figure_says_its_unit_once(view, model, brk, said):
    assert view["_ki_unit_once"](model, brk) == said


def test_the_next_readouts_say_whether_they_test_the_pipeline(view, board):
    today = _today(board)

    def readouts(ticker):
        return view["_ki_readouts"](_ctx(ticker)["catalysts"]["items"], today,
                                    prose=drivers.indication_prose,
                                    min_pct=drivers.DRIVER_MIN_PCT)["rows"]

    # AZN's next three are all products on sale.
    sold = _brief(view, "AZN", modelled=False, events=readouts("AZN"))
    assert sold["paragraphs"][2] == (
        "The next readouts, Truqap, Saphnelo and Enhertu (by est. Nov 2026), extend products "
        "already sold rather than test the pipeline.")
    # LLY's second is a compound in trials: the first of those is the test, with its value.
    assets = {"pipeline": _asset_rows(("Retatrutide", 25.3, "Ph 3 · Nov 2026", "pipeline"))}
    lly = _brief(view, "LLY", modelled=False, events=readouts("LLY"), assets=assets)
    assert lly["paragraphs"][2] == (
        "The Phase 3 readout for Retatrutide (est. Nov 2026) is the next test of the "
        "pipeline, 25.30 a share in the model.")
    assert ("readout: Retatrutide Phase 3 readout in obesity (est. Nov 2026), pipeline"
            in lly["facts"].splitlines())
    unvalued = _brief(view, "LLY", modelled=False, events=readouts("LLY"))
    assert unvalued["paragraphs"][2] == (
        "The Phase 3 readout for Retatrutide (est. Nov 2026) is the next test of the pipeline.")
    # Already a leg of the value, its figure is not said twice.
    leg = _brief(view, "LLY", events=readouts("LLY"), assets=assets)
    assert leg["paragraphs"][2] == (
        "The value rests on Retatrutide (25.30 after its chance of approval). The Phase 3 "
        "readout for Retatrutide (est. Nov 2026) is the next test of the pipeline.")
    # A regulatory date on a compound is a test of the pipeline too; one compound twice is
    # named once; only the next three count.
    events = [{"date": "2026-11-01", "asset": "Dup", "date_text": "est. Nov 2026"},
              {"date": "2026-11-15", "asset": "Dup", "date_text": "est. Nov 2026"},
              {"date": "2026-12", "asset": "Other", "date_text": "Dec 2026"},
              {"date": "2027-01-10", "asset": "Baxdrostat", "pipeline": True,
               "event": "PDUFA date", "date_text": "10 Jan 2027"}]
    assert _brief(view, modelled=False, events=events)["paragraphs"][2] == (
        "The next readouts, Dup and Other (by Dec 2026), extend products already sold rather "
        "than test the pipeline.")
    assert _brief(view, modelled=False, events=events[3:])["paragraphs"][2] == (
        "The PDUFA date for Baxdrostat (10 Jan 2027) is the next test of the pipeline.")
    # One product named: one readout, in the singular.
    assert _brief(view, modelled=False, events=events[:2])["paragraphs"][2] == (
        "The next readout, Dup (est. Nov 2026), extends a product already sold rather than "
        "testing the pipeline.")


def test_the_pipelines_next_test_is_the_one_the_value_turns_on_in_the_soonest_month(view):
    def ev(date, asset, event, short, text):
        return {"date": date, "asset": asset, "pipeline": True, "event": event,
                "short": short, "date_text": text}

    ph3 = ev("2026-11-20", "Ph3drug", "Phase 3 readout", "Ph 3", "est. Nov 2026")
    ph2 = ev("2026-11-05", "Ph2drug", "Phase 2 readout", "Ph 2", "est. Nov 2026")
    reg = ev("2026-11-25", "Regdrug", "PDUFA date", "PDUFA", "25 Nov 2026")
    # Within the month, a regulatory date first, then the furthest phase.
    assert _brief(view, modelled=False, events=[ph2, ph3, reg])["paragraphs"][2] == (
        "The PDUFA date for Regdrug (25 Nov 2026) is the next test of the pipeline.")
    assert _brief(view, modelled=False, events=[ph2, ph3])["paragraphs"][2] == (
        "The Phase 3 readout for Ph3drug (est. Nov 2026) is the next test of the pipeline.")
    # A month sooner wins over a later phase.
    early = dict(ph2, date="2026-10-20", date_text="est. Oct 2026")
    assert _brief(view, modelled=False, events=[early, ph3])["paragraphs"][2] == (
        "The Phase 2 readout for Ph2drug (est. Oct 2026) is the next test of the pipeline.")


@pytest.mark.parametrize("row, sentence", [
    ({"asset": "Lynparza", "when": "8 Sep 2027", "date": "2027-09-08", "share_text": "5.6%",
      "share": 0.0558},
     "The nearest loss of exclusivity, Lynparza on 8 Sep 2027, is 5.6% of revenue."),
    ({"asset": "Soliris", "when": "Mar 2029", "date": "2029-03-31", "share_text": "9.9%",
      "share": 0.099},
     "The nearest loss of exclusivity, Soliris in Mar 2029, is 9.9% of revenue."),
    # A tenth of revenue or more is the largest risk.
    ({"asset": "Keytruda", "when": "2028", "date": "2028-12-31", "share_text": "45.0%",
      "share": 0.45},
     "The nearest loss of exclusivity, Keytruda in 2028, is 45.0% of revenue, the largest "
     "risk."),
    # A share on file only as text is read as a number.
    ({"asset": "Eliquis", "when": "1 Apr 2028", "date": "2028-04-01", "share_text": "10.0%"},
     "The nearest loss of exclusivity, Eliquis on 1 Apr 2028, is 10.0% of revenue, the "
     "largest risk."),
])
def test_the_nearest_material_loss_of_exclusivity_is_named(view, row, sentence):
    # A larger loss more than five years on is not this year's question.
    later = {"asset": "Later", "when": "2040", "date": "2040-12-31", "share_text": "60.0%",
             "share": 0.6}
    brief = _brief(view, modelled=False, expiries={"rows": [row], "all": [row, later],
                                                   "more": 1})
    assert brief["paragraphs"][2] == sentence
    assert f"risk: {row['asset']} loses exclusivity {row['when']}" in brief["facts"]
    assert "Later" not in brief["paragraphs"][2] and "Later" not in brief["facts"]


def test_a_loss_of_exclusivity_with_no_share_is_named_only_with_nothing_material_after(view):
    imfinzi = {"asset": "Imfinzi", "when": "2031", "date": "2031-12-31", "share_text": "",
               "share": None, "value": 8.89}
    small = {"asset": "Small", "when": "2033", "date": "2033-12-31", "share_text": "1.0%",
             "share": 0.01}
    brief = _brief(view, modelled=False, expiries={"rows": [imfinzi, small]})
    assert brief["paragraphs"][2] == "The nearest loss of exclusivity is Imfinzi in 2031."
    # A later loss worth 5% of revenue is named over a nearer one with no share.
    mid = {"asset": "Mid", "when": "1 Jan 2032", "date": "2032-01-01", "share_text": "6.0%",
           "share": 0.06}
    brief = _brief(view, modelled=False, expiries={"rows": [imfinzi, mid]})
    assert brief["paragraphs"][2] == (
        "The first loss of exclusivity over 5% of revenue, Mid on 1 Jan 2032, is 6.0% of "
        "revenue.")


def _loss(asset, date, share, when):
    return {"asset": asset, "date": date, "when": when, "share": share,
            "share_text": f"{share * 100:.1f}%" if share is not None else ""}


def test_products_lost_the_same_day_are_one_loss(view):
    words = view["_ki_loss_words"]
    janumet = _loss("Janumet", "2026-11-24", 0.019, "24 Nov 2026")
    januvia = _loss("Januvia", "2026-11-24", 0.020, "24 Nov 2026")
    small = _loss("Small", "2027-06-01", 0.01, "1 Jun 2027")
    out = words({"all": [janumet, januvia, small]}, [], "2026-10-01")
    assert out["text"] == ("the nearest loss of exclusivity, Janumet and Januvia on 24 Nov "
                           "2026, is 3.9% of revenue together")
    assert [r["asset"] for r in out["rows"]] == ["Janumet", "Januvia"]
    assert out["facts"] == ["risk: Janumet loses exclusivity 24 Nov 2026, 1.9% of revenue",
                            "risk: Januvia loses exclusivity 24 Nov 2026, 2.0% of revenue"]
    # Together worth 5%, they are the first material loss.
    big = [dict(janumet, share=0.03, share_text="3.0%"), dict(januvia, share=0.03,
                                                             share_text="3.0%")]
    assert words({"all": big}, [], "2026-10-01")["text"] == (
        "the nearest loss of exclusivity, Janumet and Januvia on 24 Nov 2026, is 6.0% of "
        "revenue together")
    # MRK: the two small ones come first, Keytruda is the first loss over 5%.
    keytruda = _loss("Keytruda", "2028-12-31", 0.487, "2028")
    assert words({"all": [janumet, januvia, keytruda]}, [], "2026-10-01")["text"] == (
        "the first loss of exclusivity over 5% of revenue, Keytruda in 2028, is 48.7% of "
        "revenue, the largest risk")


def test_a_larger_loss_inside_five_years_is_said_after_the_first(view):
    words = view["_ki_loss_words"]
    mid = _loss("Mid", "2027-01-01", 0.11, "1 Jan 2027")
    eliquis = _loss("Eliquis", "2028-04-01", 0.20, "1 Apr 2028")
    out = words({"all": [mid, eliquis]}, [], "2026-10-01")
    # The larger one is the largest risk, so the first is not called that.
    assert out["text"] == ("the nearest loss of exclusivity, Mid on 1 Jan 2027, is 11.0% of "
                           "revenue; the largest, Eliquis on 1 Apr 2028, is 20.0%")
    assert [r["asset"] for r in out["rows"]] == ["Mid", "Eliquis"]
    # Under 15%, or no larger than the first, or past five years: not said.
    for later in (dict(eliquis, share=0.127), dict(eliquis, share=0.10),
                  dict(eliquis, date="2032-04-01", when="1 Apr 2032")):
        assert words({"all": [mid, later]}, [], "2026-10-01")["text"] == (
            "the nearest loss of exclusivity, Mid on 1 Jan 2027, is 11.0% of revenue, the "
            "largest risk")
    # In the note, beside the rows the list shows.
    brief = _brief(view, modelled=False, series={"close": 50.0, "as_of": "2026-10-01"},
                   expiries={"rows": [mid], "all": [mid, eliquis]})
    assert brief["paragraphs"][2] == (
        "The nearest loss of exclusivity, Mid on 1 Jan 2027, is 11.0% of revenue; the largest, "
        "Eliquis on 1 Apr 2028, is 20.0%.")
    assert "risk: Eliquis loses exclusivity 1 Apr 2028, 20.0% of revenue" in brief["facts"]


def test_a_shouted_name_is_said_as_a_name(view):
    out = view["_ki_loss_words"]({"all": [_loss("JAKAVI", "2028-01-01", 0.12, "1 Jan 2028")]},
                                 [], "2026-10-01")
    assert out["text"] == ("the nearest loss of exclusivity, Jakavi on 1 Jan 2028, is 12.0% of "
                           "revenue, the largest risk")


def test_the_loss_of_exclusivity_follows_the_readouts_and_needs_a_row(view):
    events = [{"date": "2026-11-01", "asset": "Truqap", "date_text": "est. Nov 2026"}]
    lynparza = {"asset": "Lynparza", "when": "8 Sep 2027", "date": "2027-09-08",
                "share_text": "5.6%", "share": 0.0558}
    both = _brief(view, modelled=False, events=events, expiries={"rows": [lynparza]})
    assert both["paragraphs"][2] == (
        "The next readout, Truqap (est. Nov 2026), extends a product already sold rather than "
        "testing the pipeline; the nearest loss of exclusivity, Lynparza on 8 Sep 2027, is "
        "5.6% of revenue.")
    # An empty list says nothing; with no list at all, the risks' exclusivity row is read.
    assert len(_brief(view, modelled=False, expiries={"rows": []})["paragraphs"]) == 2
    assert view["_ki_loss_words"]({"rows": [], "all": []}, [], "2026-10-01") == {}
    risks = [{"kind": "exclusivity", "asset": "Lynparza", "date": "2027-09-08",
              "share_text": "5.6%"}]
    assert _brief(view, modelled=False, risks=risks)["paragraphs"][2] == (
        "The nearest loss of exclusivity, Lynparza in Sep 2027, is 5.6% of revenue.")


@pytest.mark.parametrize("ticker, sentence", [
    ("AZN", "It ranks 7th of 18 big pharma: growth 4th best but operating margin 3rd worst, "
            "growth bought at the cost of margin."),
    # Growth in the middle third of the cohort says nothing, so there is no read.
    ("GILD", "It ranks 12th of 18 big pharma: growth 7th worst, operating margin 3rd best."),
    ("VRTX", "It ranks 1st of 18 big pharma: growth 3rd best, operating margin 2nd best, "
             "strong on both."),
    ("BAYN", "It ranks 18th of 18 big pharma: growth worst, operating margin worst, weak on "
             "both."),
    # Pre-tax margin stands in where operating margin is not on file.
    ("BIIB", "It ranks 15th of 18 big pharma: growth 6th worst, pre-tax margin 4th worst, "
             "weak on both."),
    ("UTHR", "It ranks 6th of 21 commercial-stage biotechs: growth 5th worst but operating "
             "margin best, margin without the growth."),
    # A loss is never a good margin, whatever its place: AXSM's is in the middle third.
    ("AXSM", "It ranks 10th of 21 commercial-stage biotechs: growth 2nd best but operating "
             "margin 10th worst, growth bought at the cost of margin."),
    # One measure alone gives no judgement.
    ("ROG", "It ranks 6th of 18 big pharma: operating margin 5th best."),
    # A clinical company is read on its runway.
    ("CRSP", "It ranks 10th of 30 clinical-stage biotechs: cash runway 77 months, 2nd best."),
])
def test_the_rank_against_peers_says_what_growth_and_margin_say_together(view, board, ticker,
                                                                         sentence):
    company = board["companies"][ticker]
    brief = _brief(view, ticker, modelled=False, company=company,
                   cohort=board["cohorts"][company["cohort"]])
    assert brief["paragraphs"][2] == sentence
    assert brief["facts"].splitlines()[-1].startswith(
        f"peer rank: {view['_ki_ord'](company['rank'])} of {company['ranked_of']} ")
    # A company without a rank has no sentence.
    unranked = board["companies"]["ADAPY"]
    assert len(_brief(view, "ADAPY", modelled=False, company=unranked,
                      cohort=board["cohorts"]["commercial"])["paragraphs"]) == 2


@pytest.mark.parametrize("metric, margin, standing", [
    ({"score": 81.2}, False, "good"), ({"score": 66.7}, False, "good"),
    ({"score": 66.6}, False, ""), ({"score": 50.0}, False, ""), ({"score": 33.4}, False, ""),
    ({"score": 33.3}, False, "bad"), ({"score": 0.0}, False, "bad"),
    ({"score": 90.0, "value": -0.1}, True, "bad"),       # a loss is never a good margin
    ({"score": 90.0, "value": -0.1}, False, "good"),     # growth is read on its place
    ({"score": None}, False, ""), (None, False, "")])
def test_a_place_is_good_or_bad_only_in_the_top_or_bottom_third(view, metric, margin, standing):
    assert view["_ki_standing"](metric, margin=margin) == standing


def test_the_note_never_gives_a_move_a_cause_and_keeps_house_style(view, board):
    briefs = [_azn_brief(view, board),
              _brief(view, changes=_month()),
              _brief(view, series=_trading(-0.029, -0.065), changes=GOOD + BAD + DEAL),
              _brief(view, modelled=False, street={"value": 60.0}),
              _brief(view, modelled=False, failed="timed out"),
              _brief(view, rating_failed="timed out"),
              _brief(view, rated={"ok": False, "reason": "no share price on file"})]
    for brief in briefs:
        for para in brief["paragraphs"]:
            _house_style(para)
            assert para[0].isupper(), para
            low = para.lower()
            assert not [w for w in CAUSAL if w in low], para
        _house_style(brief["facts"])


def test_the_note_opens_as_built_with_its_lead_in_bold_or_as_the_rewrite(view):
    brief = {"paragraphs": ["One <b>. Two.", "Three."], "lead": "One <b>."}
    built = view["_ki_brief_html"](brief, "from the figures on this page")
    assert '<span class="sec-label">Morning note</span>' in built
    assert '<span class="sec-basis">from the figures on this page</span>' in built
    assert re.findall(r"<p>(.*?)</p>", built, re.S) == [
        "<b>One &lt;b&gt;.</b> Two.", "Three."]
    # A lead that does not open the first paragraph is not bolded elsewhere.
    other = view["_ki_brief_html"]({"paragraphs": ["One. Two."], "lead": "Two."}, "x")
    assert "<b>" not in other
    # The rewrite is a paragraph a line, whatever the blank lines between.
    rewrite = view["_ki_brief_html"](brief, "gemini · 22 Sep 2026",
                                     "First.\n\nSecond line\nsame paragraph.\n  \n\nThird.\n")
    assert re.findall(r"<p>(.*?)</p>", rewrite, re.S) == [
        "First.", "Second line", "same paragraph.", "Third."]
    assert '<div class="ki-brief">' in rewrite and "One" not in rewrite
    assert "<b>" not in rewrite


# --- key assets ------------------------------------------------------------------------------
def test_an_exclusivity_date_is_a_month_or_the_year_the_filer_gave(view):
    loe = view["_ki_loe_text"]
    assert loe("2032-08-15", "drug substance patent") == "Aug 2032"
    # A year's last day stands in for a year the filer gave without a day.
    assert loe("2031-12-31", "AstraZeneca 20-F, U.S. new molecular entity patent (2031)") == "2031"
    # The last day of a year with no year in its basis is a real day.
    assert loe("2031-12-31", "drug substance patent") == "Dec 2031"
    assert loe("2031-12-31", "patent (2030)") == "Dec 2031"
    assert loe("2032-08-15", "patent (2032)") == "Aug 2032"
    assert loe(None) == "" and loe("2031") == ""


def test_with_its_day_an_exclusivity_date_keeps_the_precision_its_source_gave(view):
    loe = view["_ki_loe_text"]
    assert loe("2027-09-08", "drug substance patent", day=True) == "8 Sep 2027"
    assert loe("2031-12-31", "drug substance patent", day=True) == "31 Dec 2031"
    assert loe("2031-12-31", "20-F, U.S. new molecular entity patent (2031)", day=True) == "2031"
    # A month's last day standing in for a month the filer gave is the month.
    assert loe("2029-03-31", "10-K, biosimilar entry (2029-03)", day=True) == "Mar 2029"
    assert loe("2029-03-31", "10-K, biosimilar entry (2029-03)") == "Mar 2029"


@pytest.mark.parametrize("iso, basis, day, text", [
    # A filing that names the full date gives its day.
    ("2028-06-15", "10-K, patent settlement (2028-06-15)", True, "15 Jun 2028"),
    ("2028-06-15", "10-K, patent settlement (2028-06-15)", False, "Jun 2028"),
    # A filing's or the statute's year's last day is the year, with "(YYYY)" or without.
    ("2031-12-31", "statutory floor (12y)", True, "2031"),
    ("2031-12-31", "annual report disclosure", True, "2031"),
    ("2029-12-31", "10-Q", False, "2029"),
    ("2031-12-31", "patent (2031)", True, "2031"),
    # Any other day of a filing or the statute is its month: the filer gave no day.
    ("2030-09-30", "statutory floor (12y)", True, "Sep 2030"),
    ("2029-05-31", "20-F", True, "May 2029"),
    ("2028-06-15", "10-K disclosure", True, "Jun 2028"),
    # A register's date is a day.
    ("2028-06-15", "drug substance patent", True, "15 Jun 2028"),
    ("2028-06-15", "drug substance patent", False, "Jun 2028"),
])
def test_an_exclusivity_date_reads_at_the_precision_its_basis_gives(view, iso, basis, day,
                                                                       text):
    assert view["_ki_loe_text"](iso, basis, day=day) == text


def test_a_due_date_is_ahead_by_its_own_precision(view):
    ahead = view["_ki_due_ahead"]
    today = dt.date(2026, 10, 2)
    assert ahead("2026-10", today)                 # a month is ahead all month
    assert not ahead("2026-10-01", today)          # a day is not
    assert ahead("2026-10-02", today) and ahead("2026-10-02 00:00:00", today)
    assert not ahead("2026-09", today)
    assert not ahead(None, today) and not ahead("soon", today)


def test_a_compounds_next_readout_is_at_the_furthest_phase_still_to_read_out(view):
    nxt = view["_ki_next_readout"]
    today = dt.date(2026, 10, 2)
    assert nxt(AZN_PROGRAMMES[0], today) == {"phase": "Phase 3", "date": "2027-06-04",
                                             "nct_id": "NCT3", "text": "Ph 3 · Jun 2027"}
    # Its Phase 3 read out already: the next is the Phase 2.
    past = {"studies": [{"phase": "Phase 3", "due": "2026-01-01"},
                        {"phase": "Phase 2", "due": "2026-12-01", "nct_id": "NCT9"}]}
    assert nxt(past, today)["text"] == "Ph 2 · Dec 2026"
    # A month-only date this month is still ahead.
    assert nxt({"studies": [{"phase": "Phase 3", "due": "2026-10"}]}, today)["text"] == (
        "Ph 3 · Oct 2026")
    # Approved-use studies and undated ones are not readouts the value turns on.
    assert nxt({"studies": [{"phase": "Phase 4", "due": "2027-01-01"},
                            {"phase": "Phase 3", "due": None}]}, today) == {}
    assert nxt(None, today) == {}


def test_a_next_readout_is_a_test_of_a_compound_not_a_regimen_or_a_follow_up(view):
    nxt = view["_ki_next_readout"]
    today = dt.date(2026, 10, 2)
    p3 = {"phase": "Phase 3", "due": "2027-01-01", "nct_id": "NCT3"}
    # A regimen, a lymphodepletion or a comparator is no compound.
    for name in ("Fludarabine lymphodepletion regimen", "Standard of care", "Placebo",
                 "Best supportive care", "Chemotherapy alone"):
        assert nxt({"name": name, "studies": [p3]}, today) == {}, name
    # A follow-up, extension, rollover or access study tests nothing: the next real one is.
    for title in ("Long-term follow-up of X", "An open-label extension study", "Rollover study",
                  "Continued access to X", "Expanded access programme", "Long term safety"):
        out = nxt({"name": "X", "studies": [dict(p3, title=title), {
            "phase": "Phase 2", "due": "2027-03-01", "nct_id": "NCT2"}]}, today)
        assert out["nct_id"] == "NCT2", title
    # A study enrolling by invitation is a continuation of one already run.
    for status in ("Enrolling by invitation", "ENROLLING_BY_INVITATION"):
        assert nxt({"name": "X", "studies": [dict(p3, status=status)]}, today) == {}
    assert nxt({"name": "X", "studies": [dict(p3, status="Recruiting")]}, today)["nct_id"] == "NCT3"
    # Eight years out is the furthest a next readout can be.
    assert view["_KI_READOUT_YEARS"] == 8
    assert nxt({"name": "X", "studies": [dict(p3, due="2034-10-02")]}, today)["text"] == (
        "Ph 3 · Oct 2034")
    assert nxt({"name": "X", "studies": [dict(p3, due="2034-10-03")]}, today) == {}


def _mix_record(fiscal_label="FY2025"):
    return {"periods": {"FY0": {"label": fiscal_label, "revenue_usd_m": 1000.0}},
            "detail": {"products": {"fiscal_year": 2025, "rows": [
                {"name": "Alpha", "value_usd_m": 400.0},
                {"name": "Beta (oral)", "value_usd_m": 100.0},
                {"name": "Gamma", "value_usd_m": 5.0}, {"name": "Delta", "value_usd_m": 4.0},
                {"name": "Epsilon", "value_usd_m": 3.0}, {"name": "Zeta", "value_usd_m": 2.0},
                {"name": "Eta", "value_usd_m": 1.0}]}}}


def test_a_segment_only_product_table_is_measured_against_reported_revenue(view):
    """Bayer files its pharma division's products: they are shares of the group's revenue,
    not of each other."""
    mix = view["_ki_product_mix"](_mix_record())
    assert [name for name, _ in mix] == ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta",
                                         "Eta"]
    assert [share for _, share in mix][:2] == pytest.approx([0.40, 0.10])
    shares = view["_ki_product_shares"](_mix_record())
    assert shares["alpha"] == pytest.approx(0.40) and shares["beta"] == pytest.approx(0.10)
    # Rows of another year than the reported revenue give no shares: a share of something
    # else is not printed as one of the company's revenue.
    assert view["_ki_product_mix"](_mix_record("FY2024")) == []
    # Nor do rows that add to more than the revenue.
    over = _mix_record()
    over["periods"]["FY0"]["revenue_usd_m"] = 400.0
    assert view["_ki_product_mix"](over) == []
    assert view["_ki_product_mix"]({}) == [] and view["_ki_product_shares"](None) == {}


def test_one_product_filed_twice_is_one_row_and_shares_use_one_base(view):
    products = {"fiscal_year": 2025, "rows": [
        {"name": "PYLARIFY", "value_usd_m": 990.0}, {"name": "Definity", "value_usd_m": 330.2},
        {"name": "Definity", "value_usd_m": 330.2}, {"name": "Techne Lite", "value_usd_m": 92.0}]}
    mix = view["_ki_mix_segments"](products, {"label": "FY2025", "revenue_usd_m": 1541.6})
    # A shouted brand takes the title case every other name has.
    assert [d["label"] for d in mix] == ["Pylarify", "Definity", "Techne Lite", "rest"]
    total = sum(d["value"] for d in mix)
    assert total == pytest.approx(1541.6)


def test_key_assets_are_the_five_largest_of_each_part_with_when_each_is_decided(view):
    assets = view["_ki_key_assets"](_azn_verdict(), {}, AZN_PROGRAMMES, AZN_EXCLUSIVITIES,
                                    dt.date(2026, 10, 2), True)
    marketed, pipeline = assets["marketed"], assets["pipeline"]
    assert view["_KI_ASSETS_SHOWN"] == 5
    assert [(r["name"], r["text"], r["meta"]) for r in marketed["rows"]] == [
        ("Tagrisso", "10.29", "Aug 2032"),            # the exclusivity file's date
        ("Imfinzi", "8.89", "2031"),                  # a year the filer gave
        ("Symbicort", "7.04", "lapsed"),              # the model has it in the base
        ("Farxiga", "5.47", "lapsed"),                # its date has passed, whatever the model
        ("Breztri Aerosphere", "3.27", "2038")]       # the model's year, brackets dropped
    # Not counted and with no value are not key assets; the rest is one row, the part's
    # total less what is shown, and its count includes what the model values at nothing.
    names = {r["name"] for r in marketed["rows"] + pipeline["rows"]}
    assert not names & {"Not counted", "No value", "Zero"}
    assert marketed["more_n"] == 3                    # Small, Tiny and Zero
    assert marketed["more_value"] == pytest.approx(50.0 - (10.29 + 8.89 + 7.04 + 5.47 + 3.27))
    assert [r["name"] for r in pipeline["rows"]] == ["Elecoglipron", "AZD6234", "Compound C",
                                                     "Compound D", "Compound E"]
    lead = pipeline["rows"][0]
    assert lead["meta"] == "Ph 3 · Jun 2027"
    assert lead["tip"] == ("Elecoglipron · chance of approval 55% · next readout NCT3, "
                           "registry estimate")
    assert pipeline["rows"][1]["meta"] == ""          # no readout on file: a dot, not a guess
    assert pipeline["more_n"] == 2
    assert pipeline["more_value"] == pytest.approx(20.0 - (4.66 + 3.74 + 3.0 + 2.0 + 1.5))
    assert assets["top"] == pytest.approx(10.29)       # both tables on one scale


def test_a_product_with_no_exclusivity_row_lapses_by_the_models_year(view):
    verdict = {"sotp": {"marketed": {"n": 3, "per_share": 6.0}}, "modelled": [
        dict(asset_id=1, name="Old", per_share=3.0, counted=True, is_marketed=True,
             loe_year=2025),
        dict(asset_id=2, name="Filed", per_share=2.0, counted=True, is_marketed=True,
             loe_year=2024),
        dict(asset_id=3, name="Ahead", per_share=1.0, counted=True, is_marketed=True,
             loe_year=2030)]}
    excl = [{"asset_id": 2, "brand_name": "Filed", "loe": "2030-05-01",
             "loe_basis": "drug substance patent"}]
    assets = view["_ki_key_assets"](verdict, {}, [], excl, dt.date(2026, 10, 2), True)
    assert [(r["name"], r["meta"]) for r in assets["marketed"]["rows"]] == [
        ("Old", "lapsed"),             # its year is before this one
        ("Filed", "May 2030"),         # the exclusivity file wins over the model's year
        ("Ahead", "2030")]
    assert assets["marketed"]["rows"][2]["tip"] == "Ahead · exclusivity: the model's LOE year"


def test_with_no_modelled_compound_the_pipeline_is_the_registrys_programmes(view):
    verdict = {"sotp": {"marketed": {"n": 1, "per_share": 5.0}},
               "modelled": [dict(asset_id=10, name="Alpha", per_share=5.0, counted=True,
                                 is_marketed=True)]}
    assets = view["_ki_key_assets"](verdict, {}, _programmes(), [], dt.date(2026, 10, 2), True)
    assert [(r["name"], r["text"], r["meta"]) for r in assets["pipeline"]["rows"]] == [
        ("Late2", "Ph 3", "Nov 2026"), ("Late", "Ph 3", "Mar 2027"), ("Mid", "Ph 2", "Dec 2026"),
        ("Nodate", "Ph 2", ""), ("Early", "Ph 1", "Nov 2026")]
    assert all(r["value"] is None for r in assets["pipeline"]["rows"])
    markup = view["_ki_key_assets_html"](assets)
    # Phases, not values, so the head says so and no risking is claimed.
    assert "Pipeline, risked" not in markup
    assert re.search(r'<span>Pipeline</span><span></span><span class="v">phase</span>'
                     r'<span>readout, est\.</span>', markup)


def _programmes():
    return [{"asset_id": 1, "name": "Late (X)", "stage": "Phase 3", "area": "Oncology",
             "trials": 2, "studies": [{"phase": "Phase 3", "due": "2027-03-01",
                                       "nct_id": "NCT1"}]},
            {"asset_id": 2, "name": "Early", "stage": "Phase 1",
             "studies": [{"phase": "Phase 1", "due": "2026-11-01"}]},
            {"asset_id": 3, "name": "Mid", "stage": "Phase 2",
             "studies": [{"phase": "Phase 2", "due": "2026-12-01"}]},
            {"asset_id": 4, "name": "Late2", "stage": "Phase 3",
             "studies": [{"phase": "Phase 3", "due": "2026-11-15"}]},
            {"asset_id": 5, "name": "Approved", "stage": "Phase 4",
             "studies": [{"phase": "Phase 4", "due": "2026-11-15"}]},
            {"asset_id": 6, "name": "Nodate", "stage": "Phase 2", "studies": []}]


def test_programme_rows_run_furthest_phase_first_then_the_nearest_readout(view):
    rows = view["_ki_programme_rows"](_programmes(), dt.date(2026, 10, 2))
    assert [r["name"] for r in rows] == ["Late2", "Late", "Mid", "Nodate", "Early"]
    assert "Approved" not in {r["name"] for r in rows}        # a Phase 4 is on the market
    assert rows[1]["tip"] == "Late (X) · Oncology · 2 trials · readout a registry estimate"
    assert rows[3]["tip"] == "Nodate"                         # no readout, no estimate claimed
    # A regimen is no compound, and a follow-up study gives no readout date.
    more = _programmes() + [
        {"asset_id": 7, "name": "Lymphodepletion regimen", "stage": "Phase 3",
         "studies": [{"phase": "Phase 3", "due": "2026-10-15"}]},
        {"asset_id": 8, "name": "Followed", "stage": "Phase 3",
         "studies": [{"phase": "Phase 3", "due": "2026-10-20", "title": "Long-term follow-up"}]}]
    rows = view["_ki_programme_rows"](more, dt.date(2026, 10, 2))
    assert [(r["name"], r["meta"]) for r in rows][:3] == [
        ("Late2", "Nov 2026"), ("Late", "Mar 2027"), ("Followed", "")]
    assert "Lymphodepletion regimen" not in {r["name"] for r in rows}


def test_not_modelled_key_assets_are_revenue_shares_and_phases(view):
    excl = [{"asset_id": 10, "brand_name": "Alpha", "loe": "2029-12-31",
             "loe_basis": "10-K, compound patent (2029)"}]
    assets = view["_ki_key_assets"]({}, _mix_record(), _programmes(), excl,
                                    dt.date(2026, 10, 2), False)
    marketed = assets["marketed"]
    assert [(r["name"], r["text"], r["meta"]) for r in marketed["rows"]] == [
        ("Alpha", "40%", "2029"), ("Beta", "10%", ""), ("Gamma", "<1%", ""),
        ("Delta", "<1%", ""), ("Epsilon", "<1%", "")]
    # The rest is the rest of revenue, not a count of products.
    assert marketed["rest"] == pytest.approx(1.0 - (0.40 + 0.10 + 0.005 + 0.004 + 0.003))
    assert marketed["more_n"] == 0 and marketed["more_value"] is None
    assert [r["name"] for r in assets["pipeline"]["rows"]] == ["Late2", "Late", "Mid", "Nodate",
                                                               "Early"]
    text = _text(view["_ki_key_assets_html"](assets))
    assert text.startswith("Marketed of revenue LOE Alpha 40% 2029 Beta 10% ·")
    assert "Epsilon <1% · rest of revenue 49% Pipeline phase readout, est. Late2 Ph 3 Nov 2026" \
        in text
    # No product table: the rest is not claimed.
    bare = view["_ki_key_assets"]({}, {}, [], [], dt.date(2026, 10, 2), False)
    assert "rest" not in bare["marketed"] and bare["marketed"]["rows"] == []


def test_key_assets_draw_two_tables_on_one_scale(view):
    assets = view["_ki_key_assets"](_azn_verdict(), {}, AZN_PROGRAMMES, AZN_EXCLUSIVITIES,
                                    dt.date(2026, 10, 2), True)
    markup = view["_ki_key_assets_html"](assets)
    text = _text(markup)
    assert text.startswith("Marketed value LOE Tagrisso 10.29 Aug 2032 Imfinzi 8.89 2031 "
                           "Symbicort 7.04 lapsed")
    assert "3 more 15.04 Pipeline, risked value readout, est. Elecoglipron 4.66 Ph 3 · " \
           "Jun 2027 AZD6234 3.74 ·" in text
    assert text.endswith("Compound E 1.50 · 2 more 5.10")
    bars = re.findall(r'<i class="(\w+)" style="width:([\d.]+)%"></i>', markup)
    assert bars[0] == ("marketed", "100.0")
    assert bars[5] == ("pipeline", f"{4.66 / 10.29 * 100:.1f}")  # the pipeline on the same scale
    assert re.search(r'<span class="n">3 more</span><span class="b"></span>'
                     r'<span class="v">15.04</span>', markup)
    # Nothing on file: each part says so in one line.
    empty = view["_ki_key_assets_html"]({"modelled": False, "marketed": {"rows": []},
                                         "pipeline": {"rows": []}})
    assert re.findall(r'<div class="ki-ka-h"><span>([^<]*)</span></div>', empty) == [
        "Marketed", "Pipeline"]
    assert re.findall(r'<div class="ki-ka none">([^<]*)</div>', empty) == [
        "No product revenue on file.", "No compound in trials on file."]


# --- key assets: the next gate's whisker, the launch floor's underline ------------------------
# The company verdicts the API served on a copy of the book on 6 Oct 2026 (fixtures/gates_ui),
# cut to what a line reads, and LLY's next-gate costs.
GATES = FIXTURES / "gates_ui"


def _gates(name):
    return json.loads((GATES / f"{name}.json").read_text())


def _gate_assets(view, ticker, development=None, shown=5):
    return view["_ki_key_assets"](_gates(f"{ticker}_forecast-verdict"), {}, [], [],
                                  dt.date(2026, 10, 6), True, shown=shown,
                                  development=development)


def test_a_pipeline_row_carries_what_passing_its_next_gate_is_worth(view):
    assets = _gate_assets(view, "LLY", _gates("LLY_development"))
    rows = {r["name"]: r for r in assets["pipeline"]["rows"]}
    elo = rows["Eloralintide"]
    assert elo["success"] == pytest.approx(8.2344, abs=1e-4)
    assert elo["gate"] == {"label": "Phase 3 readout", "month": "2028-01"}
    assert elo["tip"] == ("Eloralintide · chance of approval 55% · Phase 3 readout est. "
                          "Jan 2028: 8.23 a share if it passes, nil if it fails, derived from "
                          "published transition rates")
    # A stated PoS splits into odds the stated figure implies, and says so.
    assert rows["Retatrutide"]["tip"].endswith("on gate odds implied by the stated PoS")
    # Marketed rows carry none of it.
    assert all(r.get("success") is None and not r.get("flag")
               for r in assets["marketed"]["rows"])


def test_an_fda_gate_says_approves_and_a_due_gate_says_since_when(view):
    rows = {r["name"]: r for r in _gate_assets(view, "AMGN")["pipeline"]["rows"]}
    assert ("FDA decision: 3.25 a share if the FDA approves it, nil if it does not"
            in rows["ABP 206"]["tip"])
    assert "Phase 3 readout due since Aug 2026: 0.30 a share" in rows["Dazodalibep"]["tip"]


def test_the_scale_takes_the_whiskers_so_none_is_clipped(view):
    assets = _gate_assets(view, "AMGN")
    maritide = assets["pipeline"]["rows"][0]
    assert maritide["name"] == "Maridebart Cafraglutide"
    assert assets["top"] == pytest.approx(maritide["success"])   # 45.97 over every value
    markup = view["_ki_key_assets_html"](assets)
    w = maritide["value"] / assets["top"] * 100
    assert (f'<i class="pipeline" style="width:{w:.1f}%"></i><i class="whisker" '
            f'style="left:{w:.1f}%;width:{100 - w:.1f}%"></i>') in markup


def test_the_whisker_sits_inside_the_bar_cell_and_adds_no_height(view):
    markup = view["_ki_key_assets_html"](_gate_assets(view, "LLY"))
    rows = re.findall(r'<div class="ki-ka" title="[^"]*">(.*?)</div>', markup)
    whiskered = [r for r in rows if "whisker" in r]
    assert len(whiskered) == 5                                    # every pipeline row shown
    for row in rows:                                              # four cells, as before
        assert len(re.findall(r'<span class="(?:n|b|v|m)[ "]', row)) == 4, row
        assert re.fullmatch(r'<span class="n [a-z]+">.*?</span><span class="b">.*?</span>'
                            r'<span class="v">.*?</span><span class="m">.*?</span>', row), row
    css = (FRONTEND / "assets" / "research.css").read_text()
    assert ".ki-ka { height: 21px;" in css                       # the row keeps its height
    assert ".ki-ka .b { height: 8px; position: relative; }" in css
    rule = re.search(r"\.ki-ka \.b i\.whisker \{([^}]*)\}", css).group(1)
    assert "position: absolute" in rule and "height: 1px" in rule
    assert "var(--purple-book)" in rule and "#" not in rule       # a token, no colour literal


def test_a_launch_before_the_floor_is_underlined_and_said_in_the_one_tooltip(view):
    assets = _gate_assets(view, "LLY")
    lep = next(r for r in assets["pipeline"]["rows"] if r["name"] == "Lepodisiran")
    assert lep["flag"] == "red"
    assert lep["tip"].endswith("which puts the earliest approval from it at Jul 2030.")
    assert "2027 in the model, but the earliest approval is Oct 2029" in lep["tip"]
    markup = view["_ki_key_assets_html"](assets)
    # The mark carries no title of its own: the row's tooltip says everything once.
    assert '<span class="v"><span class="u-flagged red">2.03</span></span>' in markup
    assert markup.count("u-flagged") == 1
    vrtx = _gate_assets(view, "VRTX")
    flags = {r["name"]: r["flag"] for r in vrtx["pipeline"]["rows"]}
    assert flags["Povetacicept"] == "amber" and flags["VX-147"] == "amber"
    assert flags["Atumelnant"] == ""                             # clear
    vx147 = next(r for r in vrtx["pipeline"]["rows"] if r["name"] == "VX-147")
    assert vx147["success"] is None                              # flagged with no gate legs
    assert "whisker" not in view["_ki_key_assets_html"]({"modelled": True, "top": 10.0,
                                                          "pipeline": {"rows": [vx147]}})


def test_a_gate_that_costs_more_than_it_is_worth_is_a_fact_in_the_tooltip_and_no_mark(view):
    dev = _gates("LLY_development")
    with_costs = _gate_assets(view, "LLY", dev, shown=50)
    morf = next(r for r in with_costs["pipeline"]["rows"] if r["name"] == "MORF-057")
    assert morf["tip"].endswith(
        "· reaching the Phase 2 readout costs more than it is worth risked: it needs a 52% "
        "chance against the 27% on file, at published trial costs in 2018 prices")
    # Only failing gates say it, and the cost read changes nothing else on any row.
    without = _gate_assets(view, "LLY", None, shown=50)
    for a, b in zip(with_costs["pipeline"]["rows"], without["pipeline"]["rows"]):
        if a["name"] == "MORF-057":
            assert a["tip"].startswith(b["tip"]) and a["tip"] != b["tip"]
        else:
            assert a == b
    assert (view["_ki_key_assets_html"](with_costs).count("ki-ka")
            == view["_ki_key_assets_html"](without).count("ki-ka"))
    for r in with_costs["pipeline"]["rows"]:
        _house_style(r["tip"])


def test_the_note_says_what_the_next_gate_is_worth_where_the_event_is_that_gate(view):
    def assets(month="2028-01", success=8.2344):
        row = {"name": "Eloralintide", "value": 5.0234, "meta": "Ph 3 · Jan 2028",
               "kind": "pipeline", "success": success,
               "gate": {"label": "Phase 3 readout", "month": month}}
        return {"pipeline": {"rows": [row]}}

    def event(date="2028-01-20", what="Phase 3 readout"):
        return [{"date": date, "asset": "Eloralintide", "pipeline": True, "event": what,
                 "short": "Ph 3", "date_text": "est. Jan 2028"}]

    said = _brief(view, "LLY", modelled=False, events=event(), assets=assets())
    assert said["paragraphs"][2] == (
        "The Phase 3 readout for Eloralintide (est. Jan 2028) is the next test of the "
        "pipeline, worth 8.23 a share if it passes and nil if it fails, against 5.02 now.")
    # Another month, another kind of event, or no legs: the clause as it was.
    old = ("The Phase 3 readout for Eloralintide (est. Jan 2028) is the next test of the "
           "pipeline, 5.02 a share in the model.")
    assert _brief(view, "LLY", modelled=False, events=event(), assets=assets(month="2028-04")
                  )["paragraphs"][2] == old
    assert _brief(view, "LLY", modelled=False, events=event(), assets=assets(success=None)
                  )["paragraphs"][2] == old
    ph2 = _brief(view, "LLY", modelled=False, events=event(what="Phase 2 readout"),
                 assets=assets())["paragraphs"][2]
    assert ph2.endswith("5.02 a share in the model.")
    # An FDA gate with no date is any decision on the compound.
    fda = {"pipeline": {"rows": [{"name": "Eloralintide", "value": 5.0234, "kind": "pipeline",
                                  "success": 8.2344,
                                  "gate": {"label": "FDA decision", "month": ""}}]}}
    assert "worth 8.23 a share if it passes" in _brief(
        view, "LLY", modelled=False, events=event(what="PDUFA date"), assets=fda
    )["paragraphs"][2]
    # No new sentence: the clause grows, the paragraph keeps its one sentence.
    assert said["paragraphs"][2].replace("est. ", "est ").count(". ") == 0


def test_the_morning_note_reads_the_gate_off_the_key_assets_it_is_given(view):
    assets = _gate_assets(view, "LLY")
    gate = {r["name"]: r["gate"] for r in assets["pipeline"]["rows"]}
    events = [{"date": "2026-11-30", "asset": "Retatrutide", "pipeline": True,
               "event": "Phase 3 readout", "short": "Ph 3", "date_text": "est. Nov 2026"}]
    para = _brief(view, "LLY", modelled=False, events=events, assets=assets)["paragraphs"][2]
    assert gate["Retatrutide"] == {"label": "Phase 3 readout", "month": "2026-11"}
    assert para == ("The Phase 3 readout for Retatrutide (est. Nov 2026) is the next test of "
                    "the pipeline, worth 20.65 a share if it passes and nil if it fails, "
                    "against 20.22 now.")


def test_stated_legs_say_their_failure_leg_in_the_tooltip_and_the_note(view):
    line = copy.deepcopy(next(m for m in _gates("LLY_forecast-verdict")["modelled"]
                              if m["name"] == "Eloralintide"))
    line["gate"].update(legs_basis="stated", p_gate=None, evidence=None,
                        per_share_failure=3.1)
    line["per_share_failure"] = 3.1
    gate = view["_ki_gate"](line)
    assert gate["failure"] == 3.1
    assert gate["tip"] == ("Phase 3 readout est. Jan 2028: 8.23 a share if it passes, 3.10 if "
                           "it fails, from the success and failure legs on file")
    # Derived legs, and stated ones whose failure leg is nothing, keep nil.
    assert view["_ki_gate"](next(m for m in _gates("LLY_forecast-verdict")["modelled"]
                                 if m["name"] == "Eloralintide"))["failure"] == 0.0
    line["gate"]["per_share_failure"] = line["per_share_failure"] = 0.0
    assert "nil if it fails" in view["_ki_gate"](line)["tip"]
    row = {"name": "Eloralintide", "value": 5.0234, "kind": "pipeline", "success": 8.2344,
           "failure": 3.1, "gate": {"label": "Phase 3 readout", "month": "2028-01"}}
    events = [{"date": "2028-01-20", "asset": "Eloralintide", "pipeline": True,
               "event": "Phase 3 readout", "short": "Ph 3", "date_text": "est. Jan 2028"}]
    said = _brief(view, "LLY", modelled=False, events=events,
                  assets={"pipeline": {"rows": [row]}})["paragraphs"][2]
    assert said == ("The Phase 3 readout for Eloralintide (est. Jan 2028) is the next test of "
                    "the pipeline, worth 8.23 a share if it passes and 3.10 if it fails, "
                    "against 5.02 now.")


# --- readouts and decisions ------------------------------------------------------------------
def _event(date, kind="data readout", phase="Phase 3", name="A", marketed=True, pct=None,
           ind=None, conf="confirmed", prec="day", reg=False, nct="NCT1"):
    return {"date": date, "date_confidence": conf, "date_precision": prec, "kind": kind,
            "phase": phase, "regulatory": reg,
            "asset": {"name": name, "is_marketed": marketed},
            "indication": {"name": ind} if ind else None,
            "asset_value": ({"per_share": 1.0, "pct_of_price": pct} if pct is not None
                            else None),
            "title": f"{phase}, {name}", "nct_id": nct}


def _events():
    return [
        _event("2026-09-30", name="Past"),
        _event("2026-11-20", kind="pdufa", phase=None, name="Reg", marketed=False, reg=True),
        _event("2026-11-02", phase="Phase 2", name="SmallP2", marketed=False, pct=0.005),
        _event("2026-11-03", phase="Phase 2", name="BigP2", marketed=False, pct=0.02,
               ind="Obesity"),
        _event("2026-11-04", phase="Phase 2", name="MarketedP2", pct=0.5),
        _event("2026-12-01", name="Dup", ind="Asthma", nct="NCT10", conf="estimated"),
        _event("2026-12-15", name="Dup", ind="Asthma", nct="NCT11", conf="estimated"),
        _event("2026-12-15", name="Dup", ind="COPD", nct="NCT12", conf="estimated"),
        _event("2027-01", name="Mo", prec="month", conf="month"),
        _event("2026-10-20", kind="regulatory decision", phase=None, name="Dec", reg=True),
        _event("2026-10-25", kind="adcom", phase=None, name="Adc")]


def test_readouts_are_the_dated_events_that_can_move_the_value_soonest_first(view):
    out = view["_ki_readouts"](_events(), dt.date(2026, 10, 2), shown=20)
    assert [(r["asset"], r["short"], r["date_text"]) for r in out["rows"]] == [
        ("Dec", "decision", "20 Oct 2026"),            # a regulatory date
        ("Adc", "AdCom", "25 Oct 2026"),               # an advisory committee is one too
        ("BigP2", "Ph 2", "3 Nov 2026"),               # an unapproved compound worth 1%
        ("Reg", "PDUFA", "20 Nov 2026"),
        ("Dup", "Ph 3", "est. Dec 2026"),              # three trials in one month: one row
        ("Mo", "Ph 3", "est. Jan 2027")]               # the registry's month is an estimate
    names = {r["asset"] for r in out["rows"]}
    # Past, a small Phase 2 and a marketed product's Phase 2 are not readouts the value
    # turns on.
    assert not names & {"Past", "SmallP2", "MarketedP2"}
    # Its indications are joined, each once.
    assert [r["indication"] for r in out["rows"] if r["asset"] == "Dup"] == ["Asthma, COPD"]
    assert next(r for r in out["rows"] if r["asset"] == "Reg")["event"] == "PDUFA date"
    assert next(r for r in out["rows"] if r["asset"] == "BigP2")["pipeline"] is True
    assert next(r for r in out["rows"] if r["asset"] == "Adc")["event"] == "advisory committee"
    assert (out["more"], out["total"]) == (0, 6)
    short = view["_ki_readouts"](_events(), dt.date(2026, 10, 2), shown=3)
    assert [r["asset"] for r in short["rows"]] == ["Dec", "Adc", "BigP2"]
    assert short["more"] == 3


def test_a_phase_2_of_a_compound_the_model_does_not_value_is_a_readout(view):
    items = [_event("2026-11-03", phase="Phase 2", name="Unvalued", marketed=False),
             _event("2026-11-04", phase="Phase 1/2", name="Early", marketed=False),
             _event("2026-11-05", phase="Phase 2", name="Sold", marketed=True)]
    out = view["_ki_readouts"](items, dt.date(2026, 10, 2), shown=20)
    assert [r["asset"] for r in out["rows"]] == ["Unvalued"]


def test_a_date_is_an_estimate_unless_it_was_confirmed_or_stated(view):
    items = [_event("2026-11-20", conf="estimated", name="EstDay"),
             _event("2026-11-21", conf="stated", name="Stated"),
             _event("2026-11-22", conf="confirmed", name="Conf"),
             _event("2027-01", prec="month", conf="confirmed", name="ConfMonth"),
             _event("2027-01", prec="month", conf="month", name="RegMonth"),
             _event("2027-02-15", prec="quarter", conf="quarter", name="Q1"),
             _event("2027-12-31", prec="quarter", conf="quarter", name="Q4"),
             _event("2027-06-30", prec="half", conf="half", name="H1"),
             _event("2027-10-01", prec="half", conf="half", name="H2")]
    out = view["_ki_readouts"](items, dt.date(2026, 10, 2), shown=20)
    assert [(r["asset"], r["when"], r["date_text"], r["estimated"]) for r in out["rows"]] == [
        ("EstDay", "Nov 2026", "est. Nov 2026", True),     # an estimated day is its month
        ("Stated", "21 Nov 2026", "21 Nov 2026", False),
        ("Conf", "22 Nov 2026", "22 Nov 2026", False),
        ("ConfMonth", "Jan 2027", "Jan 2027", False),
        ("RegMonth", "Jan 2027", "est. Jan 2027", True),
        ("Q1", "Q1 2027", "est. Q1 2027", True),           # a quarter is no date
        ("H1", "H1 2027", "est. H1 2027", True),
        ("H2", "H2 2027", "est. H2 2027", True),
        ("Q4", "Q4 2027", "est. Q4 2027", True)]


def test_a_regulatory_date_with_no_asset_is_named_from_its_title(view):
    def reg(date, kind, title, **kw):
        return dict({"date": date, "date_precision": "day", "date_confidence": "confirmed",
                     "kind": kind, "title": title}, **kw)

    items = [reg("2026-11-20", "pdufa", "Baxdrostat, hypertension", regulatory=True,
                 asset=None),
             reg("2026-12-01", "pdufa", "Sonrotoclax PDUFA date for CLL", regulatory=True),
             reg("2026-12-05", "adcom", "Phase 3, Zibotentan AdCom"),
             reg("2026-12-06", "ema decision", "Datroway EMA opinion"),
             reg("2026-12-07", "regulatory decision", "x", regulatory=True,
                 asset={"name": "Enhertu (fam-trastuzumab)", "is_marketed": True})]
    out = view["_ki_readouts"](items, dt.date(2026, 10, 2), shown=20)
    assert [(r["asset"], r["short"], r["event"], r["pipeline"]) for r in out["rows"]] == [
        ("Baxdrostat", "PDUFA", "PDUFA date", True),       # no asset: not yet approved
        ("Sonrotoclax", "PDUFA", "PDUFA date", True),
        ("Zibotentan", "AdCom", "advisory committee", True),
        ("Datroway", "EMA", "EMA decision", True),
        ("Enhertu", "decision", "regulatory decision", False)]   # a product on sale
    assert out["rows"][0]["date_text"] == "20 Nov 2026"
    # A code in brackets after the name is not part of it.
    coded = view["_ki_readouts"]([reg("2026-12-01", "pdufa",
                                      "Sonrotoclax (BGB-11417) PDUFA date for CLL",
                                      regulatory=True)], dt.date(2026, 10, 2))
    assert coded["rows"][0]["asset"] == "Sonrotoclax"


def test_a_regimen_is_never_a_readout(view):
    items = [_event("2026-11-20", name="Fludarabine lymphodepletion regimen", marketed=False),
             _event("2026-11-21", name="Placebo", marketed=False),
             _event("2026-11-22", name="Standard of care", marketed=False),
             _event("2026-11-23", name="Real", marketed=False)]
    out = view["_ki_readouts"](items, dt.date(2026, 10, 2), shown=20)
    assert [r["asset"] for r in out["rows"]] == ["Real"]
    # Nor does the registry's fill add one, or a study past eight years.
    programmes = [{"name": "Chemotherapy alone",
                   "studies": [{"phase": "Phase 3", "due": "2027-05-01"}]},
                  {"name": "Far", "studies": [{"phase": "Phase 3", "due": "2035-05-01"}]},
                  {"name": "Ext", "studies": [{"phase": "Phase 3", "due": "2027-05-01",
                                               "title": "Open-label extension"}]},
                  {"name": "Next", "studies": [{"phase": "Phase 3", "due": "2027-06-01"}]}]
    out = view["_ki_readouts"]([], dt.date(2026, 10, 2), shown=5, programmes=programmes)
    assert [r["asset"] for r in out["rows"]] == ["Next"]


def test_short_of_a_full_list_the_registrys_later_readouts_fill_it(view):
    programmes = [
        {"name": "Far", "area": "Oncology",
         "studies": [{"phase": "Phase 3", "due": "2028-05-01", "nct_id": "NCT9"}]},
        {"name": "BigP2", "studies": [{"phase": "Phase 2", "due": "2028-01-01"}]},  # listed
        {"name": "Near", "studies": [{"phase": "Phase 2", "due": "2026-10-10"}]},   # inside
        {"name": "Other", "area": "Other",
         "studies": [{"phase": "Phase 1", "due": "2027-06-01"}]}]
    today = dt.date(2026, 10, 2)
    out = view["_ki_readouts"](_events()[3:4], today, shown=5, programmes=programmes)
    # A Phase 1 study does not fill the list while a later readout is on file.
    assert [(r["asset"], r["date_text"], r.get("area")) for r in out["rows"]] == [
        ("BigP2", "3 Nov 2026", None),
        ("Far", "est. May 2028", "oncology")]
    assert all(r["estimated"] and r["pipeline"] for r in out["rows"][1:])  # registry dates
    assert out["rows"][1]["tip"] == "Far · NCT9 · primary completion, registry estimate"
    # A full list is not filled.
    full = view["_ki_readouts"](_events(), today, shown=3, programmes=programmes)
    assert [r["asset"] for r in full["rows"]] == ["Dec", "Adc", "BigP2"]


@pytest.mark.parametrize("ticker, head", [
    ("AZN", ["Truqap", "Saphnelo", "Enhertu", "Fasenra", "Imfinzi"]),
    ("LLY", ["Foundayo", "Retatrutide", "Zepbound", "LY3537021", "Ixo-vec"])])
def test_the_saved_readouts_are_late_stage_and_valued_events_soonest_first(view, board, ticker,
                                                                         head):
    items = _ctx(ticker)["catalysts"]["items"]
    out = view["_ki_readouts"](items, _today(board), prose=drivers.indication_prose,
                               min_pct=drivers.DRIVER_MIN_PCT)
    assert [r["asset"] for r in out["rows"]] == head
    dates = [r["date"] for r in out["rows"]]
    assert dates == sorted(dates)
    # Every saved date is the registry's: an estimate.
    assert all(r["estimated"] and r["date_text"].startswith("est. ") for r in out["rows"])
    if ticker == "LLY":
        # LLY's two Zepbound type 1 diabetes trials in November are one row.
        assert [r["asset"] for r in out["rows"]].count("Zepbound") == 1
        assert out["rows"][1]["pipeline"] and out["rows"][2]["indication"] == (
            "type 1 diabetes mellitus")
        # A Phase 2 of a compound the model does not value is listed.
        assert out["rows"][3]["short"] == "Ph 2" and out["rows"][3]["pipeline"]
    # A tiny Phase 2 of a compound the model values is not on the list.
    assert "Volrustomig" not in {r["asset"] for r in out["rows"]}
    assert "LY4515100" not in " ".join(r["asset"] for r in out["rows"])


def test_the_readouts_list_marks_an_estimated_date_and_says_how_many_more(view, board):
    out = view["_ki_readouts"](_ctx("LLY")["catalysts"]["items"], _today(board),
                               prose=drivers.indication_prose, min_pct=drivers.DRIVER_MIN_PCT)
    markup = view["_ki_readouts_html"](out)
    pattern = (r'<div class="ki-ro" title="[^"]*"><span class="d"><i>(.)</i>([^<]*)</span>'
               r'<span class="n( pipeline)?">([^<]*)</span><span class="w">([^<]*)</span>')
    rows = re.findall(pattern, markup)
    assert rows[0] == ("○", "Nov 2026", "", "Foundayo", "Ph 3 · overweight")
    assert rows[1] == ("○", "Nov 2026", " pipeline", "Retatrutide", "Ph 3 · obesity")
    assert rows[4] == ("○", "Dec 2026", " pipeline", "Ixo-vec", "Ph 3")  # the phase alone
    assert f'<div class="ki-ro more">{out["more"]} more on Catalysts</div>' in markup
    # A confirmed date is a filled mark and its day.
    confirmed = view["_ki_readouts_html"](view["_ki_readouts"](
        [_event("2026-11-20", kind="pdufa", phase=None, name="Reg", marketed=False, reg=True)],
        dt.date(2026, 10, 2)))
    assert re.findall(pattern, confirmed) == [("●", "20 Nov 2026", " pipeline", "Reg", "PDUFA")]
    assert "more on Catalysts" not in confirmed
    assert _text(view["_ki_readouts_html"]({})) == (
        "No late-stage readout or regulatory date is on file for the next 12 months.")


# --- loss of exclusivity ---------------------------------------------------------------------
def _expiry_record():
    return {"periods": {"FY0": {"label": "FY2025", "revenue_usd_m": 1000.0}},
            "detail": {"products": {"fiscal_year": 2025, "rows": [
                {"name": "Lynparza", "value_usd_m": 56.0},
                {"name": "Farxiga", "value_usd_m": 80.0},
                {"name": "Koselugo", "value_usd_m": 11.0}]}}}


EXPIRY_EXCLUSIVITIES = [
    {"asset_id": 240, "brand_name": "Farxiga", "loe": "2026-04-04", "loe_basis": "compound patent"},
    {"asset_id": 196, "brand_name": "Farxiga", "loe": "2027-04-04", "loe_basis": "compound patent"},
    {"asset_id": 67, "brand_name": "Lynparza", "loe": "2027-09-08",
     "loe_basis": "drug substance patent"},
    {"asset_id": 62, "brand_name": "Koselugo", "loe": "2028-03-13",
     "loe_basis": "drug substance patent"},
    {"asset_id": 5, "brand_name": "Imfinzi", "loe": "2031-12-31",
     "loe_basis": "20-F, U.S. new molecular entity patent (2031)"},
    {"asset_id": 6, "brand_name": "Unsold", "loe": "2027-01-01", "loe_basis": "orphan exclusivity"}]

EXPIRY_VERDICT = {"modelled": [
    {"asset_id": 5, "name": "Imfinzi", "per_share": 8.89, "counted": True, "is_marketed": True,
     "loe_year": 2031},
    {"asset_id": 240, "name": "Farxiga", "per_share": 5.47, "counted": True, "is_marketed": True,
     "loe_year": 2032},
    {"asset_id": 7, "name": "Beyfortus", "per_share": 2.0, "counted": True, "is_marketed": True,
     "loe_year": 2035, "loe_in_base": False},
    {"asset_id": 8, "name": "This year", "per_share": 2.0, "counted": True, "is_marketed": True,
     "loe_year": 2026, "loe_in_base": False},
    {"asset_id": 9, "name": "In base", "per_share": 2.0, "counted": True, "is_marketed": True,
     "loe_year": 2030, "loe_in_base": True}]}


def test_expiries_are_the_next_losses_of_the_products_that_matter(view):
    losses = [{"asset": "Lynparza", "asset_id": 67, "date": "2027-09-08", "share_text": "5.6%"}]
    out = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, EXPIRY_VERDICT, _expiry_record(), losses,
                               dt.date(2026, 10, 2), True)
    assert [(r["when"], r["asset"], r["share_text"], r["value"]) for r in out["rows"]] == [
        # Farxiga's first application lapsed in April 2026; its later one has not, and a
        # date already gone never hides it.
        ("4 Apr 2027", "Farxiga", "8.0%", None),
        ("8 Sep 2027", "Lynparza", "5.6%", None),     # the scorecard's own share
        ("13 Mar 2028", "Koselugo", "1.1%", None),    # its share of the year's revenue
        ("2031", "Imfinzi", "", 8.89),                # a year the filer gave, and its value
        ("2035", "Beyfortus", "", 2.0)]               # not in the file: the model's LOE year
    assert [r["kind"] for r in out["rows"]] == ["patent", "patent", "patent", "patent",
                                                "model year"]
    assert out["rows"][2]["share"] == pytest.approx(0.011)
    names = {r["asset"] for r in out["rows"]}
    # A model year that is this year cannot say whether the day has passed; one already in
    # the base is no loss ahead; an orphan term is no loss of exclusivity.
    assert not names & {"This year", "In base", "Unsold"}
    assert out["more"] == 0
    # "all" holds every material row, for the note's loss of exclusivity.
    assert out["all"] == out["rows"]
    two = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, EXPIRY_VERDICT, _expiry_record(), losses,
                               dt.date(2026, 10, 2), True, shown=2)
    assert len(two["rows"]) == 2 and two["more"] == 3
    assert two["all"] == out["all"]


def test_with_nothing_material_every_expiry_is_listed(view):
    out = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, {}, {}, [], dt.date(2026, 10, 2), False)
    # Unsold's orphan term is not a loss of exclusivity, material or not.
    assert [(r["when"], r["asset"]) for r in out["rows"]] == [
        ("4 Apr 2027", "Farxiga"), ("8 Sep 2027", "Lynparza"), ("13 Mar 2028", "Koselugo"),
        ("2031", "Imfinzi")]
    # Not modelled, the model's values and years are not read.
    assert all(r["value"] is None for r in out["rows"])
    assert view["_ki_expiries"]([], EXPIRY_VERDICT, {}, [], dt.date(2026, 10, 2), False) == {
        "rows": [], "more": 0, "all": []}


def test_the_scorecards_own_loss_date_wins_for_its_products(view):
    losses = [{"asset": "Lynparza", "asset_id": 67, "date": "2028-01-15",
               "basis": "patent settlement", "share_text": "5.6%", "share_of_revenue": 0.0558}]
    out = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, {}, {}, losses, dt.date(2026, 10, 2), False)
    lynparza = next(r for r in out["rows"] if r["asset"] == "Lynparza")
    assert (lynparza["when"], lynparza["kind"], lynparza["share_text"]) == (
        "15 Jan 2028", "settlement", "5.6%")
    assert lynparza["share"] == pytest.approx(0.0558)
    assert lynparza["tip"] == "Lynparza · patent settlement"
    # Only its share is material, so it alone is listed.
    assert [r["asset"] for r in out["rows"]] == ["Lynparza"]


def test_a_product_the_model_carries_past_its_loe_is_never_listed(view):
    excl = [{"asset_id": 8, "brand_name": "Symbicort", "loe": "2030-01-20",
             "loe_basis": "drug product patent"},
            {"asset_id": 9, "brand_name": "Pulmicort", "loe": "2031-01-20",
             "loe_basis": "drug product patent"},
            {"asset_id": 1, "brand_name": "Lynparza", "loe": "2027-09-08",
             "loe_basis": "drug substance patent"}]
    verdict = {"modelled": [
        {"asset_id": 8, "name": "Symbicort", "per_share": 7.0, "is_marketed": True,
         "loe_in_base": True},
        {"asset_id": 9, "name": "Pulmicort", "per_share": 1.0, "is_marketed": True,
         "loe_year": 2025},
        {"asset_id": 1, "name": "Lynparza", "per_share": 4.0, "is_marketed": True,
         "loe_year": 2027}]}
    out = view["_ki_expiries"](excl, verdict, {}, [], dt.date(2026, 10, 2), True)
    assert [(r["when"], r["asset"], r["value"]) for r in out["rows"]] == [
        ("8 Sep 2027", "Lynparza", 4.0)]
    # Not modelled, the model's lapses are not read.
    plain = view["_ki_expiries"](excl, verdict, {}, [], dt.date(2026, 10, 2), False)
    assert [r["asset"] for r in plain["rows"]] == ["Lynparza", "Symbicort", "Pulmicort"]
    # Lapsed in the model, a product is not listed from the scorecard's losses either, nor
    # from a later row of its own.
    losses = [{"asset": "Symbicort", "asset_id": 8, "date": "2028-01-01", "share_text": "3.0%"},
              {"asset": "Brilinta", "asset_id": 10, "date": "2028-06-01", "share_text": "4.0%"}]
    later = excl + [{"asset_id": 8, "brand_name": "Symbicort", "loe": "2033-01-20",
                     "loe_basis": "drug product patent"}]
    lapsed = dict(verdict, modelled=verdict["modelled"] + [
        {"asset_id": 10, "name": "Brilinta", "per_share": 1.0, "is_marketed": True,
         "loe_in_base": True}])
    out = view["_ki_expiries"](later, lapsed, {}, losses, dt.date(2026, 10, 2), True)
    assert [r["asset"] for r in out["all"]] == ["Lynparza"]


def test_a_loss_the_scorecard_holds_outside_the_exclusivity_file_is_listed(view):
    """A product whose exclusivity is read from its filer (Keytruda, a 10-K date) is not in
    the exclusivity file; the scorecard's loss of it is listed all the same, its name as a
    name."""
    losses = [{"asset": "KEYTRUDA", "asset_id": 999, "date": "2028-12-31",
               "basis": "10-K, compound patent (2028)", "share_text": "48.7%",
               "share_of_revenue": 0.487}]
    out = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, {}, {}, losses, dt.date(2026, 10, 2),
                               False)
    assert [(r["when"], r["asset"], r["kind"], r["share_text"]) for r in out["rows"]] == [
        ("2028", "Keytruda", "patent", "48.7%")]
    assert out["rows"][0]["share"] == pytest.approx(0.487)
    assert out["rows"][0]["tip"] == "Keytruda · 10-K, compound patent (2028)"


def test_a_date_already_gone_never_hides_a_later_one_of_the_same_product(view):
    excl = [{"asset_id": 1, "brand_name": "JAKAVI", "loe": "2025-01-01",
             "loe_basis": "drug substance patent"},
            {"asset_id": 2, "brand_name": "JAKAVI", "loe": "2028-05-01",
             "loe_basis": "drug substance patent"}]
    out = view["_ki_expiries"](excl, {}, {}, [], dt.date(2026, 10, 2), False)
    assert [(r["when"], r["asset"]) for r in out["rows"]] == [("1 May 2028", "Jakavi")]


def test_an_orphan_term_never_hides_the_products_own_loss_of_exclusivity(view):
    """An orphan term guards one indication, not the molecule: the model's LOE year, or a
    later patent row of the same brand, is the product's loss."""
    excl = [{"asset_id": 5, "brand_name": "Koselugo", "loe": "2027-04-10",
             "loe_basis": "orphan drug exclusivity"}]
    verdict = {"modelled": [{"asset_id": 5, "name": "Koselugo", "per_share": 1.5,
                             "is_marketed": True, "loe_year": 2033}]}
    out = view["_ki_expiries"](excl, verdict, {}, [], dt.date(2026, 10, 2), True)
    assert [(r["when"], r["asset"]) for r in out["rows"]] == [("2033", "Koselugo")]
    patent = excl + [{"asset_id": 5, "brand_name": "Koselugo", "loe": "2030-06-01",
                      "loe_basis": "drug substance patent"}]
    out = view["_ki_expiries"](patent, verdict, {}, [], dt.date(2026, 10, 2), True)
    assert [(r["when"], r["asset"], r["kind"]) for r in out["rows"]] == [
        ("1 Jun 2030", "Koselugo", "patent")]


def test_each_expiry_is_dated_at_its_sources_precision_and_named_by_its_kind(view):
    excl = [{"asset_id": 1, "brand_name": "Lynparza", "loe": "2027-09-08",
             "loe_basis": "drug substance patent"},
            {"asset_id": 2, "brand_name": "Soliris", "loe": "2029-03-31",
             "loe_basis": "10-K, biosimilar entry (2029-03)"},
            {"asset_id": 3, "brand_name": "Ultomiris", "loe": "2035-12-31",
             "loe_basis": "12y reference product exclusivity (2035)"},
            {"asset_id": 4, "brand_name": "Brilinta", "loe": "2028-06-15",
             "loe_basis": "patent settlement"},
            {"asset_id": 6, "brand_name": "Calquence", "loe": "2030-01-20",
             "loe_basis": "new chemical entity"},
            {"asset_id": 11, "brand_name": "Gone", "loe": "2026-10-01",
             "loe_basis": "drug substance patent"},
            {"asset_id": 12, "brand_name": "Today", "loe": "2026-10-02",
             "loe_basis": "drug substance patent"}]
    out = view["_ki_expiries"](excl, {}, {}, [], dt.date(2026, 10, 2), False, shown=20)
    assert [(r["when"], r["asset"], r["kind"]) for r in out["rows"]] == [
        ("2 Oct 2026", "Today", "patent"),           # today is not yet past
        ("8 Sep 2027", "Lynparza", "patent"),
        ("15 Jun 2028", "Brilinta", "settlement"),
        ("Mar 2029", "Soliris", "exclusivity"),      # a month the filer gave
        ("20 Jan 2030", "Calquence", "exclusivity"),
        ("2035", "Ultomiris", "12y biologic")]       # a year the filer gave


@pytest.mark.parametrize("basis, kind", [
    ("drug substance patent", "patent"), ("compound patent", "patent"),
    ("orphan exclusivity", "orphan"), ("Orphan drug exclusivity", "orphan"),
    ("12y reference product exclusivity", "12y biologic"), ("biologic floor", "12y biologic"),
    ("BLA licensure (12y)", "12y biologic"), ("patent settlement", "settlement"),
    ("the model's LOE year", "model year"), ("new chemical entity", "exclusivity"),
    ("", "exclusivity"), (None, "exclusivity")])
def test_an_expirys_kind_is_two_words_from_its_basis(view, basis, kind):
    assert view["_ki_expiry_kind"](basis) == kind


def test_the_expiries_list_reads_date_product_kind_share_and_value(view):
    losses = [{"asset_id": 67, "share_text": "5.6%"}]
    out = view["_ki_expiries"](EXPIRY_EXCLUSIVITIES, EXPIRY_VERDICT, _expiry_record(), losses,
                               dt.date(2026, 10, 2), True, shown=3)
    markup = view["_ki_expiries_html"](out)
    rows = re.findall(r'<div class="ki-ex" title="([^"]*)"><span class="d">([^<]*)</span>'
                      r'<span class="n">([^<]*)</span><span class="w">([^<]*)</span>'
                      r'<span class="v">([^<]*)</span></div>', markup)
    assert rows == [
        ("Farxiga · compound patent", "4 Apr 2027", "Farxiga", "patent · 8.0% of revenue", ""),
        ("Lynparza · drug substance patent", "8 Sep 2027", "Lynparza",
         "patent · 5.6% of revenue", ""),
        ("Koselugo · drug substance patent", "13 Mar 2028", "Koselugo",
         "patent · 1.1% of revenue", "")]
    assert '<div class="ki-ex more">2 more on Portfolio</div>' in markup
    # A value a share is printed beside the product the model values.
    imfinzi = view["_ki_expiries_html"](view["_ki_expiries"](
        EXPIRY_EXCLUSIVITIES[4:5], EXPIRY_VERDICT, {}, [], dt.date(2026, 10, 2), True))
    assert re.search(r'<span class="d">2031</span><span class="n">Imfinzi</span>'
                     r'<span class="w">patent</span><span class="v">8.89</span>', imfinzi)
    assert _text(view["_ki_expiries_html"]({})) == "No loss of exclusivity ahead is on file."


# --- against the cohort ------------------------------------------------------------------------
def _record():
    return {"reporting_currency": "USD",
            "periods": {"FY0": {"label": "FY2025", "revenue_usd_m": 58739.0}},
            "detail": {"pipeline": {"compounds": {"Phase 1": 27, "Phase 1/2": 28,
                                                  "Phase 2": 12, "Phase 2/3": 0,
                                                  "Phase 3": 23, "Phase 4": 2}},
                       "products": {"fiscal_year": 2025, "rows": [
                           {"name": "Farxiga", "value_usd_m": 8400.0},
                           {"name": "Tagrisso", "value_usd_m": 7254.0}]}}}


def test_big_pharma_is_set_against_its_cohort_in_three_groups(view, board):
    ver = {"reported_revenue": [{"fiscal_year": 2023, "value": 45811.0},
                                {"fiscal_year": 2024, "value": 54073.0},
                                {"fiscal_year": 2025, "value": 58739.0}]}
    groups = view["_ki_cohort_table"](board, "AZN", _record(), ver)
    assert [(g["title"], g["sub"]) for g in groups] == [
        ("Financials", "58.7bn USD revenue, FY2025"),
        ("Pipeline", "90 compounds in trials"),       # Phase 1 to 3: a Phase 4 is on sale
        ("Marketed", "")]
    assert [[r["id"] for r in g["rows"]] for g in groups] == [
        ["rev_growth", "op_margin", "nd_ocf"], ["late_compounds", "late_per_rev"],
        ["loe_years", "top_product", "fresh_share"]]
    azn = board["companies"]["AZN"]
    cohort = {t for t, c in board["companies"].items() if c["cohort"] == "big_pharma"}
    # The measures print the scorecard's own value and place, so the tabs never disagree;
    # only a unit is shortened to fit the column.
    for g in groups:
        for row in g["rows"]:
            m = view["_ki_metric"](azn, (row["id"],))
            assert row["text"] == m["text"].replace(" years", "y")
            assert row["place_text"] == f"{m['place']} of {m['n']}"
            assert {p["ticker"] for p in row["peers"]} <= cohort - {"AZN"}
            assert row["median"] == board["cohorts"]["big_pharma"]["metric_medians"].get(row["id"])
    assert groups[2]["rows"][0]["text"] == "4.6y"


def test_a_clinical_company_is_set_against_its_cohort_on_funding_and_pipeline(view, board):
    groups = view["_ki_cohort_table"](board, "CRSP", {"detail": {"pipeline": {"compounds": {
        "Phase 1": 1, "Phase 1/2": 3}}}}, {})
    assert [g["title"] for g in groups] == ["Funding", "Pipeline"]
    assert [[r["id"] for r in g["rows"]] for g in groups] == [
        ["runway", "share_change"], ["mid_late_compounds", "trial_conc"]]
    crsp = board["companies"]["CRSP"]
    assert view["_ki_metric"](crsp, ("runway",))["text"] == "77 months"
    assert groups[0]["rows"][0]["text"] == "77mo"
    assert groups[1]["sub"] == "4 compounds in trials"


def test_a_commercial_company_without_net_debt_is_measured_on_its_runway(view, board):
    groups = view["_ki_cohort_table"](board, "INCY", {}, {})
    assert [r["id"] for r in groups[0]["rows"]] == ["rev_growth", "op_margin", "runway"]
    # With a net debt measure on file it is read instead.
    geared = copy.deepcopy(board)
    geared["companies"]["INCY"]["pillars"]["balance_sheet"]["metrics"].append(
        {"id": "nd_ocf", "value": 1.2, "text": "1.2×", "place": "best", "n": 3})
    groups = view["_ki_cohort_table"](geared, "INCY", {}, {})
    assert [r["id"] for r in groups[0]["rows"]] == ["rev_growth", "op_margin", "nd_ocf"]


def test_a_commercial_company_reads_its_unscored_exclusivity_and_says_why_when_none(view):
    board = {"method": {"metrics": {}, "reasons": {"no_product_revenue": "No product revenue"}},
             "cohorts": {"commercial": {}},
             "companies": {
                 "INCY": {"cohort": "commercial", "pillars": {}, "facts": {"other_metrics": [
                     {"id": "loe_years", "value": 2.6482, "text": "2.6 years"},
                     {"id": "top_product", "value": 0.6015, "text": "60%"}]}},
                 "ALNY": {"cohort": "commercial", "pillars": {}, "facts": {"other_metrics": [
                     {"id": "loe_years", "value": None, "reason": "no_product_revenue"}]}}}}
    incy = view["_ki_cohort_table"](board, "INCY", {}, {})
    assert [(g["title"], [(r["id"], r["text"]) for r in g["rows"]]) for g in incy] == [
        ("Marketed", [("loe_years", "2.6y"), ("top_product", "60%")])]
    alny = view["_ki_cohort_table"](board, "ALNY", {}, {})
    markup = view["_ki_cohort_html"](alny, {})
    # A group with no measure on file is one line with the reason, not a row of dots.
    assert re.findall(r'<div class="ki-ct none">([^<]*)</div>', markup) == ["No product revenue"]
    assert 'class="v none"' not in markup


def test_revenue_is_labelled_in_the_currency_its_rows_are_filed_in(view, board):
    ver = {"reported_revenue": [{"fiscal_year": 2024, "value": 2751.1},
                                {"fiscal_year": 2025, "value": 2869.9}]}
    groups = view["_ki_cohort_table"](board, "AZN", {"reporting_currency": "USD",
                                                     "row_currency": "EUR"}, ver)
    assert groups[0]["sub"] == "2.9bn EUR revenue, FY2025"
    # No reported revenue in the verdict: the record's own year, in dollars.
    assert view["_ki_cohort_table"](board, "AZN", _record(), {})[0]["sub"] == (
        "58.7bn USD revenue, FY2025")


def test_counts_are_plural_only_above_one(view, board):
    groups = view["_ki_cohort_table"](board, "AZN", {"detail": {"pipeline": {"compounds": {
        "Phase 1": 1}}}}, {})
    assert next(g for g in groups if g["title"] == "Pipeline")["sub"] == "1 compound in trials"
    assert view["_ki_plural"](1, "product") == "1 product"
    assert view["_ki_plural"](2, "product") == "2 products"


def test_a_measure_with_no_value_prints_a_dot_and_its_reason(view, board):
    adapy = board["companies"]["ADAPY"]
    m = view["_ki_metric"](adapy, ("op_margin",))
    row = view["_ki_peer_row"](board, "ADAPY", m)
    assert row["value"] is None and row["reason"]
    groups = view["_ki_cohort_table"](board, "ADAPY", {}, {})
    fin = groups[0]
    assert fin["title"] == "Financials" and [r["id"] for r in fin["rows"]] == [
        "rev_growth", "op_margin", "runway"]
    strips = {"runway": "<svg>strip</svg>"}
    markup = view["_ki_cohort_html"]([fin], strips)
    assert markup.count('class="v none"') == 2
    assert f'<div class="ki-ct" title="{html.escape(row["reason"], quote=True)}">' in markup
    # The measure on file is drawn: its strip, its value and its place.
    assert re.search(r'<span class="s"><svg>strip</svg></span><span class="v">2mo</span>'
                     r'<span class="p down">worst of 19</span>', markup)


def test_a_reason_is_filled_never_a_template(view):
    reasons = {"partial_product_revenue": "Product revenue on file covers {c}% of revenue"}
    filled = {"reason": "partial_product_revenue",
              "reason_text": "Product revenue on file covers 17% of revenue"}
    assert view["_ki_reason"](filled, reasons) == "Product revenue on file covers 17% of revenue"
    assert "{" not in view["_ki_reason"]({"reason": "partial_product_revenue"}, reasons)


# --- What changed ---------------------------------------------------------------------------
def _feed():
    return [
        {"kind": "change", "significance": "high", "ticker": "AZN", "date": "2026-09-28",
         "change_type": "press_deal", "reason": "deal",
         "headline": "AZN AstraZeneca announces strategic equity investment and clinical  "
                     "collaboration with Summit Therapeutics to advance  leading ADC "
                     "combination strategy in cancer"},
        {"kind": "change", "significance": "high", "ticker": "AZN",
         "date": "2026-09-25 05:35:23", "change_type": "date_slip", "reason": "slipped 241d",
         "headline": "AZN trial NCT06455449: primary completion slips 2027-05-14 -> 2028-01-10"},
        {"kind": "change", "significance": "high", "ticker": "AZN", "date": "2026-09-05",
         "change_type": "revenue_restatement", "reason": "restated over 5%",
         "headline": "AZN restated Datroway FY2025: 2000000.0 -> 79000000.0"},
        {"kind": "market", "significance": "high", "ticker": None, "date": "2026-10-01",
         "change_type": "rate_move", "headline": "The 10-year Treasury 5.26%"},
        {"kind": "catalyst", "significance": "high", "ticker": "AZN", "date": "2026-09-20",
         "change_type": "data readout", "headline": "AZN data readout: Phase 3"},
        {"kind": "change", "significance": "medium", "ticker": "AZN", "date": "2026-09-29",
         "change_type": "date_slip", "headline": "AZN trial NCT1: slips"},
        {"kind": "change", "significance": "high", "ticker": "AZN", "date": "2026-08-01",
         "change_type": "press_approval", "headline": "AZN old approval"},
        {"kind": "change", "significance": "high", "ticker": "AZNX", "date": "2026-09-27",
         "change_type": "press_approval", "headline": "AZNX another company"},
        {"kind": "filing", "significance": "high", "ticker": "AZN", "date": "2026-09-23",
         "change_type": "material event", "reason": "material 8-K item",
         "url": "https://www.sec.gov/x.htm", "headline": "AZN 8-K: Material agreement signed"},
    ]


def test_what_changed_keeps_the_companys_high_changes_of_30_days_newest_first(view):
    rows = view["_ki_changes"](_feed(), "AZN", dt.date(2026, 10, 1))
    # The slip stays: the readouts list is what is ahead, not what moved.
    assert [r["change_type"] for r in rows] == ["press_deal", "date_slip", "material event"]
    assert view["_ki_changes_basis"](len(rows)) == "3 of 3 in 30 days"
    # Three shown; News has the rest.
    assert view["_KI_CHANGES_SHOWN"] == 3
    assert view["_ki_changes_basis"](10) == "3 of 10 in 30 days"


def test_a_change_row_drops_the_ticker_and_keeps_the_whole_headline_on_hover(view):
    rows = view["_ki_changes"](_feed(), "AZN", dt.date(2026, 10, 1))
    deal = view["_ki_change_row"](rows[0], "AZN")
    shown = re.search(r'<span class="t">([^<]*)</span>', deal).group(1)
    assert shown == "AstraZeneca announces strategic equity investment and…"  # at a word
    assert len(shown) <= view["_KI_HEADLINE_CHARS"]
    assert "collaboration with Summit Therapeutics to advance leading ADC" in deal  # the title
    slip = view["_ki_change_row"](rows[1], "AZN")
    # Longer than the cut, kept whole: a diff row's meaning is in its tail.
    assert ">Trial NCT06455449: primary completion slips 2027-05-14 -&gt; 2028-01-10<" in slip
    filing = view["_ki_change_row"](rows[2], "AZN")
    assert filing.startswith('<a title="8-K: Material agreement signed · material 8-K item" '
                             'class="fitem link"')
    for markup in (deal, slip, filing):
        assert not re.search(r'<span class="t">AZN ', markup)
        # The date and the headline only: the severity and the reason are on hover.
        assert 'class="why"' not in markup and 'class="s ' not in markup
        assert re.findall(r'<span class="(\w+)">', markup) == ["d", "t"]


# --- house style ----------------------------------------------------------------------------
def test_every_string_the_tab_adds_is_in_house_style(view, board):
    fixed = [v for k, v in view.items() if k.startswith("_KI_") and isinstance(v, str)]
    fixed += list(view["_KI_SHORT"].values()) + list(view["_KI_REG_EVENTS"].values())
    fixed += list(view["_KI_PHASE_SHORT"].values()) + list(view["_KI_COUNT_WORDS"])
    made = []
    series = view["_ki_year_series"](_points(400))
    today = _today(board)
    for ticker, company in board["companies"].items():
        call = view["_ki_call"](AZN_RATED if ticker == "AZN" else {}, "no sum of the parts",
                                series, AZN_STREET if ticker == "AZN" else None)
        mom = view["_ki_metric"](company, ("rel_1y",))
        mult = (company.get("facts") or {}).get("multiple")
        business = view["_ki_business_figures"](_business_record(), AZN_REVENUE, company,
                                                ticker == "AZN", EXPIRY_EXCLUSIVITIES)
        made.append(_text(view["_ki_call_html"](call, view["_ki_figures"](
            series, call, mom, AZN_STREET, mult, None), business)))
        made += [tip for *_, tip in business]
        made.append(_text(view["_ki_cohort_html"](
            view["_ki_cohort_table"](board, ticker, _record(), {}), {})))
        cohort = board["cohorts"][company["cohort"]]
        for kw in ({"modelled": False, "street": {"value": 60.0}}, {"modelled": False},
                   {"rated": {"ok": False, "reason": "no share price on file"}},
                   {"rated": _rated(), "sotp": SOTP_AHEAD}):
            made += _brief(view, ticker, company=company, cohort=cohort, **kw)["paragraphs"]
    for ticker in ("AZN", "LLY", "CRSP"):
        readouts = view["_ki_readouts"](_ctx(ticker)["catalysts"]["items"], today,
                                        prose=drivers.indication_prose,
                                        min_pct=drivers.DRIVER_MIN_PCT)
        made.append(_text(view["_ki_readouts_html"](readouts)))
        changes = view["_ki_changes"](_saved_feed(ticker), ticker, today)
        made += [view["_ki_event_words"](it, ticker, cut) for it in changes
                 for cut in (True, False)]
        brief = _brief(view, ticker, series=_trading(-0.029, -0.065), changes=changes,
                       events=readouts["rows"], company=board["companies"][ticker],
                       cohort=board["cohorts"][board["companies"][ticker]["cohort"]])
        made.append(_text(view["_ki_brief_html"](brief, "from the figures on this page")))
        made.append(brief["facts"])
    azn = _azn_brief(view, board)
    made += azn["paragraphs"] + [azn["facts"]]
    for month, year, changes in ((-0.029, -0.065, GOOD), (0.03, 0.1, GOOD),
                                 (-0.029, -0.065, BAD), (-0.029, -0.065, [])):
        for rel_1m in (None, 0.01, 0.05):
            made += _brief(view, "AZN", series=_trading(month, year), changes=changes,
                           rel_1m=rel_1m, rel_1y={"value": -0.06})["paragraphs"]
    for base in (15.0, 56.0):
        for close in (38.0, 50.0, 70.0):
            made += _brief(view, series={"close": close}, rated=_rated(close, 60.0, "Hold", base),
                           sotp=SOTP_AHEAD)["paragraphs"]
    made += _brief(view, rating_failed="timed out")["paragraphs"]
    made += _brief(view, modelled=False, failed="timed out")["paragraphs"]
    modelled = view["_ki_key_assets"](_azn_verdict(), {}, AZN_PROGRAMMES, AZN_EXCLUSIVITIES,
                                      today, True)
    plain = view["_ki_key_assets"]({}, _mix_record(), _programmes(), [], today, False)
    made += [_text(view["_ki_key_assets_html"](modelled)),
             _text(view["_ki_key_assets_html"](plain)),
             _text(view["_ki_expiries_html"](view["_ki_expiries"](
                 EXPIRY_EXCLUSIVITIES, EXPIRY_VERDICT, _expiry_record(), [], today, True))),
             _text(view["_ki_expiries_html"](view["_ki_expiries"](
                 EXPIRY_EXCLUSIVITIES, {}, {}, [], today, False))),
             view["_ki_changes_basis"](10)]
    made += [r["tip"] for part in ("marketed", "pipeline") for r in modelled[part]["rows"]]
    # The sentences this revision added: a model that values nothing on sale, one short of
    # revenue, the business read alone, news rated lower, the losses grouped and the largest.
    made += _brief(view, rated=_rated(), sotp={"marketed": {"n": 0}, "net_cash_per_share": 16.24,
                                               "pipeline": {"per_share": 0.58},
                                               "future": {"per_share": 0.52}})["paragraphs"]
    made += _brief(view, rated=_rated(), sotp=dict(SOTP_AHEAD, marketed={"n": 5}),
                   coverage={"share": 0.72})["paragraphs"]
    stale = {"reported_revenue": [{"fiscal_year": 2022, "value": 520.0}]}
    for biz in (view["_ki_business_figures"](_business_record(), AZN_REVENUE, None, False,
                                             EXPIRY_EXCLUSIVITIES),
                view["_ki_business_figures"](_record(), stale, None, False, None)):
        made += [tip for *_, tip in biz]
        made += _brief(view, modelled=False, business=biz)["paragraphs"]
    lower = [dict(_news("status_change", "AZN trial NCT1: Phase 2 -> Phase 3", "2026-09-10"),
                  significance="medium")]
    for rel_1m in (None, 0.01, 0.05):
        made += _brief(view, series=_trading(-0.029, -0.065), changes=lower,
                       rel_1m=rel_1m)["paragraphs"]
    losses = [_loss("Janumet", "2026-11-24", 0.019, "24 Nov 2026"),
              _loss("Januvia", "2026-11-24", 0.020, "24 Nov 2026"),
              _loss("Mid", "2027-01-01", 0.11, "1 Jan 2027"),
              _loss("Eliquis", "2028-04-01", 0.20, "1 Apr 2028")]
    for n in range(1, len(losses) + 1):
        made += _brief(view, modelled=False, expiries={"all": losses[:n]})["paragraphs"]
    made += _brief(view, rated=_rated(), breaks=view["_ki_breaks"](
        dict(AZN_BP, levers=AZN_BP["levers"][:1])))["paragraphs"]
    made += [view["_ki_event_words"]({"headline": h, "date": "2026-09-10"}, t, cut)
             for t, h in (("ABBV", "ABBV CMS selects 1 drug(s) for Medicare price negotiation, "
                                   "IPAY 2028: BOTOX"),
                          ("NVS", "NVS CMS has deselected ENTRESTO from Medicare price "
                                  "negotiation (5 NDCs). Review: x"),
                          ("AZN", "AZN Pivotal FDA APPROVAL FOR GLP-1 BLA"),
                          ("AZN", "AZN 8-K: Material agreement signed, Material impairment, "
                                  "and 3 more"))
             for cut in (True, False)]
    for text in fixed + made:
        _house_style(text)
    # Sentence case: the fixed sentences and the empty states open on a capital and carry
    # no other title case, bar the names of the tabs they point to.
    for name in ("_KI_FAILED", "_KI_NO_CHANGES", "_KI_NO_BRIDGE", "_KI_NOT_MODELLED"):
        _sentence_case(view[name])
    empty = view["_ki_key_assets_html"]({})
    for text in (re.findall(r'<div class="ki-ka none">([^<]*)</div>', empty)
                 + [_text(view["_ki_readouts_html"]({})), _text(view["_ki_expiries_html"]({}))]):
        _sentence_case(text)


# --- the pictures ---------------------------------------------------------------------------
def _colours(svg):
    return {c.upper() for c in re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{6})"', svg)}


def test_price_call_draws_the_gutter_only_for_what_exists_and_joins_nothing(view):
    closes = [100.0, 104.0, None, 108.0, 106.0]
    dates = ["2025-10-01", "2026-01-02", "2026-04-01", "2026-07-01", "2026-10-01"]
    full = charts.price_call(closes, dates, 106.0,
                             model={"mid": 130.0, "low": 120.0, "high": 140.0, "tone": "up",
                                    "tip": "model"},
                             street={"value": 125.0, "tip": "street"})
    ET.fromstring(full)
    assert "in 12 months" in full and ">model 130<" in full and ">street 125<" in full
    assert 'class="reference"' in full                      # the close runs on, dashed
    assert full.count("<polyline") == 2                     # the null splits the line
    bare = charts.price_call(closes, dates, 106.0)
    assert "in 12 months" not in bare and ">model" not in bare
    # One y label is no scale: a narrow domain retries for more ticks.
    narrow = charts.price_call([150.4, 226.2], ["2025-10-01", "2026-10-01"], 157.7)
    assert len(re.findall(r'text-anchor="end" font-family="[^"]*Mono', narrow)) >= 2
    assert charts.price_call([None, None], ["2026-01-01", "2026-01-02"], None) == ""
    # The model's twelve-month value sits inside the domain however far it is from the price.
    far = charts.price_call(closes, dates, 106.0, model={"mid": 40.0, "low": 30.0,
                                                         "high": 50.0, "tone": "down"})
    cy = float(re.search(r'<circle cx="[\d.]+" cy="([\d.]+)" r="4.5"', far).group(1))
    assert 0 < cy < 176


def test_peer_dots_put_better_on_the_right_and_hide_no_peer(view):
    peers = [{"ticker": "A", "value": 0.10, "text": "10%"},
             {"ticker": "B", "value": 0.20, "text": "20%"},
             {"ticker": "C", "value": 0.20, "text": "20%"}]
    focal = {"ticker": "X", "value": 0.15, "text": "15%"}
    hi = charts.peer_dots(peers, focal, better="higher", median=0.2, tone="up")
    lo = charts.peer_dots(peers, focal, better="lower", median=0.2, tone="up")
    ET.fromstring(hi)

    def x_of(svg, ticker):
        return float(re.search(rf'<circle cx="([\d.]+)"[^>]*><title>{ticker} ', svg).group(1))

    assert x_of(hi, "B") > x_of(hi, "A") and x_of(lo, "B") < x_of(lo, "A")
    # B and C tie: both are drawn, one offset so it is not hidden under the other.
    ys = re.findall(r'cy="([\d.]+)"[^>]*><title>[BC] ', hi)
    assert len(ys) == 2 and ys[0] != ys[1]
    assert "<title>median</title>" in hi and tokens.UP.upper() in _colours(hi)
    assert charts.peer_dots(peers, {"value": None}) == ""
    # The company is drawn once, as itself, even when it is in the peer list.
    with_me = charts.peer_dots(peers + [dict(focal)], dict(focal), median=0.2)
    assert with_me.count("<title>X ") == 1


def test_the_cohort_tables_strip_keeps_every_dot_inside_its_row(view):
    """The table draws each strip at 72 by 16: an offset tie and the company's dot fit."""
    peers = [{"ticker": t, "value": v, "text": ""} for t, v in
             (("A", 0.1), ("B", 0.2), ("C", 0.2), ("D", 0.2))]
    svg = charts.peer_dots(peers, {"ticker": "X", "value": 0.15}, width=72, height=16,
                           median=0.2, tone="down", label="Operating margin")
    ET.fromstring(svg)
    assert 'aria-label="Operating margin"' in svg               # the measure, for a reader
    for cx, cy, r in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', svg):
        assert 0 <= float(cx) - float(r) and float(cx) + float(r) <= 72
        assert 0 <= float(cy) - float(r) and float(cy) + float(r) <= 16


def test_the_pictures_take_their_colours_from_the_tokens(view):
    tok = {v.upper() for k, v in vars(tokens).items()
           if k.isupper() and isinstance(v, str) and v.startswith("#")}
    for name, vals in tokens.PHASE_RAMP.items():
        tok.add(vals.upper())
    svgs = [charts.price_call([1.0, 2.0], ["2026-01-01", "2026-10-01"], 2.0,
                              model={"mid": 3.0, "low": 2.5, "high": 3.5, "tone": "up"},
                              street={"value": 2.8}),
            charts.peer_dots([{"value": 1}], {"value": 2}, tone="down")]
    blended = {charts._blend(tokens.UP, tokens.GROUND, 0.45).upper()}
    for svg in svgs:
        assert _colours(svg) <= tok | blended, _colours(svg) - tok - blended


def test_the_retired_track_and_share_bar_are_gone(view):
    assert not hasattr(charts, "event_track") and not hasattr(charts, "share_bar")
    for name in ("_ki_rests_on", "_ki_rests_html", "_ki_breaks_html", "_ki_track_items",
                 "_ki_columns", "_ki_column_html", "_ki_rev_bars", "_ki_note_label"):
        assert name not in view, name


# --- charts.pillar_bars ---------------------------------------------------------------------
_TOKEN_COLOURS = {v.upper() for k, v in vars(tokens).items()
                  if k.isupper() and isinstance(v, str) and v.startswith("#")}


def _bars_rows():
    return [{"id": "growth", "label": "Growth", "score": 77, "median": 48},
            {"id": "profitability", "label": "Profitability", "score": 31, "median": 50},
            {"id": "balance_sheet", "label": "Balance sheet", "score": 12, "median": 52},
            {"id": "durability", "label": "Durability", "score": 62, "median": 50,
             "note": "4.6 years of exclusivity left"},
            {"id": "pipeline", "label": "Pipeline", "score": None, "median": 52,
             "reason": "No free data for any of its measures"},
            {"separator": "Price, not in the score"},
            {"id": "value", "label": "Value", "score": 46, "median": 49},
            {"id": "momentum", "label": "Momentum", "score": 9, "median": 56}]


def test_pillar_bars_draws_one_bar_a_scored_pillar_and_a_reason_for_the_rest():
    svg = charts.pillar_bars(_bars_rows())
    ET.fromstring(svg)
    assert svg.count('class="pb-bar"') == 6
    assert svg.count('class="pb-track"') == 6
    assert svg.count('class="pb-med"') == 6
    assert svg.count('class="pb-row"') == 7
    pipeline = re.search(r'<g class="pb-row" data-pillar="pipeline">(.*?)</g>', svg).group(1)
    assert "pb-bar" not in pipeline and "pb-num" not in pipeline      # a gap, never a zero
    assert 'class="pb-reason"' in pipeline and "No free data" in pipeline
    assert svg.count('class="pb-sep"') == 1 and "Price, not in the score" in svg
    assert re.search(r'<line x1="[\d.]+" y1="[\d.]+" x2="[\d.]+" y2="[\d.]+" stroke="'
                     + tokens.RULE_STRONG + '"[^>]*stroke-dasharray', svg)


def test_pillar_bars_prints_a_note_under_its_label():
    svg = charts.pillar_bars(_bars_rows())
    row = re.search(r'<g class="pb-row" data-pillar="durability">(.*?)</g>', svg).group(1)
    label_y = float(re.search(r'<text x="0.0" y="([\d.]+)"[^>]*class="pb-label"', row).group(1))
    note = re.search(r'<text x="0.0" y="([\d.]+)"[^>]*class="pb-note">([^<]*)</text>', row)
    assert float(note.group(1)) > label_y
    assert note.group(2) == "4.6 years of exclusivity left"


def test_pillar_bars_tones_the_extremes_and_takes_colours_from_tokens_only():
    svg = charts.pillar_bars(_bars_rows())
    fills = {c.upper() for c in re.findall(r'(?:fill|stroke)="(#[0-9A-Fa-f]{3,8})"', svg)}
    assert fills and fills <= _TOKEN_COLOURS
    assert "rgb(" not in svg and "hsl(" not in svg

    def bar(pid):
        row = re.search(rf'<g class="pb-row" data-pillar="{pid}">(.*?)</g>', svg).group(1)
        fill = re.search(r'class="pb-bar"[^>]*fill="(#[0-9A-Fa-f]+)"', row).group(1)
        num = re.search(r'fill="(#[0-9A-Fa-f]+)"[^>]*class="pb-num"', row).group(1)
        med = re.search(r'class="pb-med"[^>]*stroke="(#[0-9A-Fa-f]+)"', row).group(1)
        return fill, num, med

    assert bar("growth") == (tokens.UP, tokens.UP, tokens.TEXT)            # 77
    assert bar("balance_sheet") == (tokens.DOWN, tokens.DOWN, tokens.TEXT)  # 12
    assert bar("profitability") == (tokens.MUTED, tokens.TEXT, tokens.TEXT)  # 31
    assert bar("momentum") == (tokens.DOWN, tokens.DOWN, tokens.TEXT)       # 9
    assert tokens.RULE in svg                                               # the track


def test_pillar_bars_scales_each_bar_to_its_score_and_median():
    svg = charts.pillar_bars([{"id": "a", "label": "A", "score": 50, "median": 25},
                              {"id": "b", "label": "B", "score": 100, "median": None}],
                             width=520)
    track = float(re.search(r'class="pb-track"[^>]*width="([\d.]+)"', svg).group(1))
    widths = [float(w) for w in re.findall(r'class="pb-bar"[^>]*width="([\d.]+)"', svg)]
    assert widths == pytest.approx([track / 2, track], abs=0.11)
    assert svg.count('class="pb-med"') == 1                   # no median, no tick
    assert charts.pillar_bars([]) == ""


# --- the tab, through AppTest ----------------------------------------------------------------
def _api() -> str:
    return os.getenv("ER_API_BASE", "http://localhost:8000")


def _api_up() -> bool:
    try:
        with urllib.request.urlopen(_api() + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


def _get(path: str):
    with urllib.request.urlopen(_api() + path, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _patch_button_group_serialisation():
    """The AppTest defect test_forecast_tab_ui.py works around: a single-select
    segmented_control's value is a string, and ButtonGroup.indices iterates it."""
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


def _walk(block):
    """Every element under a block, depth first, in the order the script drew them."""
    for child in getattr(block, "children", {}).values():
        yield child
        yield from _walk(child)


def _tab(app, label):
    found = [t for t in app.tabs if t.label == label]
    assert found, f"no {label} tab"
    return found[0]


def _markdown(block) -> list:
    return [str(e.value) for e in _walk(block) if getattr(e, "type", "") == "markdown"]


def _labels(md: list) -> list:
    return [html.unescape(x) for m in md
            for x in re.findall(r'<span class="sec-label">([^<]*)</span>', m)]


live = pytest.mark.skipif(not _api_up(), reason="API not running on 8000")


@pytest.fixture(scope="module", params=["AZN", "LLY", "CRSP"])
def tab(request):
    """The tab as drawn, and every answer it was drawn from, read again through the API."""
    from streamlit.testing.v1 import AppTest

    _patch_button_group_serialisation()
    ticker = request.param
    test = AppTest.from_file(str(APP), default_timeout=180)
    test.query_params["ticker"] = ticker
    test.run()
    assert not test.exception, [str(e.value)[:400] for e in test.exception]
    t = urllib.parse.quote(ticker)
    payload = _get("/comps/valuation")
    record = next((c for c in payload.get("companies") or []
                   if isinstance(c, dict) and c.get("ticker") == ticker), None) or {}
    return {"ticker": ticker, "app": test, "tab": _tab(test, "Key insights"),
            "company": payload["scorecard"]["companies"][ticker],
            "today": dt.date.fromisoformat(str(payload["scorecard"]["today"])[:10]),
            "record": record,
            "context": _get(f"/companies/{t}/comps-context"),
            "verdict": _get(f"/companies/{t}/forecast-verdict"),
            "programmes": _get(f"/companies/{t}/programmes").get("programmes") or [],
            "exclusivities": _get(f"/companies/{t}/exclusivities").get("assets") or []}


@live
def test_the_live_call_reads_the_models_value_or_says_why_not(tab):
    body = "\n".join(_markdown(tab["tab"]))
    assert 'class="pos ki-call"' in body
    # Two rows of five figures under it: the market, then the business.
    assert 'class="ki-figs ki-biz"' in body
    assert body.count('<div class="ki-f" ') >= 10
    fv = _get(f"/companies/{tab['ticker']}/fair-value")
    rated = fv.get("rating") or {}
    if rated.get("ok") and rated.get("forward_12m") is not None:
        assert f">{rated['forward_12m']:,.2f}<" in body
        assert f">{rated['rating']}<" in body
    else:
        assert ("not rated" in body or "Not modelled" in body
                or "did not load" in body), "the call must say why there is no rating"


@live
def test_the_live_bridge_is_drawn_and_titled_by_its_own_end(tab, view):
    body = "\n".join(_markdown(tab["tab"]))
    v = tab["verdict"]
    if view["_ki_forecast_state"](v) != "modelled":
        return
    rated = _get(f"/companies/{tab['ticker']}/fair-value").get("rating") or {}
    b = view["_ki_bridge"](v["sotp"], rated.get("forward_12m") if rated.get("ok") else None)
    assert b["ok"], b["reason"]
    assert "ki-bridge" in body and "does not add up" not in body
    assert f"Where {b['end']:,.2f} comes from" in body


@live
def test_the_bridge_reconciles_for_every_modelled_company(view):
    """G7, over the whole book rather than three names: every company the forecast models
    draws a bridge whose ends are its equity (or enterprise value) and its twelve-month
    value, to the cent, against the rating's own figure."""
    tickers = [c["ticker"] for c in _get("/comps/valuation")["companies"]]
    checked, failed = 0, []
    for t in tickers:
        v = _get(f"/companies/{urllib.parse.quote(t)}/forecast-verdict")
        if view["_ki_forecast_state"](v) != "modelled":
            continue
        rated = _get(f"/companies/{urllib.parse.quote(t)}/fair-value").get("rating") or {}
        b = view["_ki_bridge"](v["sotp"], rated.get("forward_12m") if rated.get("ok") else None)
        checked += 1
        if not b["ok"]:
            failed.append((t, b["reason"]))
    assert checked >= 15 and not failed, failed


@live
def test_the_live_note_is_open_on_arrival_and_written_from_the_page(tab):
    body = "\n".join(_markdown(tab["tab"]))
    note = re.search(r'<span class="sec-label">Morning note</span>'
                     r'(?:<span class="sec-basis">([^<]*)</span>)?</div>'
                     r'<div class="ki-brief">(.*?)</div>', body, re.S)
    assert note, "the morning note must be in the band, not folded away"
    paras = re.findall(r"<p>(.*?)</p>", note.group(2), re.S)
    assert paras
    if note.group(1) == "from the figures on this page":
        # As built: the call, the trading, then what drives it, the opening sentence bold.
        lead = re.match(r"<b>([^<]+)</b>", paras[0])
        assert lead and lead.group(1).endswith("."), paras[0]
        assert 2 <= len(paras) <= 3
        for para in paras:
            _house_style(html.unescape(re.sub(r"</?b>", "", para)))
    notes = [e for e in _walk(tab["tab"]) if getattr(e, "type", "") == "expander"
             and str(getattr(e, "label", "")).startswith("Morning note")]
    assert not notes


@live
def test_the_live_readouts_list_the_soonest_events_that_can_move_the_value(tab, view):
    body = "\n".join(_markdown(tab["tab"]))
    assert "Readouts and decisions" in _labels(_markdown(tab["tab"]))
    context = tab["context"]
    items = (((context.get("catalysts") or {}).get("items") or [])
             if drivers.context_error(context) is None else [])
    readouts = view["_ki_readouts"](items, tab["today"], prose=drivers.indication_prose,
                                    min_pct=drivers.DRIVER_MIN_PCT,
                                    programmes=tab["programmes"])
    if not readouts["rows"]:
        assert "No late-stage readout or regulatory date is on file" in body
        return
    for r in readouts["rows"]:
        cls = "n pipeline" if r.get("pipeline") else "n"
        assert (f'{view["html_escape"](r["when"])}</span><span class="{cls}">'
                f'{view["html_escape"](r["asset"])}</span>') in body, r["asset"]


@live
def test_the_live_key_assets_and_expiries_are_the_models_largest_parts(tab, view):
    body = "\n".join(_markdown(tab["tab"]))
    labels = _labels(_markdown(tab["tab"]))
    assert "Key assets" in labels and "Loss of exclusivity" in labels
    modelled = view["_ki_forecast_state"](tab["verdict"]) == "modelled"
    assets = view["_ki_key_assets"](tab["verdict"], tab["record"], tab["programmes"],
                                    tab["exclusivities"], tab["today"], modelled)
    for kind in ("marketed", "pipeline"):
        assert len(assets[kind]["rows"]) <= view["_KI_ASSETS_SHOWN"]
        for r in assets[kind]["rows"]:
            assert f'<span class="n {kind}">{view["html_escape"](r["name"])}</span>' in body, \
                r["name"]
    expiries = view["_ki_expiries"](tab["exclusivities"], tab["verdict"], tab["record"],
                                    tab["company"].get("exclusivity_losses"), tab["today"],
                                    modelled)
    for r in expiries["rows"]:
        tail = (f'{view["html_escape"](r["when"])}</span>'
                f'<span class="n">{view["html_escape"](r["asset"])}</span>')
        # a loss inside the year carries the "near" class
        assert (f'<span class="d">{tail}' in body
                or f'<span class="d near">{tail}' in body), r["asset"]


@live
def test_the_live_cohort_table_names_its_rank_without_a_score(tab, view):
    body = "\n".join(_markdown(tab["tab"]))
    company = tab["company"]
    assert "ki-cohort" in body
    if company.get("rank") is not None:
        # The chip is the rank alone; "right is better" heads the first group instead.
        chip = f"{view['_ki_ord'](company['rank'])} of {company['ranked_of']}"
        assert f'<span class="sec-basis">{chip}</span>' in body
        assert '<b class="rb">right is better</b>' in body
    assert f"of {company.get('ranked_of')} · score" not in body


@live
def test_the_live_what_changed_leaves_restatements_and_rates_to_news(tab):
    ticker = tab["ticker"]
    block = next((m for m in _markdown(tab["tab"]) if "ki-changes" in m), "")
    assert "restated" not in block and "Treasury" not in block
    assert not re.search(rf'<span class="t">{ticker} ', block)
    assert block.count('class="fitem') <= 3


@live
def test_the_live_tab_drops_the_old_blocks(tab):
    md = _markdown(tab["tab"])
    labels = _labels(md)
    for gone in ("Company score", "Positives and negatives", "Next", "What it rests on",
                 "Drivers, risks and catalysts", "Upcoming readouts", "Patent expiries"):
        assert gone not in labels
    for kept in ("Morning note", "Readouts and decisions", "Key assets",
                 "Loss of exclusivity", "What changed"):
        assert kept in labels
    for label in labels:
        _sentence_case(label)
    body = "\n".join(md)
    for gone in ("ki-track", "ki-strip", "ki-sentence", 'class="ki-rests', 'class="ki-col',
                 'class="ki-brk', 'class="ki-key'):
        assert gone not in body, gone
    assert "What it rests on" not in body



def test_with_nothing_past_phase_1_the_registry_fill_takes_phase_1_but_never_volunteers(view):
    programmes = [
        {"name": "Early", "area": "Oncology", "studies": [{"phase": "Phase 1", "due": "2027-06-01"}]},
        {"name": "Volunteers", "area": "Healthy volunteers",
         "studies": [{"phase": "Phase 1", "due": "2027-03-01"}]}]
    out = view["_ki_readouts"]([], dt.date(2026, 10, 2), shown=5, programmes=programmes)
    assert [r["asset"] for r in out["rows"]] == ["Early"]
