"""The redesigned Catalysts tab (frontend/catalysts_view.py, catalysts_page.py, the catnav
component and the switch in streamlit_app.py).

Four layers.

The builders are pure functions of the payload of ``GET /companies/{t}/catalysts/view``,
saved from the 2026-10-06 book as ``fixtures/catalysts/view_AZN.json``. They are run on it
and on copies with figures taken away: every block draws, a missing figure prints "no free
data" or is left off, and nothing missing is drawn as a zero. A company with no priced
stake still gets a page.

The house style of every string a reader sees. Registry titles are quoted verbatim in
hovers only, so <title> elements and title= attributes are left out of the check.

The switch: read out of the Streamlit script by name (it runs the whole app on import), so
a company outside ``_REDESIGN_TICKERS`` provably takes today's tab, called as before.

Then the page itself in AppTest on the saved payload with the read replaced, the card's
facts drawn by the Forecast tab's own builders (taken out of the script by name), and the
app against an API, skipped when none is up, like the other tab tests.
"""

from __future__ import annotations

import ast
import copy
import html
import json
import math
import os
import pathlib
import re
import sys
import types
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "streamlit_app.py"
BUILDERS = FRONTEND / "catalysts_view.py"
CSS = FRONTEND / "assets" / "catalysts.css"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "catalysts" / "view_AZN.json"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import catalysts_view as CV  # noqa: E402

BASE = os.getenv("ER_API_BASE", "http://localhost:8000")
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
HEX = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


@pytest.fixture(scope="module")
def payload():
    return json.loads(FIXTURE.read_text())


def _blocks(p, gid=None):
    """Every block the page draws, by name, with ``gid`` the selected gate."""
    gid = CV.selected_gate(p, gid)
    return {"header": CV.header_html(p), "frame": CV.frame_html(p, gid),
            "card": CV.card_html(p, gid), "next": CV.next_html(p), "risks": CV.risks_html(p),
            "unpriced": CV.unpriced_html(p), "dialog": CV.dialog_html(p, gid),
            "notes": CV.notes_text(p), "legend": CV.timeline_legend()}


