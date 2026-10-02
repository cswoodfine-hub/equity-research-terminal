"""Key insights, the highlights of every tab (docs/design/key-insights.md).

Two layers. The tab's string builders live in the Streamlit script, which runs the whole
app on import, so they are read out of its source by name and run on the sample scorecard
(``fixtures/company_score/sample_scorecard.json``) and the saved comps-context answers of
``fixtures/drivers``; none of them touches Streamlit. The four pictures it draws
(``price_call``, ``event_track``, ``peer_dots``, ``share_bar``) and ``pillar_bars`` are
tested as the chart primitives they are. Then the tab itself, driven in-process through
AppTest against the API, which is skipped when the API is not up, like the other tab tests.
"""

from __future__ import annotations

import ast
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
# The extra names the builders call, read out of the script with them.
SHARED = ("html_escape", "change_row")


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


def _text(markup: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


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


def test_the_figure_cells_read_the_close_the_year_the_street_and_the_multiple(view, board):
    azn = board["companies"]["AZN"]
    series = view["_ki_year_series"](_points(400, start=168.7, end=157.70, prev=161.47))
    call = view["_ki_call"](AZN_RATED, None, series, AZN_STREET)
    mom = view["_ki_metric"](azn, ("rel_1y",))
    mult = azn["facts"]["multiple"]
    cells = view["_ki_figures"](series, call, mom, AZN_STREET, mult,
                                view["_ki_metric"](azn, (mult["metric"],)))
    values = [c[0] for c in cells]
    keys = [c[1] for c in cells]
    assert values[0] == "157.70" and keys[0] == "close · −2.3% today"
    assert keys[1] == f"1 year · {mom['text']} vs XLV" and cells[1][2] == "down"
    assert values[2] == "211.63" and keys[2] == "street target"
    assert "14 buy, 2 hold" in cells[2][3] and "sell" not in cells[2][3]  # a zero is left out
    assert values[3] == mult["text"] and keys[3] == f"{mult['label']} · median {mult['median_text']}"
    # Every empty cell is a dot with its reason on hover, never a zero or words.
    empty = view["_ki_figures"]({}, {"source": None}, None, None, None, None)
    assert [c[0] for c in empty] == ["·"] * 4
    assert all(c[3] for c in empty)
    # The key says why, so a dot never stands alone.
    assert [c[1] for c in empty] == ["close · no price on file", "1 year · under a year of prices",
                                     "street · no consensus on file", "multiple · none on file"]
    # A street lead puts the year's range in the street's place, so it is not said twice.
    led = view["_ki_figures"](series, {"source": "street"}, mom, AZN_STREET, mult, None)
    assert led[2][1] == "52 weeks" and " to " in led[2][0]


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


def _verdict():
    return {"sotp": AZN_SOTP | {"future": {"per_share": 88.76, "rate_used": 0.364,
                                           "first_launch_year": 2026}},
            "modelled": [
                {"name": "Tagrisso", "per_share": 10.29, "counted": True, "is_marketed": True,
                 "loe_year": 2032, "loe_in_base": False},
                {"name": "Symbicort", "per_share": 7.04, "counted": True, "is_marketed": True,
                 "loe_year": None, "loe_in_base": True},
                {"name": "Baxdrostat", "per_share": 9.0, "counted": True, "is_marketed": False,
                 "pos": 0.88},
                {"name": "Not counted", "per_share": 50.0, "counted": False},
                {"name": "Small", "per_share": 1.0, "counted": True, "is_marketed": True}],
            "streams": []}


def test_what_it_rests_on_ranks_the_largest_parts_and_puts_the_rest_in_one_row(view):
    r = view["_ki_rests_on"](_verdict(), shown=3)
    assert [x["name"] for x in r["rows"]] == ["Launches past the pipeline", "Tagrisso",
                                              "Baxdrostat"]
    assert [x["meta"] for x in r["rows"]] == ["from R&D", "LOE 2032", "PoS 88%"]
    assert r["more_n"] == 2                                  # Symbicort and Small
    total = 89.61 + 12.32 + 88.76
    assert r["more_value"] == pytest.approx(total - (88.76 + 10.29 + 9.0))
    lapsed = view["_ki_rests_on"](_verdict(), shown=5)["rows"]
    assert next(x for x in lapsed if x["name"] == "Symbicort")["meta"] == "lapsed"
    assert "Not counted" not in _text(view["_ki_rests_html"](r))
    assert _text(view["_ki_rests_html"]({"rows": []})) == "No modelled asset is counted yet."


def test_the_breaks_are_the_two_nearest_levers_that_reach_the_price(view):
    bp = {"ok": True, "direction": "down", "equity_per_share": 181.83, "close": 157.70,
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
    b = view["_ki_breaks"](bp)
    assert b["head"] == "Today's 181.83 meets the 157.70 price at"
    assert [(r["glyph"], r["name"], r["model"], r["brk"]) for r in b["rows"]] == [
        ("▲", "every discount rate", "7.47%", "8.35%"),
        ("▼", "launch productivity", "0.364", "0.312")]
    up = view["_ki_breaks"](dict(bp, direction="up"))
    assert up["head"] == "The 157.70 price needs"
    assert view["_ki_breaks"]({"ok": False}) == {} and view["_ki_breaks_html"]({}) == ""
    asset = view["_ki_breaks"](dict(bp, levers=bp["levers"][2:3]))
    assert asset["rows"][0]["name"] == "Tagrisso's discount rate"
    bracket = view["_ki_breaks"](dict(bp, levers=[dict(bp["levers"][2],
                                                       name="Trikafta (Copackaged)")]))
    assert bracket["rows"][0]["name"] == "Trikafta's discount rate"
    assert view["_ki_lever_text"]("rate", -0.9327) == "−93.27%"   # the page's minus


def test_with_nothing_modelled_the_street_expects_its_eps_and_nothing_is_chained(view):
    rec = {"street": {"eps_first": {"FY1": {"value": 9.16}, "FY2": {"value": 10.44}}},
           "periods": {"FY1": {"label": "FY2026"}, "FY2": {"label": "FY2027"}}}
    assert view["_ki_street_expects"](rec) == [("9.16", "FY2026 EPS, street"),
                                               ("10.44", "FY2027 EPS, street")]
    assert view["_ki_street_expects"]({}) == []


# --- the track --------------------------------------------------------------------------------
@pytest.mark.parametrize("ticker", ["AZN", "LLY"])
def test_the_tracks_drivers_are_the_head_of_the_catalysts_list(view, board, ticker):
    events = drivers.rank_events(_ctx(ticker))
    today = dt.date.fromisoformat(board["today"])
    items, _undated = view["_ki_track_items"](events, [], today)
    labelled = [it["label"] for it in items if it["kind"] != "minor"]
    dated = [e["asset"] for e in events
             if re.match(r"^\d{4}(-\d{2}){0,2}$", str(e.get("date") or ""))]
    assert labelled == dated[:4]
    # A month is a date: LLY's Retatrutide readout ("2026-11") is placed and leads.
    if ticker == "LLY":
        assert labelled[0] == "Retatrutide"
        lead = next(it for it in items if it["label"] == "Retatrutide")
        assert lead["kind"] == "value" and lead["sub"].startswith("$")
    for it in items:
        if it["kind"] == "minor":
            assert it["tip"] and not it.get("label")


def test_the_track_draws_nothing_past_and_reads_a_month_slip(view):
    risks = [{"kind": "slip", "new": "2024-11-07", "nct_id": "NCT04908189", "days": 275},
             {"kind": "slip", "new": "2028-06", "nct_id": "NCT1", "days": 400},
             {"kind": "exclusivity", "date": "2025-01-01", "asset": "Old"}]
    items, _ = view["_ki_track_items"]([{"asset": "Past", "date": "2026-01-01",
                                         "event": "x"}], risks, dt.date(2026, 10, 2))
    assert [(it["label"], it["date"], it.get("precision")) for it in items] == [
        ("NCT1", "2028-06-01", "month")]


def test_the_tracks_risks_are_the_dated_rows_of_the_risk_list(view):
    risks = [{"kind": "exclusivity", "date": "2027-09-08", "asset": "Lynparza",
              "share_text": "5.6%", "line": "5.6% of revenue  Lynparza exclusivity ends"},
             {"kind": "slip", "new": "2028-01-10", "nct_id": "NCT06455449", "days": 241,
              "line": "241 days  NCT06455449 readout slips to Jan 2028"},
             {"kind": "pool", "lead": "73% kept", "text": "Obesity: 2 candidates",
              "line": "73% kept  Obesity: 2 candidates"}]
    items, undated = view["_ki_track_items"]([], risks, dt.date(2026, 10, 2))
    assert [(it["kind"], it["label"], it["sub"]) for it in items] == [
        ("loss", "Lynparza LOE", "5.6% of revenue"),
        ("slip", "NCT06455449", "slips 241 days")]
    assert [u["kind"] for u in undated] == ["pool"]


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


def test_the_columns_are_financials_pipeline_and_marketed_products(view, board):
    ver = {"reported_revenue": [{"fiscal_year": 2023, "value": 45811.0},
                                {"fiscal_year": 2024, "value": 54073.0},
                                {"fiscal_year": 2025, "value": 58739.0}],
           "sotp": {"pipeline": {"n": 22, "per_share": 12.32, "per_share_unrisked": 23.73}}}
    cols = view["_ki_columns"](board, "AZN", _record(), ver)
    assert [c["title"] for c in cols] == ["Financials", "Pipeline", "Marketed products"]
    fin, pipe, mkt = cols
    azn = board["companies"]["AZN"]
    growth = view["_ki_metric"](azn, ("rev_growth",))
    assert (fin["figure"], fin["unit"]) == ("58.7", "bn USD revenue, FY2025")
    assert fin["delta"] == "+8.6%" and fin["place"] == f"{growth['place']} of {growth['n']}"
    # The measures print the scorecard's own value and place, so the tabs never disagree.
    for col in cols:
        for row in col["rows"]:
            m = view["_ki_metric"](azn, (row["id"],))
            assert row["text"] == m["text"]
            assert row["place_text"] == f"{m['place']} of {m['n']}"
            cohort = [t for t, c in board["companies"].items() if c["cohort"] == "big_pharma"]
            assert {p["ticker"] for p in row["peers"]} <= set(cohort)
            assert row["median"] == board["cohorts"]["big_pharma"]["metric_medians"].get(row["id"])
    assert [r["id"] for r in fin["rows"]] == ["op_margin", "nd_ocf"]
    assert pipe["figure"] == "92" and pipe["notes"] == ["12.32 a share after PoS (23.73 before)"]
    assert [d["label"] for d in pipe["picture"]["data"]] == ["P1 27", "P1/2 28", "P2 12",
                                                             "P3 23", "P4 2"]
    assert mkt["unit"] == "years of exclusivity left"
    mix = mkt["picture"]["data"]
    assert [d["label"] for d in mix] == ["Farxiga", "Tagrisso", "rest"]
    assert mix[0]["sub"] == "14%" and mix[-1]["value"] == pytest.approx(58739 - 8400 - 7254)


def test_a_commercial_company_reads_its_unscored_exclusivity_and_says_why_when_none(view):
    board = {"method": {"metrics": {}, "reasons": {"no_product_revenue": "No product revenue"}},
             "cohorts": {"commercial": {}},
             "companies": {
                 "INCY": {"cohort": "commercial", "pillars": {}, "facts": {"other_metrics": [
                     {"id": "loe_years", "value": 2.6482, "text": "2.6 years"},
                     {"id": "top_product", "value": 0.6015, "text": "60%"}]}},
                 "ALNY": {"cohort": "commercial", "pillars": {}, "facts": {"other_metrics": [
                     {"id": "loe_years", "value": None, "reason": "no_product_revenue"}]}}}}
    mkt = view["_ki_columns"](board, "INCY", {}, {})[2]
    assert (mkt["figure"], mkt["unit"]) == ("2.6", "years of exclusivity left")
    assert [r["id"] for r in mkt["rows"]] == ["top_product"]
    none = view["_ki_columns"](board, "ALNY", {}, {})[2]
    assert none["figure"] == "·" and none["reason"] == "No product revenue"
    markup = view["_ki_column_html"](none, "", [])
    assert "No product revenue" in _text(markup)


def test_revenue_is_labelled_in_the_currency_its_rows_are_filed_in(view, board):
    ver = {"reported_revenue": [{"fiscal_year": 2024, "value": 2751.1},
                                {"fiscal_year": 2025, "value": 2869.9}]}
    fin = view["_ki_columns"](board, "AZN", {"reporting_currency": "USD",
                                             "row_currency": "EUR"}, ver)[0]
    assert fin["unit"] == "bn EUR revenue, FY2025"


def test_a_failed_forecast_read_is_not_called_nothing_modelled(view):
    assert view["_ki_forecast_state"](None, "timed out") == "failed"
    assert view["_ki_forecast_state"]({"ok": True, "per_share": 0.0, "sotp": {
        "marketed": {"per_share": 0.0}}}) == "not_modelled"
    assert view["_ki_forecast_state"]({"ok": True, "per_share": 5.0, "sotp": {
        "marketed": {"per_share": 4.0}}}) == "modelled"


def test_one_product_filed_twice_is_one_row_and_shares_use_one_base(view):
    products = {"fiscal_year": 2025, "rows": [
        {"name": "PYLARIFY", "value_usd_m": 990.0}, {"name": "Definity", "value_usd_m": 330.2},
        {"name": "Definity", "value_usd_m": 330.2}, {"name": "Techne Lite", "value_usd_m": 92.0}]}
    mix = view["_ki_mix_segments"](products, {"label": "FY2025", "revenue_usd_m": 1541.6})
    assert [d["label"] for d in mix] == ["PYLARIFY", "Definity", "Techne Lite", "rest"]
    total = sum(d["value"] for d in mix)
    assert total == pytest.approx(1541.6)


def test_a_reason_is_filled_never_a_template(view):
    reasons = {"partial_product_revenue": "Product revenue on file covers {c}% of revenue"}
    filled = {"reason": "partial_product_revenue",
              "reason_text": "Product revenue on file covers 17% of revenue"}
    assert view["_ki_reason"](filled, reasons) == "Product revenue on file covers 17% of revenue"
    assert "{" not in view["_ki_reason"]({"reason": "partial_product_revenue"}, reasons)


def test_counts_are_plural_only_above_one(view, board):
    cols = view["_ki_columns"](board, "AZN", {"detail": {"pipeline": {"compounds": {
        "Phase 1": 1}}}}, {})
    assert cols[1]["unit"] == "compound in trials"
    assert view["_ki_plural"](1, "product") == "1 product"


def test_a_clinical_company_reads_funding_pipeline_and_its_lead_asset(view, board):
    cols = view["_ki_columns"](board, "CRSP", {"detail": {"pipeline": {"compounds": {
        "Phase 1": 1, "Phase 1/2": 3}}}}, {})
    assert [c["title"] for c in cols] == ["Funding", "Pipeline", "Lead asset"]
    crsp = board["companies"]["CRSP"]
    assert cols[0]["figure"] == view["_ki_metric"](crsp, ("runway",))["text"]
    assert cols[2]["figure"] == crsp["facts"]["lead_phase"]["phase"]


def test_a_measure_with_no_value_prints_a_dot_and_its_reason(view, board):
    adapy = board["companies"]["ADAPY"]
    m = view["_ki_metric"](adapy, ("op_margin",))
    row = view["_ki_peer_row"](board, "ADAPY", m)
    assert row["value"] is None and row["reason"]
    markup = view["_ki_column_html"]({"title": "Financials", "figure": "·", "rows": [row]},
                                     "", [""])
    assert 'class="v none"' in markup and html.escape(row["reason"], quote=True) in markup


def test_revenue_bars_keep_a_missing_year_as_a_gap(view):
    bars = view["_ki_rev_bars"]([{"fiscal_year": 2021, "value": 1.0},
                                 {"fiscal_year": 2023, "value": 3.0},
                                 {"fiscal_year": 2025, "value": 5.0}])
    assert [(b["label"], b["value"], b["latest"]) for b in bars] == [
        ("FY21", 1.0, False), ("FY22", None, False), ("FY23", 3.0, False),
        ("FY24", None, False), ("FY25", 5.0, True)]


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
    assert [r["change_type"] for r in rows] == ["press_deal", "date_slip", "material event"]
    assert view["_ki_changes_basis"](len(rows)) == "3 of 3 in 30 days"
    # Three shown; News has the rest.
    assert view["_KI_CHANGES_SHOWN"] == 3
    assert view["_ki_changes_basis"](10) == "3 of 10 in 30 days"


def test_what_changed_does_not_repeat_a_slip_the_track_draws(view):
    rows = view["_ki_changes"](_feed(), "AZN", dt.date(2026, 10, 1), skip_ncts=("NCT06455449",))
    assert [r["change_type"] for r in rows] == ["press_deal", "material event"]


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


def test_the_note_label_names_the_layer_and_the_day(view):
    label = view["_ki_note_label"]({"body": "x", "model": "gemini-flash-latest",
                                    "generated_at": "2026-09-22 19:50:51"})
    assert label == "Morning note · gemini-flash-latest · 22 Sep 2026"
    assert view["_ki_note_label"]({"body": "x", "model": "rules",
                                   "generated_at": "2026-09-25"}) == (
        "Morning note · rules layer · 25 Sep 2026")
    assert view["_ki_note_label"]({}) == "Morning note · none yet"


# --- house style ----------------------------------------------------------------------------
def test_every_string_the_tab_adds_is_in_house_style(view, board):
    fixed = [v for k, v in view.items() if k.startswith("_KI_") and isinstance(v, str)]
    fixed += list(view["_KI_SHORT"].values())
    made = []
    series = view["_ki_year_series"](_points(400))
    for ticker, company in board["companies"].items():
        call = view["_ki_call"](AZN_RATED if ticker == "AZN" else {}, "no sum of the parts",
                                series, AZN_STREET if ticker == "AZN" else None)
        mom = view["_ki_metric"](company, ("rel_1y",))
        mult = (company.get("facts") or {}).get("multiple")
        made.append(_text(view["_ki_call_html"](call, view["_ki_figures"](
            series, call, mom, AZN_STREET, mult, None))))
        for col in view["_ki_columns"](board, ticker, _record(), {}):
            made.append(_text(view["_ki_column_html"](col, "", ["" for _ in col["rows"]])))
    made += [_text(view["_ki_rests_html"](view["_ki_rests_on"](_verdict()))),
             view["_ki_changes_basis"](10), view["_ki_note_label"]({})]
    for text in fixed + made:
        assert EM_DASH not in text, text
        low = text.lower()
        assert not [w for w in BANNED if re.search(rf"\b{w}\b", low)], text
    # Sentence case: the fixed sentences open on a capital and carry no other title case,
    # bar the names of the tabs they point to.
    tabs = {"Forecast", "Catalysts", "News", "Comps"}
    for name in ("_KI_FAILED", "_KI_NO_CHANGES", "_KI_NO_BRIDGE", "_KI_NO_ASSET"):
        words = view[name].split()
        assert words[0][0].isupper() and not any(
            w[0].isupper() for w in words[1:] if w.isalpha() and w.strip(".,;") not in tabs
            and w not in tabs), view[name]


# --- the four pictures ---------------------------------------------------------------------
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


def test_event_track_places_every_item_and_keeps_labels_apart(view):
    items = [{"date": "2026-11-01", "precision": "month", "side": "above", "kind": "readout",
              "estimated": True, "label": "Truqap", "sub": "Phase 3", "tip": "t1"},
             {"date": "2026-11-15", "side": "above", "kind": "readout", "label": "Enhertu",
              "sub": "Phase 3", "tip": "t2"},
             {"date": "2026-11-20", "side": "above", "kind": "regulatory", "label": "Saphnelo",
              "tip": "t3"},
             {"date": "2026-12-01", "side": "above", "kind": "value", "weight": 1.0,
              "label": "Fasenra", "sub": "$4.00", "tip": "t4"},
             {"date": "2027-01-10", "kind": "minor", "tip": "dot"},
             {"date": "2027-09-08", "side": "below", "kind": "loss", "label": "Lynparza LOE",
              "sub": "5.6% of revenue", "tip": "loss"},
             {"date": "2029-03-01", "side": "above", "kind": "readout", "label": "Late"}]
    svg = charts.event_track(items, "2026-10-02")
    ET.fromstring(svg)
    for name in ("Truqap", "Enhertu", "Saphnelo", "Fasenra", "Lynparza LOE"):
        assert f">{name}<" in svg
    assert "Late → Mar 29" in svg                            # pinned to the right end
    assert "<title>dot</title>" in svg and ">today<" in svg and ">12 months<" in svg
    # Nothing before today, and no tick label under the 12-month rule.
    assert ">Oct 27<" not in svg
    # No two labels on one tier overlap: each starts after the last one on its row ends.
    rows = {}
    for x, y, anchor, text in re.findall(
            r'<text x="([\d.]+)" y="([\d.]+)" font-size="10"[^>]*text-anchor="(\w+)"'
            r'[^>]*>([^<]*)</text>', svg):
        start = float(x) - (len(text) * 5.6 if anchor == "end" else 0)
        rows.setdefault(y, []).append((start, start + len(text) * 5.6))
    for spans in rows.values():
        spans.sort()
        assert all(b[0] >= a[1] - 1 for a, b in zip(spans, spans[1:])), spans
    assert charts.event_track([], "2026-10-02") == ""


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


def test_share_bar_labels_only_what_fits_and_skips_a_zero(view):
    svg = charts.share_bar([{"value": 80, "colour": tokens.UP, "label": "Farxiga", "sub": "80%"},
                            {"value": 2, "colour": tokens.MUTED, "label": "Tiny", "sub": "2%"},
                            {"value": 0, "colour": tokens.MUTED, "label": "Zero"}], 440, 34)
    ET.fromstring(svg)
    assert ">Farxiga<" in svg and ">80%<" in svg
    assert ">Tiny<" not in svg                               # too narrow to hold a label
    assert svg.count("<rect") == 2                           # the zero draws nothing
    assert ">Zero<" not in svg
    assert charts.share_bar([{"value": 0}]) == ""


def test_the_new_pictures_take_their_colours_from_the_tokens(view):
    tok = {v.upper() for k, v in vars(tokens).items()
           if k.isupper() and isinstance(v, str) and v.startswith("#")}
    for name, vals in tokens.PHASE_RAMP.items():
        tok.add(vals.upper())
    svgs = [charts.price_call([1.0, 2.0], ["2026-01-01", "2026-10-01"], 2.0,
                              model={"mid": 3.0, "low": 2.5, "high": 3.5, "tone": "up"},
                              street={"value": 2.8}),
            charts.event_track([{"date": "2027-01-01", "kind": "value", "label": "A",
                                 "weight": 1}], "2026-10-02"),
            charts.peer_dots([{"value": 1}], {"value": 2}, tone="down"),
            charts.share_bar([{"value": 1, "colour": tokens.UP}])]
    blended = {charts._blend(tokens.UP, tokens.GROUND, 0.45).upper()}
    for svg in svgs:
        assert _colours(svg) <= tok | blended, _colours(svg) - tok - blended


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


live = pytest.mark.skipif(not _api_up(), reason="API not running on 8000")


@pytest.fixture(scope="module", params=["AZN", "LLY", "CRSP"])
def tab(request):
    from streamlit.testing.v1 import AppTest

    _patch_button_group_serialisation()
    ticker = request.param
    test = AppTest.from_file(str(APP), default_timeout=180)
    test.query_params["ticker"] = ticker
    test.run()
    assert not test.exception, [str(e.value)[:400] for e in test.exception]
    payload = _get("/comps/valuation")
    context = _get(f"/companies/{urllib.parse.quote(ticker)}/comps-context")
    return {"ticker": ticker, "app": test, "tab": _tab(test, "Key insights"),
            "company": payload["scorecard"]["companies"][ticker], "context": context}


@live
def test_the_live_call_reads_the_models_value_or_says_why_not(tab):
    body = "\n".join(_markdown(tab["tab"]))
    assert 'class="pos ki-call"' in body
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
    v = _get(f"/companies/{tab['ticker']}/forecast-verdict")
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
def test_the_live_track_leads_with_the_catalysts_lists_head(tab):
    body = "\n".join(_markdown(tab["tab"]))
    rows = [r for r in drivers.rank_events(tab["context"])
            if re.match(r"^\d{4}(-\d{2}){0,2}$", str(r.get("date") or ""))][:4]
    if not rows:
        return
    for r in rows:
        assert f">{html.escape(r['asset'], quote=False)}<" in body, r["asset"]


@live
def test_the_live_cohort_band_prints_the_scorecards_rank(tab):
    body = "\n".join(_markdown(tab["tab"]))
    company = tab["company"]
    if company.get("rank") is not None:
        assert f"of {company['ranked_of']} · score {company['score']}" in body


@live
def test_the_live_what_changed_leaves_restatements_and_rates_to_news(tab):
    ticker = tab["ticker"]
    block = next((m for m in _markdown(tab["tab"]) if "ki-changes" in m), "")
    assert "restated" not in block and "Treasury" not in block
    assert not re.search(rf'<span class="t">{ticker} ', block)
    assert block.count('class="fitem') <= 3


@live
def test_the_live_tab_drops_the_old_blocks_and_folds_the_note(tab):
    md = _markdown(tab["tab"])
    labels = [html.unescape(x) for m in md
              for x in re.findall(r'<span class="sec-label">([^<]*)</span>', m)]
    for gone in ("Company score", "Positives and negatives", "Next"):
        assert gone not in labels
    assert "Drivers, risks and catalysts" in labels
    body = "\n".join(md)
    assert "ki-strip" not in body and "ki-sentence" not in body
    notes = [e for e in _walk(tab["tab"]) if getattr(e, "type", "") == "expander"
             and e.label.startswith("Morning note")]
    assert len(notes) == 1 and not notes[0].proto.expanded
