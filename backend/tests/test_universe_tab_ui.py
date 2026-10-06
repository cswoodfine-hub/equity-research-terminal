"""The redesigned Universe tab (frontend/universe_cc.py, universe_page.py, the uvboard
component and the switch in streamlit_app.py).

Four layers.

The builders are pure functions of the payload of ``GET /universe/command``, saved from the
2026-10-06 book as ``fixtures/universe/command_AZN.json``. They are run on it and on copies
with figures taken away: every block draws, a missing figure prints "no free data" or is
named as left off, and nothing missing is drawn as a zero.

The house style of every string a reader sees. Registry and release titles are quoted
verbatim in hovers only, so <title> elements and title= attributes are left out of the
check.

The switch: read out of the Streamlit script by name (it runs the whole app on import), so
a company outside ``_REDESIGN_TICKERS`` provably takes today's overview, called as before.

Then the app itself through AppTest against an API, skipped when none is up, like the
other tab tests.
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
BUILDERS = FRONTEND / "universe_cc.py"
UNIVERSE_CSS = FRONTEND / "assets" / "universe.css"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "universe" / "command_AZN.json"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import universe_cc as UC  # noqa: E402

BASE = os.getenv("ER_API_BASE", "http://localhost:8000")
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text())


def _all_blocks(p, w="1y"):
    """Every block the page draws, by name."""
    return {
        "status": UC.status_line(p), "lead": UC.lead_line(p, w),
        "spotlight": UC.spotlight_section(p, w) + UC.spotlight_html(p, w),
        "hero": UC.hero_html(p, w), "band3": UC.band_week_rates_exposure(p),
        "lanes": UC.band_lanes(p), "band7": UC.band_prices_policy(p),
        "notes": UC.notes_text(p), "dialog": UC.dialog_html(p, "the map"),
    }


def _visible(markup: str) -> str:
    """What a reader sees without hovering: hovers (registry titles, verbatim) and tags
    gone."""
    markup = re.sub(r"<title>.*?</title>", " ", markup, flags=re.S)
    markup = re.sub(r'\stitle="[^"]*"', " ", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _house_style(text: str) -> None:
    assert EM_DASH not in text, text[:200]
    low = text.lower()
    found = [w for w in BANNED if re.search(rf"\b{w}\b", low)]
    assert not found, (found, text[:200])


def _stripped(p):
    """The fixture with the focal company's figures and the cohort's blocks taken away."""
    q = copy.deepcopy(p)
    me = q["companies"]["AZN"]
    me.update(price=None, change_1d=None, change_5d=None, range_52w=None, cap_usd_bn=None,
              beta=None, catalysts_12m=None)
    me["model"] = {k: None for k in me["model"]}
    me["street"] = {k: None for k in me["street"]}
    me["score"] = {"score": None, "rank": None, "ranked_of": None, "rank_range": None}
    me["loe"] = {"share_5y": None, "at_risk_5y_usd": None, "priced_total_usd": None}
    me["slip"] = None
    me.pop("ira", None)
    for w in me["rel"]:
        me["rel"][w] = {"rel": None, "own": None, "covers": None}
    q["closes"]["AZN"] = []
    q["focal"].update(fair_value={"ok": False, "lenses": [], "rating": {}}, pillars={},
                      positives=[], negatives=[], events=[], approvals=[], readouts=[],
                      loe_first=[], note_rate=None)
    q.update(events=[], week_items=[], lanes={"start": q["lanes"]["start"],
                                               "end": q["lanes"]["end"], "events": [],
                                               "approvals": []},
             markets={"rates": [], "fx": [], "benchmarks": [], "days": 30},
             policy={"items": [], "events": []})
    return q


# ----------------------------------------------------------------------------- purity
def test_the_builders_module_touches_no_streamlit_network_or_clock():
    tree = ast.parse(BUILDERS.read_text(), feature_version=(3, 9))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"streamlit", "urllib", "requests", "os", "time", "random"}
    source = BUILDERS.read_text()
    assert "today()" not in source and ".now(" not in source
    assert not re.search(r"(?<![\w.])open\(", source)


def test_builders_are_pure_and_repeatable(payload):
    before = json.dumps(payload, sort_keys=True)
    first = _all_blocks(payload)
    second = _all_blocks(payload)
    assert first == second
    assert json.dumps(payload, sort_keys=True) == before
    for name, out in first.items():
        assert out, name


def test_markdown_safe(payload):
    """One st.markdown per band: no blank line and no four-space indent can break it."""
    for name, out in _all_blocks(payload).items():
        assert "\n\n" not in out, name
        assert not re.search(r"\n {4}", out), name


# ------------------------------------------------------------------------ house style
@pytest.mark.parametrize("window", ["1m", "3m", "1y"])
def test_house_style_of_every_visible_string(payload, window):
    for name, out in _all_blocks(payload, window).items():
        _house_style(_visible(out))


def test_section_labels_are_sentence_case(payload):
    labels = re.findall(r'<span class="sec-label">([^<]+)</span>',
                        "".join(_all_blocks(payload).values()))
    assert len(labels) >= 10
    names = {"AstraZeneca", "XLV", "AZN", "Medicare"}
    for label in labels:
        label = html.unescape(label)
        assert label[0].isupper(), label
        rest = [w for w in label.split()[1:] if w[0].isupper() and w.strip(",") not in names]
        assert not rest, label


def test_the_lead_line_reads_its_inputs(payload):
    lead = payload["lead"]["3m"]
    line = _visible(UC.lead_line(payload, "3m"))
    us, eu = lead["us_median"], lead["eu_median"]
    assert f"{abs(us) * 100:.1f}%" in line and f"{abs(eu) * 100:.1f}%" in line
    assert line.startswith("US big pharma ") and "in three months" in line
    own = lead["own"]
    place = 1 + sum(1 for v in own.values() if v > own["AZN"])
    assert f"{UC.ordinal(place)} of {len(own)}" in line
    gone = copy.deepcopy(payload)
    gone["lead"]["3m"]["eu_median"] = None
    assert UC.lead_line(gone, "3m") == ""                    # no sentence with a hole


# ------------------------------------------------------------------- the window switch
def _cells(markup):
    return re.findall(r'<div class="(c0|c-[a-z]+)">', markup), \
        re.split(r'(?=<div class="(?:c0|c-[a-z]+)">)', markup)[1:]


def test_the_window_switch_changes_only_the_window_cells(payload):
    keys, one = _cells(UC.spotlight_html(payload, "1m"))
    _, year = _cells(UC.spotlight_html(payload, "1y"))
    changed = [k for k, a, b in zip(keys, one, year) if a != b]
    assert changed == ["c-rel"]
    assert "Against XLV, 1 month" in one[keys.index("c-rel")]
    assert UC.hero_map(payload, "1m") != UC.hero_map(payload, "1y")
    assert UC.band_week_rates_exposure(payload) == UC.band_week_rates_exposure(payload)


# ---------------------------------------------------------------- null is never zero
def test_a_company_with_no_model_value_is_named_not_plotted(payload):
    plotted = set(re.findall(r'<g class="b[^"]*" data-ticker="([A-Z]+)"',
                             UC.hero_map(payload, "1y")))
    missing = {t for t, c in payload["companies"].items() if c["model"]["upside"] is None}
    assert missing and not plotted & missing
    assert all(t in UC.map_counts(payload, "1y") for t in missing)
    assert len(plotted) == len(payload["companies"]) - len(missing)


def test_the_focal_company_with_nothing_on_file_still_draws(payload):
    q = _stripped(payload)
    out = _all_blocks(q)
    # Every figure the focal company lacks prints the words, and no value cell holds a
    # zero in its place.
    values = re.findall(r'<div class="v[^"]*">(.*?)</div>', out["spotlight"])
    assert sum(1 for v in values if v == UC.NO_DATA) >= 7
    assert not [v for v in values if re.match(r"[+−]?0(\.0+)?(%|<)", v)]
    # The strips still show the cohort but carry no dot for the focal company.
    assert '<title>AZN</title>' not in out["spotlight"]
    assert 'data-ticker="AZN"' not in UC.hero_map(q, "1y")
    assert "AZN" in UC.map_counts(q, "1y")
    assert "Nothing material across the group" in out["band3"]
    assert "no free data" in _visible(out["band3"])            # the value block
    assert UC.NO_DATA in _visible(out["dialog"])
    _house_style(_visible("".join(out.values())))


def test_no_week_move_prints_na_not_zero(payload):
    q = copy.deepcopy(payload)
    q["companies"]["LLY"]["change_5d"] = None
    board = UC.board_svg(q, "1y")
    row = re.search(r'data-ticker="LLY">(.*?)</g>', board, re.S).group(1)
    assert ">n/a<" in row and "0.0%" not in row


def test_exposure_bars_only_where_a_share_is_on_file(payload):
    q = copy.deepcopy(payload)
    q["companies"]["MRK"]["ira"]["share"] = None
    q["companies"]["MRK"]["ira"]["selected"] = []
    svg = UC.exposure_html(q)
    assert "MRK Part D" not in svg
    assert "none selected" in svg


def test_prices_leave_out_a_company_with_no_closes(payload):
    q = copy.deepcopy(payload)
    q["closes"]["GSK"] = []
    out = UC.prices_html(q)
    assert '<span class="tk">GSK</span>' not in out
    assert len(re.findall(r'<div class="uv-sm(?: me)?" ', out)) == len(payload["companies"]) - 1


# ------------------------------------------------------------------------- the board
def test_the_board_draws_every_event_in_the_90_days_and_marks_the_firm_one(payload):
    board = UC.board_svg(payload, "1y")
    events = payload["events"]
    marks = len(re.findall(r"<(?:circle|path|rect)[^>]*><title>[^<]*(?:\(month only\)|\((?:estimated|confirmed|stated|month)\))", board))
    assert marks == len(events)
    firm = [e for e in events if e["firm"]]
    assert firm and all(e["regulatory"] for e in firm)
    for e in firm:
        assert f"{'PDUFA' if (e['type'] or '').upper() == 'PDUFA' else 'FDA'} {UC.dday(e['date'])}" \
            in board
    assert UC.board_counts(payload) == f"{len(events)} dated, {len(firm)} firm"


def test_every_row_and_bubble_is_a_click_target(payload):
    hero = UC.hero_html(payload, "1y")
    rows = set(re.findall(r'<g class="row[^"]*" data-ticker="([A-Z]+)"', hero))
    assert rows == set(payload["companies"])
    assert re.search(r'<g class="b azn" data-ticker="AZN"', hero)


# ---------------------------------------------------------------------- the stylesheet
def test_no_drawn_label_is_under_9px(payload):
    """Every SVG label is set at 9px or more, in every window."""
    for w in ("1m", "3m", "1y"):
        for name, markup in _all_blocks(payload, w).items():
            sizes = [float(x) for x in re.findall(r'<text [^>]*font-size="([\d.]+)"', markup)]
            if sizes:
                assert min(sizes) >= 9, (w, name, min(sizes))


def test_the_week_minis_are_drawn_at_the_width_their_column_gives_them():
    """The ranked list's small charts are drawn 1:1: an SVG wider than its grid column is
    scaled down, and its 9px axis words with it (they printed at 7.4px)."""
    css = UNIVERSE_CSS.read_text()
    m = re.search(r"\.uv-wm > summary \{[^}]*grid-template-columns:\s*([^;]+);", css)
    assert m, "the ranked list's grid is not where the test reads it"
    cols = re.sub(r"\(([^)]*)\)", lambda x: "(" + x.group(1).replace(" ", "") + ")",
                  m.group(1)).split()
    assert cols[3] == f"{UC.IW}px", cols


def _lane_rules_hold(placed, reserved=()):
    """No two labels overlap, none sits on a reserved box, and no leader runs through a
    nearer label: the rules place_lane_labels promises."""
    boxes = []
    for xx, lab, anc, tier, yy in placed:
        wd = UC.lab_w(lab, 9)
        x0 = xx + 2 if anc == "start" else xx + 3 - wd
        boxes.append(((x0, yy - 9, x0 + wd, yy + 2), xx, tier))
    for i, (a, xa, ta) in enumerate(boxes):
        assert not any(UC.labels_hit(a, r) for r in reserved), placed[i]
        for j, (b, xb, tb) in enumerate(boxes):
            if i == j:
                continue
            assert not UC.labels_hit(a, b), (placed[i], placed[j])
            if ta * tb > 0 and abs(tb) > abs(ta):
                assert not (a[0] - 4 <= xb <= a[2] + 4), (placed[j], "runs through", placed[i])


def test_policy_labels_never_sit_under_another_documents_leader():
    """The fixture's Medicare lane: a greedy pass put the June proposed rule's leader
    through the July draft guidance's label, pairing each square with the wrong title."""
    marks = [(228.3, "CY2027 final rule"), (315.3, "Negotiation proposed rule"),
             (357.0, "Negotiation draft guidance"), (437.8, "Pharmacy contracting RFI")]
    reserved = [(354.1, 76.0, 514.3, 88.0)]           # "comments close 23 Nov, 48 days"
    placed = UC.place_lane_labels(marks, 64, reserved, 108, 571)
    assert sorted(p_[1] for p_ in placed) == sorted(m[1] for m in marks)
    _lane_rules_hold(placed, reserved)