def _visible(markup: str) -> str:
    """What a reader sees without hovering: hovers (registry titles, verbatim) and tags
    gone."""
    markup = re.sub(r"<title>.*?</title>", " ", markup, flags=re.S)
    markup = re.sub(r'\stitle="[^"]*"', " ", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def _house_style(text: str) -> None:
    assert EM_DASH not in text, text[:200]
    low = text.lower()
    for word in BANNED:
        assert not re.search(rf"\b{word}", low), (word, text[:200])


def _stripped(p):
    """The payload with the figures a source can fail to give taken away."""
    q = copy.deepcopy(p)
    q["close"] = None
    for g in q["gates"]:
        g["success"] = g["swing"] = None
        g["development"] = None
        g["launch"] = {}
        g["trial"] = None
        g["held"] = None
        g["held_studies"] = g["open_studies"] = []
        g["move"] = None
        g["model"] = {}
    for c in q["cliffs"]:
        c["model_per_share"] = c["share_of_revenue"] = None
    for e in q["events"]:
        e["trial"] = None
        e["line_value"] = None
    q["crowding"] = None
    return q


def _no_stakes(p):
    """A company with no priced next gate: every event unpriced, no gate served."""
    q = copy.deepcopy(p)
    q["gates"] = []
    for e in q["events"]:
        e["priced"], e["per_share"], e["gate_asset"] = False, None, None
        e["reason"] = e.get("reason") or "no_gate"
    q["slips"] = [dict(s, gate_asset=None, gate_swing=None) for s in q["slips"]]
    return q


def _empty(p):
    q = {k: ([] if isinstance(v, list) else {} if isinstance(v, dict) else v)
         for k, v in p.items()}
    q["close"] = None
    return q


# ------------------------------------------------------------------------ the builders
def test_the_builders_module_touches_no_streamlit_network_or_clock():
    tree = ast.parse(BUILDERS.read_text(), feature_version=(3, 9))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {"__future__", "datetime", "html", "math", "re"}, names
    source = BUILDERS.read_text()
    for call in ("date.today(", "datetime.now(", "time.time(", "open("):
        assert call not in source, call


def test_builders_are_pure_and_repeatable(payload):
    before = copy.deepcopy(payload)
    a, b = _blocks(payload), _blocks(payload)
    assert a == b and payload == before


def test_markdown_safe(payload):
    """No blank line inside a block (markdown would end the HTML there)."""
    for name, markup in _blocks(payload).items():
        assert "\n\n" not in markup, name


@pytest.mark.parametrize("variant", ["fixture", "stripped", "no_stakes", "empty"])
def test_house_style_of_every_visible_string(payload, variant):
    p = {"fixture": payload, "stripped": _stripped(payload),
         "no_stakes": _no_stakes(payload), "empty": _empty(payload)}[variant]
    gids = [g["asset_id"] for g in p.get("gates") or []] or [None]
    for gid in gids:
        for name, markup in _blocks(p, gid).items():
            text = _visible(markup)
            _house_style(text)
            assert "None" not in re.findall(r"\bNone\b", text), (variant, name)
            assert "nan" not in re.findall(r"\bnan\b", text), (variant, name)


def test_section_labels_are_sentence_case(payload):
    markup = "".join(_blocks(payload).values())
    labels = re.findall(r'class="sec-label">([^<]+)<', markup)
    assert {"Next 24 months, by therapy area", "What can move the share", "Next up",
            "Risk register"} <= set(labels), labels
    for label in labels:
        assert label[0].isupper() or label[0].isdigit(), label
        for word in label.split()[1:]:
            assert not word[:1].isupper() or word in ("AZN",), label


def test_the_lead_reads_its_gates(payload):
    t = CV.totals(payload)
    swing = sum(g["success"] - g["failure"] for g in payload["gates"])
    assert t["swing"] == pytest.approx(swing)
    assert t["n"] == len(payload["gates"])
    lead = _visible(CV.lead_sentence(payload))
    assert CV.usd(t["swing"]) in lead and CV.usd(t["swing12"]) in lead
    top = sorted(payload["gates"], key=lambda g: -(g["success"] - g["failure"]))[:2]
    pair = sum(g["success"] - g["failure"] for g in top)
    assert CV.usd(pair) in lead


def test_the_header_figures_are_the_sums_of_the_gates(payload):
    head = _visible(CV.header_html(payload))
    now = sum(g["now"] for g in payload["gates"])
    success = sum(g["success"] for g in payload["gates"])
    costs = [((g.get("development") or {}).get("gate") or {}).get("cost_per_share")
             for g in payload["gates"] if (g.get("development") or {}).get("ok")]
    assert CV.usd(now) in head and CV.usd(success) in head
    assert CV.usd(sum(c for c in costs if c is not None)) in head
    assert f"{sum(1 for c in costs if c is not None)} of {len(payload['gates'])} costed" in head


def test_null_is_never_drawn_as_zero(payload):
    p = _stripped(payload)
    blocks = _blocks(p)
    for name in ("header", "frame", "card", "dialog"):
        assert CV.NO_DATA in _visible(blocks[name]), name
    # No gate with no pass leg draws a pass bar, and none prints a zero for it.
    rng = CV.range_svg(p, "near")
    assert 'class="seg-up"' not in rng and 'class="seg-dn"' not in rng
    assert "$0.00" not in _visible(blocks["card"])
    head = _visible(blocks["header"])
    assert "of price" not in head and "against the" not in head
    # Exclusivity losses with no model value hang no bar.
    tl = CV.timeline_svg(p)
    assert not re.search(r'class="(sm|bio|unk)[^"]*"[^>]*height="0\.0"', tl)


def test_a_nil_leg_reads_nil(payload):
    gid = CV.default_gate(payload)
    r = next(g for g in CV.gate_rows(payload) if g["asset_id"] == gid)
    assert r["failure"] == 0.0
    fork = _visible(CV.fork_svg(r))
    assert "nil" in fork and "$0.00" not in fork
    assert "$0.00" not in _visible(CV.dialog_html(payload, gid))


def test_the_odds_chain_multiplies_every_step_from_the_gate(payload):
    """The dialog's chance chain read only "Phase 3 to NDA/BLA" out of a Phase 2 gate's
    basis and multiplied it by the PoS after a pass, printing 39.8% for AZD6793 against a
    PoS of 13.5%. Every step is printed now and the product is of the rates printed."""
    rows = {r["name"]: r for r in CV.gate_rows(payload)}
    p2 = rows["AZD6793"]
    assert [w for w, _r in CV.odds_steps(p2["basis"])] == [
        "pass Phase 2", "pass Phase 3", "filing to approval"]
    chain = _visible(CV._odds_chain(p2))
    assert chain.startswith("21.9% pass Phase 2 × 64.5% pass Phase 3 × 95.6% filing to "
                            "approval = 13.5% published"), chain
    for r in rows.values():
        steps = CV.odds_steps(r["basis"])
        text = _visible(CV._odds_chain(r))
        if len(steps) < 2:
            assert "=" not in text
            continue
        printed = [float(x) / 100 for x in re.findall(r"([\d.]+)% (?:pass|filing)", text)]
        product = float(re.search(r"= ([\d.]+)% published", text).group(1)) / 100
        assert abs(math.prod(round(x, 3) for x in printed) - product) < 0.0006, r["name"]
        if (r.get("evidence") or {}).get("p_gate") == "published":
            assert abs(product - r["pos_now"]) < 0.002, r["name"]


def test_the_standard_review_is_printed_with_its_own_study(payload):
    """The launch floor's standard review belongs to the study the floor governs from.
    Rilvegostomig's gate reads out Jan 2030 but its floor dates from an earlier Phase 3, so
    the card printed "earliest Sep 2030 · standard Jan 2030", a standard decision before
    the earliest one. It is now printed with the floor's own study, in the dialog."""
    rows = {r["name"]: r for r in CV.gate_rows(payload)}
    r = rows["Rilvegostomig"]
    assert r["launch"]["gate"]["same_as_governing"] is False
    ap = CV.approval_dates(r)
    assert ap["earliest"] == r["launch"]["gate"]["decision_date"] and ap["standard"] is None
    assert ap["floor"] == r["launch"]["decision_date"]
    assert ap["floor_standard"] == r["launch"]["standard"]["decision_date"]
    strip = _visible(CV.dates_svg(r, CV._today(payload)))
    assert "earliest Sep 2030" in strip and "standard" not in strip
    dialog = _visible(CV.dialog_html(payload, r["asset_id"]))
    assert "Standard review" not in dialog
    assert ("Asset's floor 3 Sep 2029 from NCT06109779, the earliest basis on file · "
            "standard review 3 Jan 2030") in dialog
    # where the gate is the floor's own study, the standard sits beside the earliest
    e = rows["Elecoglipron"]
    assert e["launch"]["gate"]["same_as_governing"] is True
    assert "earliest Dec 2028 · standard Apr 2029" in _visible(CV.dates_svg(e, CV._today(payload)))
    for row in rows.values():
        ap = CV.approval_dates(row)
        if ap["earliest"] and ap["standard"]:
            assert ap["standard"] > ap["earliest"], row["name"]


def test_a_colour_means_one_thing_across_the_tab(payload):
    """Orange and purple are small molecule and biologic on the timeline's exclusivity lane;
    the risk register drew every LOE bar orange and the crowding leader purple, and the
    unpriced reasons in the phase colours. Bars now stack by modality, the leader and the
    reasons are neutral, and only the FDA reason keeps the FDA colour."""
    loe = CV.loe_svg(payload)
    by = payload["loe_by_year"]
    for year, v in by.items():
        if CV._today(payload).year <= int(year) < CV._today(payload).year + 15:
            want = [CV._modality_class(q[2]) for q in v["products"] if q[1] > 0]
            got = re.findall(r'class="(sm|bio|unk)(?: dim| past)?"',
                             loe[loe.index(f"<title>{year}:"):].split("</g>")[0])
            assert got == want, year
    css = CSS.read_text()
    reasons = dict(re.findall(r"\.cx \.(u\d) \{ background: ([^;]+);", css))
    assert reasons["u3"] == "var(--phase-filed)"
    assert not any("phase" in v for k, v in reasons.items() if k != "u3")
    assert "purple-book" not in re.search(r"\.cr \.cr-lead \{[^}]*\}", css).group(0)
    assert "purple-book" not in re.search(r"\.cx-risk\.k-pool \{[^}]*\}", css).group(0)


def test_a_company_with_no_priced_stakes_still_draws(payload):
    for p in (_no_stakes(payload), _empty(payload)):
        blocks = _blocks(p)
        assert "No pipeline line of" in _visible(blocks["header"])
        assert "no gate to select" in _visible(blocks["card"])
        assert "This gate is not on the book" in _visible(blocks["dialog"])
        assert "data-gate" not in blocks["frame"]
        assert CV.selected_gate(p, 123) is None
    events = _visible(CV.frame_html(_no_stakes(payload)))
    assert "Next 24 months, by therapy area" in events and "No pipeline line" in events


def test_every_gate_is_a_click_target_on_both_charts(payload):
    frame = CV.frame_html(payload, CV.default_gate(payload))
    rng = frame[frame.index('class="cx-rg-wrap"'):]
    tl = frame[:frame.index('class="cx-rg-wrap"')]
    ids = {str(g["asset_id"]) for g in payload["gates"]}
    near = {r["asset_id"] for r in CV.gate_rows(payload) if r["view"] == "near"}
    assert len(near) <= CV.VIEW_ROWS          # every near gate is drawn, none folded
    assert set(re.findall(r'class="gl-row[^"]*" data-gate="(\d+)"', rng)) == ids
    dated = {str(r["asset_id"]) for r in CV.gate_rows(payload) if r["d"] or r["fl"]}
    assert dated <= set(re.findall(r'data-gate="(\d+)"', tl))


_LABEL_SIZE = {"lbl": (10, False, True), "lvm": (9, True, False), "sl": (9, True, True),
               "lm": (9, False, False)}


def _gate_marks_under_names(svg: str) -> list:
    """Gate marks drawn before the names (so under them) whose circle reaches into a
    name's box, the box worked out as place_label works it out."""
    boxes = []
    for m in re.finditer(r'<text class="(lbl|lvm|sl|lm)" x="([\d.]+)" y="([\d.]+)" '
                         r'text-anchor="(\w+)">([^<]*)</text>', svg):
        size, mono, bold = _LABEL_SIZE[m.group(1)]
        w = CV._tw(html.unescape(m.group(5)), size, mono, bold)
        x, y = float(m.group(2)), float(m.group(3))
        x0 = {"start": x, "end": x - w, "middle": x - w / 2}[m.group(4)]
        boxes.append((x0, y - 8.2, x0 + w, y + 2.3, m.start()))
    out = []
    for m in re.finditer(r'<a data-gate="(\d+)"><title>[^<]*</title><circle class="(pf|due)[^"]*" '
                         r'cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', svg):
        x, y, r = float(m.group(3)), float(m.group(4)), float(m.group(5))
        for x0, y0, x1, y1, at in boxes:
            if at > m.start() and CV._circle_in_rect(x, y, r, (x0, y0, x1, y1), pad=-0.5):
                out.append(m.group(1))
    return out


def test_no_gate_sits_hidden_under_a_name(payload):
    """A small gate the lane has no clear room for was left under a name and could not be
    clicked (AZD5335 and Surovatamig on the 6 Oct book): the name moves, or the gate is
    drawn over it, or a name after the 24 months gives way."""
    for gid in (None, *(g["asset_id"] for g in payload["gates"][:6])):
        svg = CV.timeline_svg(payload, CV.selected_gate(payload, gid))
        assert _gate_marks_under_names(svg) == []
    css = CSS.read_text()
    assert re.search(r"\.cx-tl text \{[^}]*pointer-events: none", css)


def test_the_selected_gate_is_marked_on_both_charts(payload):
    gid = CV.default_gate(payload)
    frame = CV.frame_html(payload, gid)
    assert frame.count('class="sel"') == 1
    assert re.search(rf'class="gl-row on" data-gate="{gid}"', frame)
    other = next(g["asset_id"] for g in payload["gates"] if g["asset_id"] != gid)
    assert CV.selected_gate(payload, str(other)) == other
    assert CV.selected_gate(payload, "not a gate") == gid


def test_the_card_names_the_gate_its_legs_and_its_dates(payload):
    gid = CV.default_gate(payload)
    r = next(g for g in CV.gate_rows(payload) if g["asset_id"] == gid)
    card = _visible(CV.card_html(payload, gid, facts_html="<table>facts</table>",
                                 lines=["a line"]))
    assert r["name"] in card and CV.usd(r["now"]) in card and CV.usd(r["success"]) in card
    assert "facts" in card and "a line" in card
    if r.get("move"):
        assert f"{abs(r['move']['days'])} days" in card


def test_resolve_text_is_the_rows_own_note(payload):
    for r in CV.gate_rows(payload):
        if r.get("stake"):
            assert CV.resolve_text(r) == r["stake"]["resolve_note"]
        else:
            assert CV.resolve_text(r).startswith("No catalyst row on file")


def test_catalysts_css_is_tokens_only_and_reaches_the_page_and_the_frame():
    css = CSS.read_text()
    assert not HEX.findall(css), "a hex colour in catalysts.css"
    assert "rgb(" not in css and "hsl(" not in css
    used = set(re.findall(r"var\(\s*(--[\w-]+)", re.sub(r"/\*.*?\*/", "", css, flags=re.S)))
    defined = set()
    for f in (FRONTEND / "assets" / "tokens.css", FRONTEND / "assets" / "research.css", CSS):
        defined |= set(re.findall(r"(--[\w-]+)\s*:", f.read_text()))
    assert not used - defined, used - defined
    assert "@media (max-width: 1179.98px)" in css and "@media (max-width: 899.98px)" in css
    import theme
    page = theme.css()
    assert css in page and page.index(theme._RESEARCH_CSS) < page.index(css)
    import catalysts_page
    assert css in catalysts_page._frame_css()


def test_the_svgs_read_colour_from_the_stylesheet_only(payload):
    markup = "".join(_blocks(payload).values())
    for attr in ("fill=", "stroke=", "color:", "background:"):
        assert not re.search(rf'{attr}\s*"?\s*(#|rgb|hsl)', markup), attr
    assert not HEX.findall(re.sub(r"#\d+ of \d+", "", re.sub(
        r'url\(#[\w-]+\)|id="[\w-]+"|href="[^"]*"', "", markup)))


# ------------------------------------------------------------------------- the switch
@pytest.fixture(scope="module")
def switch():
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "_catalysts_redesigned")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_REDESIGN_TICKERS"
                                                  for t in n.targets))]
    space: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return space


