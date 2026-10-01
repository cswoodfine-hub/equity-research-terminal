"""Key insights, the company on one page (company-scorecard.md 1.3, 5.3 and 7.2, E3).

Two layers. The tab's string builders live in the Streamlit script, which runs the whole
app on import, so they are read out of its source by name and run on the sample scorecard
(``fixtures/company_score/sample_scorecard.json``) and the saved comps-context answers of
``fixtures/drivers``; none of them touches Streamlit. ``charts.pillar_bars`` is tested as
the chart primitive it is. Then the tab itself, driven in-process through AppTest against
the API, which is skipped when the API is not up, like the other tab tests.
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
KEYS = ["last close", "model", "multiple", "next exclusivity loss"]
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


def _cells(markup: str) -> list:
    """(key, value, sub) per strip cell, with where each span sits in the markup."""
    out = []
    for m in re.finditer(r'<span class="ki-cell"[^>]*>(.*?)</span></span>', markup):
        cell = m.group(1) + "</span>"
        k = re.search(r'<span class="k">(.*?)</span>', cell)
        v = re.search(r'<span class="v[^"]*">(.*?)</span>', cell)
        s = re.search(r'<span class="sub">(.*?)</span>', cell)
        out.append({"key": html.unescape(k.group(1)), "value": html.unescape(v.group(1)),
                    "sub": html.unescape(s.group(1)), "v_at": v.start(), "s_at": s.start()})
    return out


AZN_RATING = {"ok": True, "rating": "Buy", "upside_12m": 0.1322194148932445,
              "forward_12m": 182.81947030491597}


# --- the strip ---------------------------------------------------------------------------
def test_the_strip_has_four_cells_in_order_each_value_before_its_sub(view, board):
    azn = board["companies"]["AZN"]
    cells = view["_ki_strip_cells"]("161.47", -0.01668598368635643, AZN_RATING, azn)
    markup = view["_ki_strip_html"](cells)
    got = _cells(markup)
    assert [c["key"] for c in got] == KEYS
    assert all(c["v_at"] < c["s_at"] for c in got)
    assert 'class="pos ki-strip"' in markup
    assert [(c["value"], c["sub"]) for c in got] == [
        ("161.47", "−1.7% on the day"),
        ("+13.2%", "Buy, 182.82 in 12 months"),
        ("4.7×", "EV to sales, median 4.8×"),
        ("Sep 2027", "5.6% of FY2025 revenue, Lynparza")]


@pytest.mark.parametrize("ticker", ["AZN", "LLY", "CRSP", "VRTX", "PFE"])
def test_the_multiple_cell_is_the_scorecards_multiple(view, board, ticker):
    company = board["companies"][ticker]
    m = company["facts"]["multiple"]
    got = _cells(view["_ki_strip_html"](view["_ki_strip_cells"]("1.00", 0.0, {}, company)))
    assert got[2]["value"] == m["text"]
    assert got[2]["sub"] == f"{m['label']}, median {m['median_text']}"


def test_lly_reads_its_pe_and_crsp_its_cash_multiple(view, board):
    lly = _cells(view["_ki_strip_html"](view["_ki_strip_cells"](
        "1.00", 0.0, {}, board["companies"]["LLY"])))
    assert (lly[2]["value"], lly[2]["sub"]) == ("26.2×", "P/E NTM, median 15.1×")
    crsp = _cells(view["_ki_strip_html"](view["_ki_strip_cells"](
        "1.00", 0.0, {}, board["companies"]["CRSP"])))
    assert (crsp[2]["value"], crsp[2]["sub"]) == ("2.3×", "Market cap to cash, median 2.1×")


def test_the_exclusivity_cell_is_the_first_loss_or_says_there_is_none(view, board):
    for ticker, company in board["companies"].items():
        cells = view["_ki_strip_cells"]("1.00", 0.0, {}, company)
        key, value, sub, _cls, tip = cells[3]
        assert key == "next exclusivity loss"
        losses = company["exclusivity_losses"]
        if not losses:
            assert (value, sub) == ("·", "none in 24 months"), ticker
            continue
        first = losses[0]
        assert value == view["_ki_month"](first["date"]), ticker
        assert sub.startswith(f"{first['share_text']} of {first['fy']} revenue, "), ticker
        assert sub.endswith(view["_ki_product"](first["asset"])), ticker
        assert first["date_text"] in tip
    lly = view["_ki_strip_cells"]("1.00", 0.0, {}, board["companies"]["LLY"])[3]
    assert lly[1:3] == ("Dec 2027", "6.6% of FY2025 revenue, Trulicity")


def test_empty_cells_open_on_a_dot_never_on_words(view, board):
    adapy = board["companies"]["ADAPY"]
    cells = view["_ki_strip_cells"](None, None, {"ok": None}, adapy)
    assert [(c[1], c[2]) for c in cells] == [
        ("·", "no price on file"), ("·", "not modelled"), ("·", "no multiple on file"),
        ("·", "none in 24 months")]
    failed = view["_ki_strip_cells"]("161.47", -0.0167, AZN_RATING, None, problem="boom")
    assert failed[0][1] == "161.47" and failed[1][1] == "+13.2%"
    assert [c[1] for c in failed[2:]] == ["·", "·"]


def test_the_model_cell_signs_the_upside_and_names_the_rating(view):
    cells = view["_ki_strip_cells"]("1.00", None, {"ok": True, "rating": "Sell",
                                                   "upside_12m": -0.5569,
                                                   "forward_12m": 512.68}, None)
    assert cells[0][2] == ""                              # no day move, no sub
    assert cells[1][1:4] == ("−55.7%", "Sell, 512.68 in 12 months", "down")
    assert view["_ki_signed_pct"](0.00001) == "0.0%"


# --- the bars ------------------------------------------------------------------------------
def test_the_pillar_rows_put_the_business_first_then_the_price(view, board):
    method = board["method"]
    azn = board["companies"]["AZN"]
    rows = view["_ki_pillar_rows"](azn, board["cohorts"]["big_pharma"], method)
    labels = [r.get("label") or r.get("separator") for r in rows]
    assert labels == ["Growth", "Profitability", "Balance sheet", "Pipeline", "Durability",
                      "Price, not in the score", "Value", "Momentum"]
    by = {r["id"]: r for r in rows if "id" in r}
    assert [by[p]["score"] for p in ("growth", "profitability", "balance_sheet", "pipeline",
                                      "durability", "value", "momentum")] == [
        77, 31, 55, 65, 62, 46, 9]
    assert by["durability"]["note"] == "4.6 years of exclusivity left"
    assert by["growth"]["median"] == azn["pillars"]["growth"]["median"]
    crsp = view["_ki_pillar_rows"](board["companies"]["CRSP"], board["cohorts"]["clinical"],
                                   method)
    assert [r.get("label") or r.get("separator") for r in crsp] == [
        "Pipeline", "Funding", "Price, not in the score", "Value", "Momentum"]


def test_a_pillar_with_no_score_carries_its_reason_not_a_zero(view, board):
    adapy = board["companies"]["ADAPY"]
    rows = view["_ki_pillar_rows"](adapy, board["cohorts"]["commercial"], board["method"])
    growth = next(r for r in rows if r.get("id") == "growth")
    assert growth["score"] is None
    assert growth["reason"] == "The latest filed year is more than 15 months old"
    svg = charts.pillar_bars(rows)
    assert "The latest filed year is more than 15" in svg


# --- positives and negatives ----------------------------------------------------------------
@pytest.mark.parametrize("ticker", ["AZN", "LLY", "CRSP", "VRTX", "PFE"])
def test_the_lines_are_the_first_positives_then_negatives(view, board, ticker):
    company = board["companies"][ticker]
    markup = view["_ki_lines_html"](company)
    pos, neg = view["_ki_lines_pick"](company)
    want = [("+", p["text"]) for p in pos] + [("−", n["text"]) for n in neg]
    got = [(html.unescape(g), html.unescape(t)) for g, t in re.findall(
        r'<span class="ki-g [a-z]+">([^<]*)</span><span class="ki-t">([^<]*)</span>', markup)]
    assert got == want
    # Each side is the head of the scorecard's own list, three at most.
    assert pos == company["positives"][:len(pos)] and len(pos) <= 3
    assert neg == company["negatives"][:len(neg)] and len(neg) <= 3
    for line in pos + neg:
        assert f'title="{html.escape(line["source"], quote=True)}"' in markup


def _words(text):
    return len([w for w in str(text or "").split() if re.search(r"[A-Za-z0-9]", w)])


def test_the_sentence_and_lines_keep_to_75_words(view, board):
    """8.7: past the budget the longer side gives up its last line, never below two
    lines. On the sample, LLY ran to 79 words and PFE to 80 with three of each."""
    trimmed = 0
    for t, company in board["companies"].items():
        pos, neg = view["_ki_lines_pick"](company)
        full = (company.get("positives") or [])[:3] + (company.get("negatives") or [])[:3]
        used = _words(company.get("sentence")) + sum(_words(x["text"]) for x in pos + neg)
        assert used <= 75 or len(pos) + len(neg) <= 2, (t, used)
        if len(pos) + len(neg) < len(full):
            trimmed += 1
            # Nothing was dropped that fitted: one more line puts it over.
            assert used > 75 - max(_words(x["text"]) for x in full), t
    assert trimmed >= 2
    # LLY: 19 + 36 + 24 = 79 with three positives and two negatives; the positives are the
    # longer side and give up their third. PFE: two and three, so a negative goes.
    lly, pfe = board["companies"]["LLY"], board["companies"]["PFE"]
    assert view["_ki_lines_pick"](lly) == (lly["positives"][:2], lly["negatives"][:2])
    assert view["_ki_lines_pick"](pfe) == (pfe["positives"][:2], pfe["negatives"][:2])
    assert view["_ki_lines_pick"](board["companies"]["AZN"]) == (
        board["companies"]["AZN"]["positives"][:3], board["companies"]["AZN"]["negatives"][:3])


def test_a_company_with_no_line_says_so_in_one_muted_line(view, board):
    markup = view["_ki_lines_html"](board["companies"]["IONS"])
    assert 'class="ki-empty"' in markup
    assert _text(markup) == "No business measure in the top or bottom quarter of the cohort."


# --- Next ---------------------------------------------------------------------------------
@pytest.mark.parametrize("ticker", ["AZN", "LLY"])
def test_next_is_the_head_of_the_catalysts_list(view, ticker):
    rows = drivers.rank_events(_ctx(ticker))
    markup = view["_ki_next_html"](rows[:3])
    leads = [html.unescape(x) for x in re.findall(r'<span class="ki-lead[^"]*">([^<]*)</span>',
                                                   markup)]
    texts = [html.unescape(x) for x in re.findall(r'<span class="ki-t">([^<]*)</span>', markup)]
    assert leads == [r["lead"] for r in rows[:3]]
    assert texts == [r["text"] for r in rows[:3]]
    basis = view["_ki_next_basis"](len(rows), drivers.drivers_basis(len(rows)))
    assert basis == f"3 of {len(rows)} assets in 12 months, Catalysts has them all"


def test_next_for_azn_and_lly_lead_as_the_spec_draws_them(view):
    azn = drivers.rank_events(_ctx("AZN"))[:3]
    assert azn[0]["line"] == "$4.68  Elecoglipron · Phase 3 readout · obesity · est. Jun 2027"
    assert azn[1]["lead"] == "est. Oct 2026" and azn[1]["asset"] == "Truqap"
    lly = drivers.rank_events(_ctx("LLY"))[:3]
    assert lly[0]["line"].startswith("$33.51  Retatrutide")
    markup = view["_ki_next_html"](azn)
    assert 'class="ki-lead ki-val"' in markup and "Model output" in markup


def test_next_with_no_event_is_one_muted_line(view):
    assert drivers.rank_events(_ctx("CRSP")) == []
    assert _text(view["_ki_next_html"]([])) == "No event dated in the next 12 months."


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
    assert view["_ki_changes_basis"](len(rows)) == "3 of 3 high in 30 days, News has them all"
    # Three shown, like Next (8.7's budget at 1440 x 810); News has the rest.
    assert view["_KI_CHANGES_SHOWN"] == 3
    assert view["_ki_changes_basis"](10) == "3 of 10 high in 30 days, News has them all"


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
    made = []
    for ticker, company in board["companies"].items():
        cells = view["_ki_strip_cells"]("1.00", -0.01, AZN_RATING, company)
        made += [_text(view["_ki_strip_html"](cells)), _text(view["_ki_lines_html"](company))]
        made += [r.get("separator") or r.get("reason") or r.get("note") or ""
                 for r in view["_ki_pillar_rows"](company, board["cohorts"][company["cohort"]],
                                                  board["method"])]
    made += [view["_ki_next_basis"](25, drivers.drivers_basis(25)),
             view["_ki_changes_basis"](10), view["_ki_note_label"]({})]
    for text in fixed + made:
        assert EM_DASH not in text, text
        low = text.lower()
        assert not [w for w in BANNED if w in low], text
    # Sentence case: the fixed sentences open on a capital and carry no other title case.
    for text in ("_KI_FAILED", "_KI_NO_LINES", "_KI_NO_NEXT", "_KI_NO_CHANGES",
                 "_KI_SEPARATOR"):
        words = view[text].split()
        assert words[0][0].isupper() and not any(w[0].isupper() for w in words[1:]
                                                 if w.isalpha()), view[text]


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
def test_the_live_strip_reads_the_scorecard(tab):
    md = _markdown(tab["tab"])
    strip = next(m for m in md if "ki-strip" in m)
    cells = _cells(strip)
    assert [c["key"] for c in cells] == KEYS
    assert all(c["v_at"] < c["s_at"] for c in cells)
    company = tab["company"]
    m = company["facts"]["multiple"]
    if m:
        assert cells[2]["value"] == m["text"]
        assert cells[2]["sub"] == f"{m['label']}, median {m['median_text']}"
    losses = company["exclusivity_losses"]
    if losses:
        assert cells[3]["sub"].startswith(f"{losses[0]['share_text']} of")
        assert cells[3]["value"] == dt.date.fromisoformat(losses[0]["date"]).strftime("%b %Y")
    else:
        assert (cells[3]["value"], cells[3]["sub"]) == ("·", "none in 24 months")


@live
def test_the_live_sentence_and_lines_are_the_scorecards(tab, view):
    body = "\n".join(_markdown(tab["tab"]))
    company = tab["company"]
    assert html.escape(company["sentence"], quote=False) in body
    # The lines are the heads of the scorecard's lists, trimmed to 8.7's 75 words with the
    # sentence (``_ki_lines_pick``); LLY gives up its third positive on the live book.
    pos, neg = view["_ki_lines_pick"](company)
    for line in pos + neg:
        assert html.escape(line["text"], quote=False) in body
    for line in company["positives"][len(pos):] + company["negatives"][len(neg):]:
        assert f'<span class="ki-t">{html.escape(line["text"], quote=False)}<' not in body
    assert "ki-bars" in body and 'class="pb-row"' in body


@live
def test_the_live_next_is_the_head_of_the_catalysts_list(tab):
    body = "\n".join(_markdown(tab["tab"]))
    rows = drivers.rank_events(tab["context"])[:3]
    if not rows:
        assert "No event dated in the next 12 months." in body
    shown = [html.unescape(x) for x in re.findall(r'<span class="ki-t">([^<]*)</span>', body)
             if html.unescape(x) in {r["text"] for r in rows}]
    assert shown == [r["text"] for r in rows]


@live
def test_the_live_what_changed_leaves_restatements_and_rates_to_news(tab):
    ticker = tab["ticker"]
    block = next((m for m in _markdown(tab["tab"]) if "ki-changes" in m), "")
    assert "restated" not in block and "Treasury" not in block
    assert not re.search(rf'<span class="t">{ticker} ', block)
    assert block.count('class="fitem') <= 3


@live
def test_the_live_tab_drops_the_removed_blocks_and_folds_the_note(tab):
    md = _markdown(tab["tab"])
    labels = [html.unescape(x) for m in md
              for x in re.findall(r'<span class="sec-label">([^<]*)</span>', m)]
    assert labels[:2] == ["Company score", "Positives and negatives"] or not tab["company"]
    for gone in ("What happened", "Dated ahead", "Morning note", "Nothing flagged"):
        assert gone not in labels
    body = "\n".join(md)
    # The sentence names the cohort; the bars' section does not say it again.
    assert 'sec-label">Company score</span><span class="sec-basis">' not in body
    assert "chart-mount stretch" not in body                  # the five-session sparkline
    assert "12m value" not in body and "in development" not in body
    notes = [e for e in _walk(tab["tab"]) if getattr(e, "type", "") == "expander"
             and e.label.startswith("Morning note")]
    assert len(notes) == 1 and not notes[0].proto.expanded
    # China-linked business development folds like the note: open, it put about 90 words
    # of verbatim headlines on PFE's first screen (8.7).
    assert "China-linked business development" not in labels
    china = [e for e in _walk(tab["tab"]) if getattr(e, "type", "") == "expander"
             and e.label.startswith("China-linked business development · ")]
    assert all(not e.proto.expanded for e in china)