def test_policy_label_rules_hold_on_crowded_lanes():
    import random
    rng = random.Random(7)
    words = ["Rule", "Notice", "Draft guidance", "Final guidance", "Comment request",
             "Tariff notice on patented products", "Proposed rule"]
    for _ in range(200):
        marks = [(rng.uniform(112, 560), rng.choice(words)) for _ in range(rng.randint(1, 7))]
        placed = UC.place_lane_labels(marks, 64, [], 108, 571)
        _lane_rules_hold(placed)


def test_the_policy_lanes_count_earlier_documents_by_their_own_years(payload):
    """The read runs two years back: documents before this year are counted under the
    years they carry, never all under last year."""
    svg = UC.policy_svg(payload)
    assert ">4 in 2025<" in svg and ">1 in 2025<" in svg
    q = copy.deepcopy(payload)
    q["policy"]["items"].append({"lane": "cms_ira", "published_on": "2024-11-04",
                                 "doc_type": "Rule", "title": "Medicare Program; a rule",
                                 "short": "A rule"})
    assert ">5 in 2024 to 2025<" in UC.policy_svg(q)
    q = copy.deepcopy(payload)
    q["today"] = "2027-01-15"
    svg = UC.policy_svg(q)
    assert ">8 in 2025 to 2026<" in svg and ">4 in 2025 to 2026<" in svg
    assert "in 2026<" not in svg.replace("2025 to 2026<", "")