def test_only_azn_takes_the_redesign(switch):
    assert switch["_REDESIGN_TICKERS"] == {"AZN"}
    on = switch["_catalysts_redesigned"]
    assert on("AZN")
    for t in ("LLY", "NVO", "JNJ", "ROG", "BAYN", "CRSP"):
        assert not on(t)


def _tab_block():
    """The statement under ``with catalysts_tab:`` that picks the tab body."""
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    for node in ast.walk(tree):
        if (isinstance(node, ast.With) and len(node.items) == 1
                and getattr(node.items[0].context_expr, "id", "") == "catalysts_tab"):
            return node.body[0]
    raise AssertionError("no catalysts_tab block")


@pytest.mark.parametrize("ticker,drawn,want", [
    ("LLY", True, ["today"]), ("NVO", True, ["today"]),
    ("AZN", True, ["redesign"]), ("AZN", False, ["redesign", "today"])])
def test_every_other_company_keeps_todays_tab(switch, ticker, drawn, want):
    calls = []
    page = types.SimpleNamespace(
        render=lambda api_base, t, kit: calls.append("redesign") or drawn)
    space = {"ticker": ticker, "api_base": "http://api.invalid", "feed": [],
             "_catalysts_redesigned": switch["_catalysts_redesigned"],
             "catalysts_page": page, "_CATALYSTS_KIT": object(),
             "_catalysts_today": lambda a, t, f: calls.append("today")}
    block = _tab_block()
    exec(compile(ast.Module(body=[block], type_ignores=[]), str(APP), "exec"), space)
    assert calls == want


