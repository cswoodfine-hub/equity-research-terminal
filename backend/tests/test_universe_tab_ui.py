"""The redesigned Universe tab (frontend/universe_cc.py, universe_page.py, the uvboard
component and the switch in streamlit_app.py).

The tab is the week across the group on one 1440 by 780 screen: a control row (the week,
the regions against the company picked, the window and the close), the band (the lead
story and the ranked feed beside the company board, the cheap to expensive ribbon under
them) and a slim tabbed panel holding everything else. The parts that make it fit are
pinned here; the fit itself was measured in a browser.

Four layers.

The builders are pure functions of the payload of ``GET /universe/command``, saved from the
2026-10-06 book as ``fixtures/universe/command_AZN.json``. They are run on it and on copies
with figures taken away: every block draws, a missing figure prints "no free data" or is
named as left off, and nothing missing is drawn as a zero.

The house style of every string a reader sees. A source's own words (a quoted headline, a
filing's title) are marked as such and checked to be the source's; registry and release
titles in hovers (<title> elements and title= attributes) are left out of the check.

The switch: read out of the Streamlit script by name (it runs the whole app on import), so
a company outside ``_REDESIGN_TICKERS`` provably takes today's overview, called as before.

Then the app itself through AppTest against an API, skipped when none is up, like the
other tab tests.
"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import html
import inspect
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
    """Every block the page draws, by name, and the builders the dialog shares."""
    blocks = {
        "status": UC.status_line(p), "lead": UC.lead_line(p, w), "kicker": UC.week_kicker(p),
        "front": UC.front_html(p), "notes": UC.notes_text(p),
        "spotlight": UC.spotlight_section(p, w) + UC.spotlight_html(p, w),
        "dialog": UC.dialog_html(p, "the board"), "index": UC.index_html(p, w),
    }
    return blocks


VB = re.compile(r'<span class="vb">([^<]*)</span>')


def _visible(markup: str) -> str:
    """What a reader sees without hovering: hovers (registry titles, verbatim) and tags
    gone."""
    markup = re.sub(r"<title>.*?</title>", " ", markup, flags=re.S)
    markup = re.sub(r'\stitle="[^"]*"', " ", markup)
    markup = VB.sub(" ", markup)                             # the source's own words
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
    assert len(labels) >= 2
    names = {"AstraZeneca", "XLV", "PPH", "AZN", "Medicare", "FX"}
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
    assert line.startswith("US median ") and line.endswith("over three months")
    assert ", Europe " in line and ", AZN " in line
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
    # The week and the index do not move with the window; only the control row's line does.
    assert UC.front_html(payload) == UC.front_html({**payload, "window": "1m"})
    # The index follows the window: its own first day and label move with the switch.
    one, year = UC.index_html(payload, "1m"), UC.index_html(payload, "1y")
    assert one != year and "· 1 month ·" in one and "· 1 year ·" in year
    assert UC.ew_index(payload, "1m")["dates"][0] == payload["windows"]["1m"]["first"]
    assert UC.lead_line(payload, "1m") != UC.lead_line(payload, "1y")


# ---------------------------------------------------------------- null is never zero


def test_the_focal_company_with_nothing_on_file_still_draws(payload):
    q = _stripped(payload)
    out = _all_blocks(q)
    # Every figure the focal company lacks prints the words, and no value cell holds a
    # zero in its place.
    values = re.findall(r'<div class="v(?: [^"]*)?">(.*?)</div>', out["spotlight"])
    assert sum(1 for v in values if v == UC.NO_DATA) >= 7
    assert not [v for v in values if re.match(r"[+−]?0(\.0+)?(%|<)", v)]
    # The hover cards still rank the cohort; the focal company is not placed in them.
    assert out["spotlight"].count('class="r">not placed<') >= 6
    assert 'class="hc-r me"' not in out["spotlight"]
    # The band still draws the company: its tile says no free data, its row no move.
    tile = out["front"].split('data-ticker="AZN"')[-1]
    assert f'<span class="v">{UC.NO_DATA}</span>' in tile.split("</div>")[0]
    row = re.search(r'data-ticker="AZN"[^>]*><span class="tk">AZN</span>(<span[^>]*>[^<]*</span>)',
                    out["front"]).group(1)
    assert UC.NO_DATA in row and "0.0%" not in row
    assert "Nothing material across the group" in out["front"]
    assert UC.NO_DATA in _visible(out["dialog"])
    _house_style(_visible("".join(out.values())))


def test_exposure_bars_only_where_a_share_is_on_file(payload):
    q = copy.deepcopy(payload)
    q["companies"]["MRK"]["ira"]["share"] = None
    q["companies"]["MRK"]["ira"]["selected"] = []
    out = UC.exposure_html(q)
    assert "MRK Part D" not in out
    assert "<title>MRK: no drug selected for Medicare negotiation</title>" in out
    none = re.search(r"None selected: ([^.]+)\.", _visible(out)).group(1).split(", ")
    assert "MRK" in none
    # Selected, but no share on file: no bar and no zero, the words on hover.
    q["companies"]["MRK"]["ira"]["selected"] = [{"brand": "JANUVIA", "ipay": 2026}]
    out = UC.exposure_html(q)
    assert "MRK Part D" not in out and f"<title>MRK: {UC.NO_DATA}</title>" in out


def test_prices_leave_out_a_company_with_no_closes(payload):
    q = copy.deepcopy(payload)
    q["closes"]["GSK"] = []
    out = UC.prices_html(q)
    assert '<span class="tk">GSK</span>' not in out
    assert len(re.findall(r'<div class="uv-sm(?: me)?" ', out)) == len(payload["companies"]) - 1


# ------------------------------------------------------------------------- the board


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
    m = re.search(r"\.uw-it \{[^}]*grid-template-columns:\s*([^;]+);", css)
    assert m, "the ranked list's grid is not where the test reads it"
    cols = re.sub(r"\(([^)]*)\)", lambda x: "(" + x.group(1).replace(" ", "") + ")",
                  m.group(1)).split()
    assert cols[2] == f"{UC.IW}px", cols


def test_the_focal_price_tile_keeps_its_row_lines():
    """The washed AZN tile sits on the same text lines as its row: its bleed above is
    given back in padding, after its rule's extra pixel, and its height is the others'."""
    css = UNIVERSE_CSS.read_text()
    base = re.search(r"\.uv-sm \{([^}]*)\}", css).group(1)
    me = re.search(r"\.uv-sm\.me \{([^}]*)\}", css).group(1)

    def num(decl, pattern):
        return [float(v) for v in re.search(pattern, decl).group(1).split("px")[:-1]]

    b_rule = num(base, r"border-top:\s*([\d.]+px)")[0]
    b_top = num(base, r"padding-top:\s*([\d.]+px)")[0]
    m_rule = num(me, r"border-top:\s*([\d.]+px)")[0]
    m_top, _side, m_bot = num(me, r"padding:\s*([\d.]+px [\d.]+px [\d.]+px);")
    mt, _ms, mb = num(me, r"margin:\s*(-?[\d.]+px -?[\d.]+px -?[\d.]+px);")
    assert mt + m_rule + m_top == b_rule + b_top                 # its first line on the row's
    assert mt + m_rule + m_top + m_bot + mb == b_rule + b_top    # and the row's height


def _ink(markup):
    """Each SVG label's box as the browser measures it: an advance of 0.6em, and the
    font's ascent and descent (Plex Mono's run about 1em above the baseline and 0.3em
    under it)."""
    out = []
    for m in re.finditer(r'<text x="([\d.-]+)" y="([\d.-]+)"[^>]*font-size="([\d.]+)"([^>]*)>'
                         r'([^<]*)</text>', markup):
        x, y, fs, rest, s = float(m[1]), float(m[2]), float(m[3]), m[4], m[5]
        wd = len(html.unescape(s)) * fs * 0.6
        x0 = x - wd if 'text-anchor="end"' in rest else (
            x - wd / 2 if 'text-anchor="middle"' in rest else x)
        out.append((html.unescape(s), (x0, y - fs, x0 + wd, y + fs * 0.3)))
    return out


def test_a_narrow_ranking_cell_drops_its_unit_before_its_place_meets_its_value():
    """Under 1440 wide the value and its place collided ("−26.5 pts16th of 18" at 1366):
    each cell is a size container that drops the value's unit below its 1440 width, and
    wraps the place under the value rather than over it if they still meet. The hovered
    cell is lifted so its card stays over the containers beside it."""
    css = UNIVERSE_CSS.read_text()
    assert re.search(r"\.uv-sp > div \{[^}]*container-type: inline-size", css)
    assert re.search(r"\.uv-sp > div:hover \{[^}]*z-index: \d", css)
    assert re.search(r"\.uv-sp \.vr \{[^}]*flex-wrap: wrap", css)
    assert re.search(r"\.uv-sp \.r \{[^}]*margin-left: auto", css)
    q = dict(re.findall(r"@container \(max-width: ([\d.]+)px\) \{ ([^{]+) \{ display: none; \} \}",
                        css))
    assert {v.strip() for v in q.values()} == {".uv-sp .v .u", ".uv-sp .c0 .v .u"}, q
    # The thresholds sit just under the cells' content widths at 1440: 1408px over
    # 1.32 + 7 shares, less each cell's padding (16px; the price cell 10px).
    share = 1408 / 8.32
    widths = {".uv-sp .v .u": share - 16 - 1, ".uv-sp .c0 .v .u": share * 1.32 - 10}
    for px, sel in q.items():
        assert 0 < widths[sel.strip()] - float(px) < 2, (sel, px, widths[sel.strip()])


def test_the_board_frame_stacks_at_the_pages_breakpoint_not_its_own():
    """The uvboard frame is the page's width less its 33px of gutters, so a media query
    read inside it fires 33px of viewport later than the page's: from 1180 to 1212 wide
    the frame stacked the hero under a one-screen page, which then scrolled. Inside the
    frame the hero keeps two columns down to 1147px."""
    css = UNIVERSE_CSS.read_text()
    page = re.search(r"@media \(max-width: ([\d.]+)px\) \{\s*/\* The lead drops", css)
    assert page and float(page.group(1)) == 1179.98
    m = re.search(r"@media \(min-width: ([\d.]+)px\) and \(max-width: ([\d.]+)px\) \{([^@]*)\}",
                  css)
    assert m, "no frame breakpoint"
    lo, hi, body = float(m.group(1)), float(m.group(2)), m.group(3)
    assert (lo, hi) == (1180 - 33, 1179.98)
    assert re.search(r"\.uv-frame \.uw-band \{[^}]*grid-template-columns: minmax\(0, 1fr\) "
                     r"470px", body)
    # It comes after the page's block, so it wins inside the frame.
    assert css.index(m.group(0)) > page.start()


def test_a_legend_hint_ends_in_an_ellipsis_not_a_cut_word():
    """A one-line legend narrower than 1440 clipped its closing hint mid-word ("click a
    b", "hover a row for its news, click fo"). The hint is the item that shrinks, and it
    ends in an ellipsis."""
    css = UNIVERSE_CSS.read_text()
    sp = re.search(r"\.uv-leg \.sp \{([^}]*)\}", css).group(1)
    for decl in ("display: block", "flex: 0 1 auto", "min-width: 0", "overflow: hidden",
                 "text-overflow: ellipsis", "margin-left: auto"):
        assert decl in sp, decl
    assert re.search(r"\.uv-leg span \{[^}]*white-space: nowrap", css)


def test_the_week_tag_column_holds_the_longest_tag():
    """A ranked item's tag sits on its kicker line; in the list of the ranks the column
    has no room for, it has a column of its own, which holds the longest tag the API
    sends. A tag is 9.5px mono capitals at 0.08em, after a 3px rule and 5px of air."""
    css = UNIVERSE_CSS.read_text()
    m = re.search(r"\.uw-mr \{[^}]*grid-template-columns:\s*([^;]+);", css)
    col = float(re.sub(r"\(([^)]*)\)", "", m.group(1)).split()[1].rstrip("px"))
    src = (ROOT / "backend" / "universe_command.py").read_text()
    tags = set(re.findall(r'"tag": "([A-Za-z0-9 ]+)"', src)) | {"phase 3", "result", "PDUFA",
                                                                 "FDA date"}
    longest = max(len(t) for t in tags)
    assert longest == 8, tags
    need = longest * 9.5 * (0.6 + 0.08) + 3 + 5
    assert col >= need, (col, need)
    assert re.search(r"\.uw-tag \{[^}]*font-size: 9\.5px[^}]*letter-spacing: 0\.08em", css)


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


# ------------------------------------------------------------- the one-screen layout
# The fit was measured in headless Chrome at 1440 by 900 (no page scroll with any panel
# tab open, and none at 1440 by 860). What these pin are the parts that make it: lose one
# and the page grows past the screen.
def _svg_size(markup, cls):
    m = re.search(rf'<svg class="{cls}" width="([\d.]+)" height="([\d.]+)"', markup)
    assert m, cls
    return float(m.group(1)), float(m.group(2))


def test_the_control_row_is_one_line(payload):
    """The lead is one line beside the window control, the status a close date and the
    notes behind a hover: no separate lead line, no cohort sentence."""
    lead = UC.lead_line(payload, "1y")
    assert lead.count("<div") == 1 and "<br" not in lead
    status = _visible(UC.status_line(payload).split('<span class="uv-nt-c">')[0])
    assert status == f"closes to {UC.dday(payload['price_date'])} notes ▾"
    assert UC.esc(UC.notes_text(payload)) in UC.status_line(payload)
    css = UNIVERSE_CSS.read_text()
    assert re.search(r"\.uv-lead \{[^}]*white-space: nowrap", css)
    assert re.search(r"\.uv-nt:hover \.uv-nt-c", css)


def test_the_spotlight_has_no_line_comparison_and_says_it_ranks_all(payload):
    """The peer-dot strip is gone from every cell; each ranked cell keeps its hover card
    of the whole cohort, marked by a caret, with its place beside the value."""
    sp = UC.spotlight_html(payload, "1y")
    cells = re.split(r'(?=<div class="(?:c0|c-[a-z]+)">)', sp)[1:]
    assert len(cells) == 8
    for cell in cells[1:]:
        assert "<circle" not in cell and 'class="uv-hc"' in cell
        assert '<span class="all"' in cell and ">▾</span>" in cell
        assert re.search(r'<span class="r"><b>\d+(st|nd|rd|th)</b> of \d+</span>', cell)
        # Three lines: the label, the value with its place, one sub-line.
        assert cell.count('<div class="k">') == cell.count('<div class="vr">') == 1
        assert cell.split('<div class="uv-hc">')[0].count('<div class="s">') == 1
    n = len(payload["companies"])
    assert f"hover a cell for all {n}" in UC.spotlight_section(payload)
    # The caret is drawn, not printed: the glyph read as a 4 by 3px speck. It is an 8 by
    # 5px triangle brighter than muted, and a cell with a card takes the help cursor.
    css = UNIVERSE_CSS.read_text()
    caret = re.search(r"\.uv-sp \.k \.all \{([^}]*)\}", css).group(1)
    assert "font-size: 0" in caret and "width: 0" in caret
    assert "border-left: 4px solid transparent" in caret
    assert "border-right: 4px solid transparent" in caret
    assert re.search(r"border-top: 5px solid color-mix\(in oklab, var\(--text\) \d+%, "
                     r"var\(--muted\)\)", caret)
    assert re.search(r"\.uv-sp > div:has\(> \.uv-hc\) \{ cursor: help; \}", css)


def test_the_page_has_no_panel_and_draws_the_index_under_the_frame():
    """The tabbed panel is gone: the index heads the tab, drawn before the frame and
    outside it, so its height can follow the screen's."""
    tree = ast.parse((FRONTEND / "universe_page.py").read_text(), feature_version=(3, 9))
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert "_panel" not in fns
    assert any(getattr(d, "attr", "") == "fragment" for d in fns["_command"].decorator_list)
    cmd = ast.unparse(fns["_command"]) if hasattr(ast, "unparse") else ""
    assert cmd.index("UC.index_html(p, w)") < cmd.index("UC.front_html(p)")
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", "") == "tabs"]
    css = UNIVERSE_CSS.read_text()
    assert re.search(r"\.uw-idx \{[^}]*height: clamp\(100px, calc\(100vh - 668px\), 330px\);", css)


def test_the_index_is_the_average_of_closes_set_to_100_on_the_first_day(payload):
    ix = UC.ew_index(payload, "3m")
    start = payload["windows"]["3m"]["first"]
    first = {t: next((c for d, c in payload["closes"][t] if d >= start), None)
             for t in payload["tickers"]}
    assert ix["dates"][0] >= start and ix["left_out"] == [] and len(ix["members"]) == 18
    d0, dn = ix["dates"][0], ix["dates"][-1]
    last = {t: [c for d, c in payload["closes"][t] if d <= dn][-1] for t in payload["tickers"]}
    want = 100 * sum(last[t] / first[t] for t in payload["tickers"]) / 18
    assert ix["values"][0] == pytest.approx(100.0) and ix["values"][-1] == pytest.approx(want)
    b = [c for d, c in payload["benchmark"] if d >= d0]
    assert ix["bench"][-1][1] == pytest.approx(100 * b[-1] / b[0])
    out = UC.index_html(payload, "3m")
    assert f'<b>{want:.1f}</b><span class="chg ' in out and UC.pc(want / 100 - 1) in out
    assert re.search(r'<span class="k">PPH</span><b class="(up|down)">'
                     + re.escape(UC.pc(b[-1] / b[0] - 1)) + "</b>", out)
    assert "vs PPH" not in out and "vs XLV" not in out      # no gap line, by request
    m = [c for d, c in payload["market"] if d >= d0]
    assert re.search(r'<span class="k">S&amp;P 500</span><b class="(up|down)">'
                     + re.escape(UC.pc(m[-1] / m[0] - 1)) + "</b>", out)
    assert 'class="mk"' in out and 'class="bm"' in out
    moves = {t: last[t] / first[t] - 1 for t in payload["tickers"]}
    best, worst = max(moves, key=moves.get), min(moves, key=moves.get)
    assert f"<b>{best} " in out and f"<b>{worst} " in out
    assert out.count('class="hv') == len(ix["dates"])       # a hover a trading day
    assert "the 18 on this page on their closes" in out
    assert "PPH (global big pharma) dashed and the S&amp;P 500 faint, both on price" in out
    assert 'vector-effect="non-scaling-stroke"' in out
    assert not re.search(r"<text", out)                     # every label is HTML, never scaled


def test_the_index_names_a_company_left_out_and_never_draws_from_nothing(payload):
    q = copy.deepcopy(payload)
    start = q["windows"]["3m"]["first"]
    first = min(d for t in q["tickers"] for d, _c in q["closes"][t] if d >= start)
    q["closes"]["ABBV"] = [r for r in q["closes"]["ABBV"] if r[0] > first]
    ix = UC.ew_index(q, "3m")
    assert ix["left_out"] == ["ABBV"] and len(ix["members"]) == 17
    assert "ABBV left out, no close on" in UC.index_html(q, "3m")
    empty = {**payload, "closes": {}, "benchmark": []}
    assert UC.ew_index(empty) is None
    assert UC.NO_DATA in UC.index_html(empty)


# ------------------------------------------------------------ the week across the group
def _as(payload, t):
    """The payload as it would read with ``t`` picked: the week is the API's, the same
    whichever company is in focus; only the focus moves."""
    q = copy.deepcopy(payload)
    q["ticker"] = t
    q["focal"]["ticker"] = t
    return q


def _unwashed(markup):
    """Markup with the wash taken off: the ``me`` class wherever it sits."""
    return re.sub(r'class="([^"]*)"', lambda m: 'class="' + " ".join(
        c for c in m.group(1).split() if c != "me") + '"', markup)


def test_the_week_reads_the_same_whichever_company_is_picked(payload):
    """Pick LLY instead of AZN and the band, the ribbon and the index read exactly the
    same: the Universe tab is the group, so no company is marked out on it."""
    lly = _as(payload, "LLY")
    assert UC.front_html(payload) == UC.front_html(lly)
    assert UC.index_html(payload) == UC.index_html(lly)
    for markup in (UC.front_html(payload), UC.index_html(payload)):
        assert not re.search(r'class="[^"]*\bme\b', markup)


def test_the_ranked_feed_runs_from_one_at_one_size_and_names_what_it_leaves(payload):
    rk = UC.ranked_html(payload)
    cols = rk.split('<div class="col">')[1:]
    assert len(cols) == 2
    ranks = [int(n) for n in re.findall(r'<div class="uw-it[^"]*"[^>]*><span class="n">(\d+)</span>', rk)]
    assert ranks == list(range(1, 1 + 2 * UC.RANK_ROWS))
    for col in cols:
        assert col.count('<div class="uw-it') == UC.RANK_ROWS
    rest = payload["week_items"][2 * UC.RANK_ROWS:]
    assert f'{len(rest)} more ▾' in rk
    assert re.findall(r'<div class="uw-mr"><span class="n">(\d+)</span>', rk) == \
        [str(i["rank"]) for i in rest]
    assert f"1 to {2 * UC.RANK_ROWS} of {len(payload['week_items'])}" in rk
    assert 'class="uw-lead"' not in UC.front_html(payload) and 'uw-hd' not in UC.front_html(payload)
    # Every item has its figure and its detail; none prints a bare zero for a gap.
    for it in payload["week_items"]:
        x = UC.feed_item(payload, it)
        assert x["fig"] and x["fig"] not in ("0", "0%", "+0.0%"), it["kind"]
        assert not any(str(k).startswith("For ") for k, _v in x["rows"])  # no focal row


def test_the_source_words_are_the_sources_and_the_rest_is_house_style(payload):
    """Every string marked as a source's own words is one the payload carries as
    verbatim; everything else a reader sees follows house style. Alexion's notice says
    "showcase": it is quoted, never written."""
    sources = set()
    for it in payload["week_items"]:
        if it.get("verbatim"):
            sources.add(it["head"])
        if it.get("quote"):
            sources.add(it["quote"])
        sources |= {v for k, v in it.get("rows") or [] if str(k).startswith("Filed ")}
    for t, kinds in payload["week"]["grid"].items():
        sources |= {x["text"] for k in kinds.values() for x in k if x["verbatim"]}
    marked = [html.unescape(m) for b in _all_blocks(payload).values() for m in VB.findall(b)]
    assert marked and set(marked) <= sources, set(marked) - sources
    assert any("showcase" in m for m in marked)
    for name, out in _all_blocks(payload).items():
        _house_style(_visible(out))


def test_the_board_names_every_company_with_its_week_news_and_next_date(payload):
    board = UC.board_html(payload)
    rows = re.findall(r'<div class="uw-br[^"]*" data-ticker="([A-Z]+)" style="--uw-ow:(\d+);'
                      r'--uw-on:(\d+);--uw-ox:(\d+)"', board)
    assert sorted(r[0] for r in rows) == sorted(payload["companies"])
    for k in (1, 2, 3):                       # each sort is an order of all eighteen
        assert sorted(int(r[k]) for r in rows) == list(range(0, 2 * len(rows), 2))
    wk = {t: c["change_5d"] for t, c in payload["companies"].items()}
    by_week = [r[0] for r in sorted(rows, key=lambda r: int(r[1]))]
    assert by_week == sorted(wk, key=lambda t: (-wk[t], t))
    # The benchmark's week (PPH) sits between the last company above it and the first below.
    xlv = payload["bench_week"]["change"]
    above = sum(1 for v in wk.values() if v > xlv)
    assert f'class="uw-bx" style="--uw-ow:{2 * above - 1}"' in board
    nxt = payload["week"]["next"]
    gsk = re.search(r'data-ticker="GSK".*?<span class="nd([^"]*)">([^<]*)</span>'
                    r'<span class="nx([^"]*)">([^<]*)</span>', board).groups()
    assert gsk == (" fda firm", "26 Oct", " fda", "PDUFA Bepirovirsen")
    assert nxt["BAYN"] is None and "none dated in 90 days" in board
    est = [t for t, e in nxt.items() if e and not e["firm"]]
    for t in est:
        assert re.search(rf'data-ticker="{t}".*?<span class="nd[^"]* est', board), t
    news = payload["week"]["news"]
    for t in payload["companies"]:
        cell = re.search(rf'data-ticker="{t}".*?<span class="nw([^"]*)">([^<]*)</span>', board)
        assert cell.group(2) == (str(len(news[t])) if news[t] else "·"), t
    # No valuation column: the ribbon carries cheap and expensive.
    assert "Cheap or expensive" not in board and "upside" not in _visible(board).lower()
    q = copy.deepcopy(payload)
    q["companies"]["LLY"]["change_5d"] = None
    row = re.search(r'data-ticker="LLY".*?<span class="wk([^"]*)">([^<]*)</span>',
                    UC.board_html(q)).groups()
    assert row == (" none", UC.NO_DATA)


def test_the_ribbon_runs_cheap_to_expensive_with_no_value_last(payload):
    rib = UC.ribbon_html(payload)
    tiles = re.findall(r'<div class="uw-tile([^"]*)" data-ticker="([A-Z]+)"', rib)
    order = [t for _c, t in tiles]
    assert order == payload["week"]["value_order"]
    up = {t: payload["companies"][t]["model"]["upside"] for t in order}
    have = [t for t in order if up[t] is not None]
    assert have == sorted(have, key=lambda t: -up[t])
    assert [t for t in order if up[t] is None] == order[len(have):] == ["BAYN"]
    assert "na" in tiles[-1][0].split() and UC.NO_DATA in rib.split('data-ticker="BAYN"')[1]
    # The rule sits where value meets the price: after the last cheap, before the first dear.
    seq = re.findall(r'<div class="uw-zero">|data-ticker="([A-Z]+)"', rib)
    zero = seq.index("")
    assert up[seq[zero - 1]] >= 0 > up[seq[zero + 1]]
    assert not [c for c, _t in tiles if "me" in c.split()]   # no company marked out
    # A tile's hover: the close, the model's 12-month value and rating, the street target.
    card = _visible(rib.split('data-ticker="SNY"')[1].split('</div></div>')[0])
    assert "Close 39.51 EUR" in card and "Strong buy" in card and "Street target" in card


def test_the_52_week_range_keeps_its_labels_inside_its_cell():
    """The range bar under the price ends where its labels need it to: LLY's 1,292.66 high
    ran past the cell's right edge, and a four-figure low would have met "52 wk"."""
    for lo, hi, price in ((153.41, 212.71, 156.53), (783.85, 1292.66, 1143.12),
                          (1001.0, 1999.99, 1500.0)):
        svg = UC.range_bar(price, lo, hi)
        boxes = []
        for x, anchor, s in re.findall(r'<text x="([\d.]+)"[^>]*?( text-anchor="end")?'
                                       r' [^>]*>([^<]*)</text>', svg):
            wd = UC.lab_w(s, 9.5, True) if s[0].isdigit() else UC.lab_w(s, 9)
            x0 = float(x) - wd if anchor else float(x)
            boxes.append((x0, x0 + wd))
        assert all(0 <= a and b <= 196 for a, b in boxes), boxes
        boxes.sort()
        assert all(b <= c for (_a, b), (c, _d) in zip(boxes, boxes[1:])), boxes


def test_the_kinds_keep_off_the_colours_of_up_and_down():
    """Green and red mean up and down, and cheap and expensive; no kind of news is drawn
    in either."""
    for colours in (UC.KIND_COLOUR, UC.GRID_COLOUR):
        assert not {"var(--up)", "var(--down)"} & set(colours.values())


def test_every_company_mark_in_the_frame_opens_it(payload):
    """Board rows, ribbon tiles and story tickers carry data-ticker, each inside a part
    that names itself for the dialog's "opened from"."""
    front = UC.front_html(payload)
    marks = set(re.findall(r'data-ticker="([A-Z]+)"', front))
    assert marks == set(payload["companies"])
    for part in ("the news", "the board", "the ribbon"):
        assert f'data-from="{part}"' in front
    idx = (FRONTEND / "components" / "uvboard" / "index.html").read_text()
    assert 'hit.closest("[data-from]")' in idx


def test_the_band_is_one_height_with_taller_ranked_rows():
    """The news column and the board are drawn to one height: eighteen 17px board rows and
    their heads against two columns of five 66px ranked rows and their head, which leaves
    room under them for the FDA row."""
    css = UNIVERSE_CSS.read_text()
    assert re.search(r"--uw-row: 17px;", css)
    assert re.search(r"\.uw-it \{[^}]*height: 66px;", css)
    assert UC.RANK_ROWS == 5


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


BIG_PHARMA = {"ABBV", "AMGN", "AZN", "BAYN", "BIIB", "BMY", "GILD", "GSK", "JNJ",
            "LLY", "MRK", "NVO", "NVS", "PFE", "REGN", "ROG", "SNY", "VRTX"}


def test_the_big_pharma_companies_take_the_redesign(switch):
    assert switch["_REDESIGN_TICKERS"] == BIG_PHARMA
    on = switch["_universe_redesigned"]
    for t in BIG_PHARMA:
        assert on(t, "Overview")
    assert not on("AZN", "Markets") and not on("AZN", "Policy")
    for t in ("CRSP", "ABEO", "ADAPY"):
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
    # The control row and the group's index are page markdown; the band is in the frame.
    md = _universe_markdown("AZN")
    assert 'class="uv uw-idx"' in md and "Headlines this week" not in md


@needs_api
def test_live_app_another_company_keeps_todays_overview():
    md = _universe_markdown("CRSP")
    assert "uw-idx" not in md and "Headlines this week" in md


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
    for needle in ('class="uw-kick0"', 'class="uv-lead"', 'class="uv-status"',
                   'class="uv uw-idx"'):
        assert needle in md, needle
    assert not test.tabs
    assert "over a year" in md
    test.button_group(key="uv_window").set_value("3 months").run()
    assert not test.exception
    md = _md(test)
    assert "over three months" in md


def test_page_without_the_component_falls_back_to_pills():
    test = _page("universe_page._uvboard = None")
    md = _md(test)
    assert 'class="uw-band"' in md and 'class="uw-rib"' in md      # the band, drawn inline
    pills = test.button_group(key="uv_pick")
    labels = [getattr(o, "content", o) for o in pills.options]
    assert sorted(labels) == sorted(json.loads(FIXTURE.read_text())["companies"])


def test_page_with_the_focal_company_stripped_still_draws():
    tweak = ("import copy, importlib, pathlib\n"
             f"sys.path.insert(0, {str(pathlib.Path(__file__).parent)!r})\n"
             "import test_universe_tab_ui as T\n"
             "payload = T._stripped(payload)")
    md = _md(_page(tweak))
    assert 'class="uv uw-idx"' in md and UC.NO_DATA in md


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
    # On the tab the control row says it, so the partial read costs the page no line: the
    # count leads the status in the flag colour and the sentence is its hover.
    status = UC.status_line(q)
    assert _visible(status.split('<span class="uv-nt-c">')[0]) == f"{n} of {len(q['companies'])} valued ▾"
    assert UC.esc(UC.incomplete_text(q)) in status
    assert "uv-pt" not in UC.status_line(payload) and "valued" not in UC.status_line(payload)
    assert "incomplete_note" not in (FRONTEND / "universe_page.py").read_text()
    assert re.search(r"\.uv-nt\.uv-pt \{[^}]*color: var\(--flag\)", UNIVERSE_CSS.read_text())


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


def test_a_ranked_row_says_its_item_in_a_few_words_and_its_card_keeps_the_headline(payload):
    want = {"deal": None, "readout": "Phase 3 result", "slips": "trial dates slipped",
            "notice": " data at ", "earnings": "results call"}
    rk = UC.ranked_html(payload)
    for it in payload["week_items"]:
        b = UC.brief(it)
        assert b and len(b.split()) <= 5, (it["kind"], b)
        _house_style(b)
        if want.get(it["kind"]):
            assert want[it["kind"]] in b, (it["kind"], b)
    deal = next(i for i in payload["week_items"] if i["kind"] == "deal" and "Summit" in (i.get("head") or ""))
    assert UC.brief(deal) == "Summit stake and collaboration"
    row = rk.split(f'<span class="n">{deal["rank"]}</span>')[1].split('<div class="uw-it')[0]
    assert '<div class="h">Summit stake and collaboration</div>' in row
    assert html.escape(deal["head"])[:60] in row  # the full headline is in its card


def test_the_fda_row_marks_every_approval_of_the_year_and_names_never_overlap(payload):
    out = UC.fda_row_html(payload)
    today = dt.date.fromisoformat(payload["today"])
    year = [a for a in payload["lanes"]["approvals"]
            if f"{today.year}-01-01" <= a["date"] <= payload["today"]]
    marks = re.findall(r'<span class="fm (nda|bla|anda)" data-ticker="([A-Z]+)"', out)
    assert len(marks) == len(year) and len(year) > 0
    assert {m[1] for m in marks} <= set(payload["tickers"])
    assert f"{len(year)} this year" in out and f"FDA approvals {today.year}" in out
    # A generic carries no name on the line; every name sits on one of two tiers and
    # none overlaps another on its tier (by the row's own spacing estimate).
    generics = {_a["label"] for _a in year if _a["application_type"] == "ANDA"}
    for tier in ("t0", "t1"):
        spans = re.findall(r'<span class="fl ' + tier + r'[^"]*" data-ticker="[A-Z]+" '
                           r'style="left:([\d.]+)%">([^<]*) <i>([A-Z]+)</i>', out)
        ends = []
        for left, name, tk in spans:
            assert html.unescape(name) not in generics
            w = len(f"{html.unescape(name)} {tk}") * UC.FDA_LABEL_PX / UC.FDA_ROW_PX * 100
            ends.append((float(left) - w / 2, float(left) + w / 2))
        for (a0, a1), (b0, _b1) in zip(ends, ends[1:]):
            assert b0 > a1, tier
    ahead = [e for e in payload["lanes"]["events"] if e.get("regulatory") and not e.get("month")
             and payload["today"] < e["date"] <= f"{today.year}-12-31"]
    assert out.count('class="fm ahead"') == len(ahead)
    assert out.count('class="mo"') == 12 and 'class="today"' in out
    assert '<section class="uw-fda"' in UC.front_html(payload)
    _house_style(_visible(out))