def test_the_prices_are_indexed_on_a_day_that_traded(payload):
    """A year back from the 5 Oct 2026 close is a Sunday; the panels start on the first
    close after it and say so."""
    assert UC.prices_basis(payload) == "indexed to 100 on 6 Oct 2025"
    first = UC._d(payload["benchmark"][0][0])
    assert first.weekday() < 5


def test_the_dialog_never_lists_a_condition_as_an_asset(payload):
    """AZN's 27 Oct study names no drug, so its short name is a condition; the dialog's
    asset column says no drug is named rather than printing "Hepatocellular" as one."""
    ev = {e["date"]: e for e in payload["focal"]["events"]}
    assert ev["2026-10-27"]["short_basis"] == "condition"
    assert ev["2026-10-31"]["short_basis"] == "asset"
    rows = re.findall(r'<div class="uv-ev"[^>]*>(.*?)</div>', UC.dialog_html(payload), flags=re.S)
    cells = [_visible(r) for r in rows]
    oct27 = next(c for c in cells if c.startswith("○ 27 Oct"))
    assert "no drug named" in oct27 and not oct27.split("no drug named")[0].strip().endswith(
        "Hepatocellular")
    assert any(c.startswith("○ 31 Oct Truqap") for c in cells)


def test_universe_css_is_tokens_only_and_reaches_the_page_and_the_frame(monkeypatch):
    css = UNIVERSE_CSS.read_text()
    assert not HEX.findall(css), "a hex colour in universe.css"
    used = set(re.findall(r"var\(\s*(--[\w-]+)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))
    defined = set()
    for f in (FRONTEND / "assets" / "tokens.css", FRONTEND / "assets" / "research.css",
              UNIVERSE_CSS):
        defined |= set(re.findall(r"(--[\w-]+)\s*:", f.read_text()))
    assert not used - defined, used - defined
    assert ".uv { font-family: var(--font-ui)" in css
    import theme
    page = theme.css()
    assert css in page and page.index(theme._RESEARCH_CSS) < page.index(css)
    import universe_page
    assert css in universe_page._frame_css()


def test_the_svgs_read_colour_from_the_tokens_only(payload):
    from components import tokens as TK
    palette = {v.upper() for k, v in vars(TK).items() if isinstance(v, str) and v.startswith("#")}
    palette |= {v.upper() for v in TK.PHASE_RAMP.values()}
    svg = "".join(_all_blocks(payload).values())
    for h in set(HEX.findall(svg)):
        h = h.upper()
        if h in palette:
            continue
        # A blend of two tokens (the wash under a bubble or a row) is allowed; anything
        # else is a literal.
        rgb = tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
        assert any(_is_blend(rgb, a, b) for a in palette for b in palette), h


def _is_blend(rgb, a, b):
    A = tuple(int(a[i:i + 2], 16) for i in (1, 3, 5))
    B = tuple(int(b[i:i + 2], 16) for i in (1, 3, 5))
    for step in range(0, 101):
        t = step / 100
        if all(abs(round(A[i] * t + B[i] * (1 - t)) - rgb[i]) <= 1 for i in range(3)):
            return True
    return False


# ------------------------------------------------------------------------- the switch
@pytest.fixture(scope="module")
def switch():
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "_universe_redesigned")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_REDESIGN_TICKERS"
                                                  for t in n.targets))]
    space: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