def test_todays_tab_is_drawn_as_before():
    source = APP.read_text()
    body = source[source.index("def _catalysts_today("):]
    body = body[:body.index("\n\n\n")]
    assert body.index("_drivers_and_risks(api_base, ticker, feed)") < body.index(
        'section("At stake", basis="rNPV swing, ranked by size")')
    for call in ('_stake_split(stakes["priced"])',
                 "_stake_row(stake_box, api_base, ticker, row)", "more at stake"):
        assert call in body, call
    assert "catalysts_page" not in body and "catalysts_view" not in body


def test_the_kit_hands_the_forecast_tabs_own_builders():
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    kit = next(n for n in tree.body if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_CATALYSTS_KIT")
    given = {k.arg: k.value.id for k in kit.value.keywords}
    assert given == {"gate_summary": "_gate_summary", "gate_rows": "_gate_rows",
                     "gate_table_html": "_gate_table_html", "gate_lines": "_gate_lines",
                     "gate_ladder_html": "_gate_ladder_html",
                     "gate_studies_html": "_gate_studies_html",
                     "stake_resolvable": "_stake_resolvable", "stake_row": "_stake_row",
                     "stake_resolved_note": "_stake_resolved_note"}


# ------------------------------------------------------------- the page, offline
KIT_NAMES = {"_stake_leg", "_stake_resolvable", "_stake_title", "_stake_row_html",
             "_stake_split", "_stake_resolved_note", "_stake_row", "_gate_attr", "_gate_ps",
             "_gate_mm", "_gate_pct", "_gate_when", "_gate_programme", "_gate_summary",
             "_gate_breakeven", "_gate_rows", "_gate_table_html", "_gate_steps",
             "_gate_head", "_gate_lines", "_gate_ladder_html", "_gate_studies_html",
             "_launch_flag", "_launch_flagged", "_ki_month", "_ki_day", "html_escape",
             "api_post_json", "api_get", "_STAKE_SHOWN", "_STAKE_TITLE_CHARS",
             "_GATE_EVIDENCE", "_GATE_PRICES", "_GATE_FAILED", "_GATE_LADDER",
             "_LAUNCH_TONES", "_KI_MONTHS"}


def kit():
    """The Forecast tab's builders, taken out of the script by name, as _CATALYSTS_KIT
    hands them to the page."""
    import streamlit as st
    tree = ast.parse(APP.read_text(), feature_version=(3, 9))
    keep = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in KIT_NAMES:
            keep.append(n)
        elif isinstance(n, ast.Assign) and any(getattr(t, "id", "") in KIT_NAMES
                                               for t in n.targets):
            keep.append(n)
    import urllib as _urllib
    space = {"st": st, "re": re, "json": json, "urllib": _urllib, "html": html}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(APP), "exec"), space)
    return types.SimpleNamespace(**{k.lstrip("_"): space[k] for k in (
        "_gate_summary", "_gate_rows", "_gate_table_html", "_gate_lines", "_gate_ladder_html",
        "_gate_studies_html", "_stake_resolvable", "_stake_row", "_stake_resolved_note")})


_PAGE = '''
import json, sys
sys.path.insert(0, {frontend!r})
sys.path.insert(0, {tests!r})
import streamlit as st
import catalysts_page
import test_catalysts_redesign_ui as T
payload = json.loads(open({fixture!r}).read())
{tweak}
catalysts_page.fetch = lambda api_base, ticker: payload
ok = catalysts_page.render("http://api.invalid", "AZN", T.kit())
st.caption(f"rendered {{ok}}")
'''


def _page(tweak=""):
    from streamlit.testing.v1 import AppTest
    test = AppTest.from_string(_PAGE.format(frontend=str(FRONTEND), fixture=str(FIXTURE),
                                            tests=str(pathlib.Path(__file__).parent),
                                            tweak=tweak), default_timeout=60)
    test.run()
    assert not test.exception, test.exception
    return test


def _md(test):
    return "".join(str(m.value) for m in test.markdown)


def _walk(block):
    for child in getattr(block, "children", {}).values():
        yield child
        yield from _walk(child)


def _popovers(test):
    return [b for b in _walk(test.main) if getattr(b, "type", "") == "popover"]


def test_page_draws_the_header_the_rail_and_the_card():
    test = _page()
    md = _md(test)
    assert 'class="cx cx-hd"' in md and 'class="cx cx-card' in md
    assert "Next up" in md and "Risk register" in md and "Why " in md
    assert [t.label for t in test.tabs] == ["Selected gate", "Next up", "Risk register",
                                            "Unpriced"]
    assert "rendered True" in [c.value for c in test.caption]
    assert any(b.label == "Full detail" for b in test.button)