def test_only_azn_takes_the_redesign(switch):
    assert switch["_REDESIGN_TICKERS"] == {"AZN"}
    on = switch["_universe_redesigned"]
    assert on("AZN", "Overview")
    assert not on("AZN", "Markets") and not on("AZN", "Policy")
    for t in ("LLY", "NVO", "JNJ", "ROG", "BAYN", "CRSP"):
        assert not on(t, "Overview")


def test_every_other_company_keeps_todays_overview_called_as_before():
    source = APP.read_text()
    block = source[source.index('        if _view == "Markets":'):]
    block = block[:block.index("    with insights_tab:")]
    assert ("_universe_redesigned(ticker, _view)" in block
            and "universe_page.render(api_base, ticker)" in block)
    assert block.rstrip().endswith(
        "_universe_overview(api_base, engine, _engine_name, _covered,\n"
        "                               _all_changes, universe_feed)")
    overview = source[source.index("def _universe_overview("):
                      source.index("def _markets_view(")]
    assert "universe_page" not in overview and "universe_cc" not in overview


# ------------------------------------------------------------------- the app, live API
def _api_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


needs_api = pytest.mark.skipif(not _api_up(), reason=f"API not running at {BASE}")


def _universe_markdown(ticker):
    from streamlit.testing.v1 import AppTest
    test = AppTest.from_file(str(APP), default_timeout=300)
    test.query_params["ticker"] = ticker
    test.run()
    assert not test.exception, test.exception
    tab = next(t for t in test.tabs if t.label == "Universe")

    def walk(block):
        for child in getattr(block, "children", {}).values():
            yield child
            yield from walk(child)
    return "".join(str(n.value) for n in walk(tab) if getattr(n, "type", "") == "markdown")


@needs_api
def test_live_app_azn_draws_the_command_centre():
    md = _universe_markdown("AZN")
    assert 'class="uv-sp"' in md and "AstraZeneca against the group" in md
    assert "This week, ranked" in md and "Approvals and readouts" in md
    assert "Headlines this week" not in md


@needs_api
def test_live_app_another_company_keeps_todays_overview():
    md = _universe_markdown("LLY")
    assert "uv-sp" not in md and "Headlines this week" in md


# ------------------------------------------------------------- the page, offline
# universe_page draws through Streamlit, so it is run in AppTest on the saved payload with
# the read replaced: no API, no network.
_PAGE = '''
import json, sys
sys.path.insert(0, {frontend!r})
import universe_page
payload = json.loads(open({fixture!r}).read())
{tweak}
universe_page.fetch = lambda api_base, ticker, part="all": payload
universe_page.render("http://api.invalid", "AZN")
'''


def _page(tweak=""):
    from streamlit.testing.v1 import AppTest
    _patch_button_group()
    test = AppTest.from_string(_PAGE.format(frontend=str(FRONTEND), fixture=str(FIXTURE),
                                            tweak=tweak), default_timeout=60)
    test.run()
    assert not test.exception, test.exception
    return test


def _patch_button_group():
    """A single-select segmented control's session value is a string, and AppTest's
    ButtonGroup.indices iterates its characters (as test_catalysts_tab_ui notes)."""
    from streamlit.testing.v1 import element_tree

    def indices(self):
        values = self.value
        if values is None:
            return []
        if not isinstance(values, (list, tuple)):
            values = [values]
        labels = [getattr(o, "content", o) for o in self.options]
        return [labels.index(v) for v in values if v in labels]

    element_tree.ButtonGroup.indices = property(indices)


def _md(test):
    return "".join(str(m.value) for m in test.markdown)