def test_the_record_control_is_drawn_only_where_the_row_is_resolvable():
    test = _page()
    # Recording a derived outcome is switched off: the selected gate's row says why, and
    # no control is drawn.
    payload = json.loads(FIXTURE.read_text())
    gid = CV.default_gate(payload)
    note = next(g for g in payload["gates"] if g["asset_id"] == gid)["stake"]["resolve_note"]
    assert note in [c.value for c in test.caption]
    assert not _popovers(test)
    tweak = ("gid = catalysts_page.CV.default_gate(payload)\n"
             "for g in payload['gates']:\n"
             "    if g['asset_id'] == gid:\n"
             "        g['stake']['resolvable'] = True\n")
    test = _page(tweak)
    (pop,) = _popovers(test)
    assert pop.proto.popover.label == "Record the outcome"
    labels = [b.label for b in _walk(pop) if getattr(b, "type", "") == "button"]
    assert labels == ["met", "missed"]
    assert note not in [c.value for c in test.caption]


def test_full_detail_opens_the_dialog():
    test = _page()
    next(b for b in test.button if b.label == "Full detail").click().run()
    assert not test.exception, test.exception
    md = _md(test)
    assert 'class="cx cx-dlg"' in md and "Legs at the gate" in md
    assert "Cost to reach the gate" in md