def test_page_draws_every_band_and_the_window_switch_reruns_it():
    test = _page()
    md = _md(test)
    for needle in ('class="uv-lead"', 'class="uv-sp"', "This week, ranked",
                   "Rates and the AZN value", "Medicare and exclusivity",
                   "Approvals and readouts", "Prices, 12 months", "Policy calendar"):
        assert needle in md, needle
    assert "Against XLV, 1 year" in md
    test.button_group(key="uv_window").set_value("3 months").run()
    assert not test.exception
    md = _md(test)
    assert "Against XLV, 3 months" in md and "in three months" in md


def test_page_without_the_component_falls_back_to_pills():
    test = _page("universe_page._uvboard = None")
    md = _md(test)
    assert 'class="uv-map"' in md and 'class="uv-board"' in md     # the SVGs, drawn inline
    pills = test.button_group(key="uv_pick")
    labels = [getattr(o, "content", o) for o in pills.options]
    assert sorted(labels) == sorted(json.loads(FIXTURE.read_text())["companies"])


def test_page_with_the_focal_company_stripped_still_draws():
    tweak = ("import copy, importlib, pathlib\n"
             f"sys.path.insert(0, {str(pathlib.Path(__file__).parent)!r})\n"
             "import test_universe_tab_ui as T\n"
             "payload = T._stripped(payload)")
    md = _md(_page(tweak))
    assert 'class="uv-sp"' in md and UC.NO_DATA in md


def test_a_pick_opens_the_company_dialog_once():
    test = _page("universe_page._uvboard = None")
    test.button_group(key="uv_pick").set_value("AZN").run()
    assert not test.exception, test.exception
    md = _md(test)
    assert 'class="uv uv-dg"' in md and "Value against the price" in md
    labels = [b.label for b in test.button]
    assert labels[:3] == ["Open Key insights", "Open Catalysts", "Open Comps"]
    # A rerun for any other reason does not open it again.
    test.run()
    assert 'class="uv uv-dg"' not in _md(test)


def test_an_incomplete_read_is_drawn_once_and_never_held(monkeypatch):
    """A read the API marks incomplete (taken while it was still valuing the group) is
    used for the run that asked, then asked for again; a complete read is held. The
    module is loaded on its own, since the page tests above replace its fetch."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("universe_page_fetch_test",
                                                  FRONTEND / "universe_page.py")
    UP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(UP)
    reads = []

    def read(api_base, ticker, part):
        reads.append(part)
        return {"complete": len(reads) > 1, "n": len(reads)}

    monkeypatch.setattr(UP, "_read", read)
    UP._fetch_complete.clear()
    try:
        assert UP.fetch("http://api.invalid", "AZN")["n"] == 1
        assert UP.fetch("http://api.invalid", "AZN")["n"] == 2
        assert UP.fetch("http://api.invalid", "AZN")["n"] == 2
        assert len(reads) == 2
    finally:
        UP._fetch_complete.clear()


def test_an_incomplete_read_says_so_and_a_complete_one_does_not(payload):
    assert UC.incomplete_note(payload) == ""
    q = copy.deepcopy(payload)
    q["complete"] = False
    for t in ("LLY", "MRK"):
        q["companies"][t]["model"]["upside"] = None
    note = UC.incomplete_note(q)
    n = sum(1 for c in q["companies"].values() if c["model"]["upside"] is not None)
    assert f"{n} of {len(q['companies'])} big pharma have a model value" in note
    _house_style(_visible(note))
    assert note in UC.dialog_html(q)


def test_apply_goto_sets_the_picker_before_it_is_drawn():
    """A dialog button reruns the dialog as a fragment, which AppTest cannot drive; this
    checks what the click hands the next run (the click itself is checked in a browser)."""
    from streamlit.testing.v1 import AppTest
    script = (f"import sys\nsys.path.insert(0, {str(FRONTEND)!r})\nimport streamlit as st\n"
              "import universe_page\n"
              "st.session_state['_uv_goto'] = {'ticker': 'LLY', 'tab': 'Key insights'}\n"
              "universe_page.apply_goto(['AZN', 'LLY'])\n"
              "st.selectbox('Company', ['AZN', 'LLY'], key='company_pick')\n")
    test = AppTest.from_string(script, default_timeout=30).run()
    assert not test.exception, test.exception
    assert test.selectbox(key="company_pick").value == "LLY"
    assert test.session_state["_uv_tab_click"] == "Key insights"