def test_the_dialog_sends_the_record_to_the_cards_control():
    """The At stake row's first click arms and reruns the app, which closed the dialog, so
    an outcome could never be confirmed there. The dialog says what each outcome would do
    and points to the card's popover, which survives the rerun; met and missed are drawn
    once, in the popover."""
    tweak = ("gid = catalysts_page.CV.default_gate(payload)\n"
             "for g in payload['gates']:\n"
             "    if g['asset_id'] == gid:\n"
             "        g['stake']['resolvable'] = True\n")
    test = _page(tweak)
    next(b for b in test.button if b.label == "Full detail").click().run()
    assert not test.exception, test.exception
    md = _md(test)
    assert "If you record met" in md and "Record the outcome on the card" in md
    labels = [b.label for b in test.button]
    assert labels.count("met") == 1 and labels.count("missed") == 1
    # a row the back end does not mark resolvable shows its note in the dialog too
    test = _page()
    next(b for b in test.button if b.label == "Full detail").click().run()
    md = _md(test)
    assert "If you record met" not in md and "met" not in [b.label for b in test.button]


def test_page_without_the_component_draws_inline_and_picks_by_list():
    test = _page("catalysts_page._catnav = None")
    md = _md(test)
    assert 'class="cx-tl"' in md and 'class="cx-rg-svg"' in md
    payload = json.loads(FIXTURE.read_text())
    gid = CV.default_gate(payload)
    pick = test.selectbox(key="cx_pick_AZN")
    assert pick.value == gid
    other = next(g for g in payload["gates"] if g["asset_id"] != gid)
    pick.set_value(other["asset_id"]).run()
    assert not test.exception, test.exception
    card = re.search(r'class="cx-nm">([^<]+)<', _md(test)).group(1)
    assert card == other["name"]


def test_a_model_not_read_hands_back_to_todays_tab():
    test = _page("payload['model_ok'] = False")
    assert "rendered False" in [c.value for c in test.caption]
    assert 'class="cx' not in _md(test)


def test_a_company_with_no_priced_stakes_renders_the_page():
    tweak = "payload['gates'] = []\nfor e in payload['events']: e['priced'] = False"
    test = _page(tweak)
    md = _md(test)
    assert "rendered True" in [c.value for c in test.caption]
    assert "No pipeline line of" in md and "no gate to select" in md
    assert not any(b.label == "Full detail" for b in test.button)


def test_an_incomplete_read_is_drawn_once_and_never_held(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("catalysts_page_fetch_test",
                                                  FRONTEND / "catalysts_page.py")
    CP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CP)
    reads = []

    def read(api_base, ticker):
        reads.append(ticker)
        return {"complete": len(reads) > 1, "n": len(reads)}

    monkeypatch.setattr(CP, "_read", read)
    CP._fetch_complete.clear()
    try:
        assert CP.fetch("http://api.invalid", "AZN")["n"] == 1
        assert CP.fetch("http://api.invalid", "AZN")["n"] == 2
        assert CP.fetch("http://api.invalid", "AZN")["n"] == 2
        assert len(reads) == 2
    finally:
        CP._fetch_complete.clear()


# ------------------------------------------------------------------- the app, live API
def _api_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=3):
            return True
    except (urllib.error.URLError, OSError):
        return False


needs_api = pytest.mark.skipif(not _api_up(), reason=f"API not running at {BASE}")


def _catalysts_markdown(ticker):
    from streamlit.testing.v1 import AppTest
    test = AppTest.from_file(str(APP), default_timeout=600)
    test.query_params["ticker"] = ticker
    test.run()
    assert not test.exception, test.exception
    tab = next(t for t in test.tabs if t.label == "Catalysts")
    return "".join(str(n.value) for n in _walk(tab) if getattr(n, "type", "") == "markdown")


@needs_api
def test_live_app_azn_draws_the_redesign():
    md = _catalysts_markdown("AZN")
    assert 'class="cx cx-hd"' in md and "Drivers and risks" not in md


@needs_api
def test_live_app_another_company_keeps_todays_tab():
    md = _catalysts_markdown("LLY")
    assert 'class="cx' not in md
