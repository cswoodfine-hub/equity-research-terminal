"""The Comps tab's Disease areas view (frontend/areas_view.py, the builders; the
``_disease_areas`` render and the tab in streamlit_app.py; ``area_map`` in charts.py).

The builders are pure functions of ``GET /areas`` and ``GET /areas/{slug}``, saved from
the 2026-10-07 book as ``fixtures/disease_areas/``. They are run on those and on copies
with figures taken away: every block draws, a missing figure prints "no free data" or
says why it is absent, and nothing missing is drawn as a zero. Then the house style of
every string a reader sees, the card text limits, and the wiring.
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
BUILDERS = FRONTEND / "areas_view.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "disease_areas"

if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import areas_view as AV  # noqa: E402
from components import charts as CH  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"


def _load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(params=["oncology", "metabolic"])
def page(request):
    return _load(request.param)


def _stripped(page):
    """The page with every figure a source can lack taken away."""
    p = copy.deepcopy(page)
    for r in p["companies"]:
        r["value"].update(usd_bn=None, share=None, basis="no marketed product here "
                          "carries a model value", top=[])
        r["pipeline"].update(usd_bn=None, top=[])
        r["durability"].update(share=None, revenue_usd_bn=None, at_risk_usd_bn=None,
                               products=[])
        r["clinical"].update(mean=None, drugs=[])
        r["readouts"].update(stake_usd_bn=None, priced=0, top=[])
        r["scores"] = {"value": None, "pipeline": r["scores"]["pipeline"],
                       "durability": None, "clinical": None}
    for k in ("value_usd_bn", "pipeline_usd_bn", "risked_usd_bn", "at_risk_usd_bn",
              "at_risk_share", "stake_usd_bn", "revenue_usd_bn"):
        p["totals"][k] = None
    return p


def _everything(page, ticker="AZN"):
    """Every string the view draws from one page."""
    rows = page["companies"]
    out = {
        "figures": AV.figures_html(AV.figure_cells(page, ticker)),
        "table": AV.table_html(rows, ticker, page["horizon_end"]),
        "method": AV.method_html(page["method"], AV.off_chart(rows)),
        "rests": AV.rests_on_html(rows, page["horizon_end"]),
        "cards": AV.cards_html(list(page["cards"]) + [AV.company_card(page, ticker)]),
        "chart": CH.area_map(AV.map_points(rows), 720, 480, highlight=ticker),
    }
    out["tips"] = " ".join(p["tip"] for p in AV.map_points(rows))
    return out


def _visible(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


# --- the builders on the saved pages ---------------------------------------------------
def test_every_block_draws_on_the_saved_pages(page):
    out = _everything(page)
    for key, markup in out.items():
        assert markup, key
    rows = page["companies"]
    thin = any(not r["ranked"] for r in rows)
    # The head, a row a company, and one rule above those with too little on file.
    assert out["table"].count("<tr") == len(rows) + 1 + (1 if thin else 0)
    assert out["cards"].count('<div class="vc ') == 5


def test_the_table_lists_the_ranked_then_those_with_too_little_on_file(page):
    rows = page["companies"]
    ranks = [r["rank"] for r in rows]
    n = sum(1 for r in rows if r["ranked"])
    assert ranks[:n] == list(range(1, n + 1)) and all(x is None for x in ranks[n:])
    table = AV.table_html(rows, "AZN", page["horizon_end"], page["weights"])
    if n < len(rows):
        rule = table.index("Too little on file to rank")
        first_thin = rows[n]["ticker"]
        assert rule < table.index(f'<span class="m">{first_thin}</span>')
        assert table.count(">too little on file</td>") == len(rows) - n


def test_the_table_head_and_the_method_state_the_weights(page):
    head = AV.table_html(page["companies"], "AZN", page["horizon_end"],
                         page["weights"]).split("</thead>")[0]
    for label, w in (("value today", "35%"), ("pipeline", "25%"), ("durability", "15%"),
                     ("clinical", "25%")):
        assert re.search(rf">{label}<span class=\"ar-w\">{w}</span>", head), label
    how = _visible(AV.method_html(page["method"], AV.off_chart(page["companies"])))
    assert "value today 35%, pipeline 25%, clinical quality 25% and durability 15%" in how
    assert "at least 3 of the 4 pillars" in how


def test_the_selected_companys_areas_come_first_most_assets_first():
    index = _load("index")
    opts = AV.area_options(index, "AZN")
    held = {a["slug"]: (a.get("assets_by_ticker") or {}).get("AZN", 0) for a in index}
    mine = [s for s in opts if held[s]]
    assert opts[:len(mine)] == mine
    assert [held[s] for s in mine] == sorted((held[s] for s in mine), reverse=True)
    assert opts[0] == "oncology"
    assert sorted(opts) == sorted(a["slug"] for a in index)


def test_the_chart_places_every_company_with_both_scores_and_labels_each(page):
    rows = page["companies"]
    points = AV.map_points(rows)
    on = [r for r in rows if r["ranked"] and r["scores"]["value"] is not None
          and r["scores"]["pipeline"] is not None]
    assert len(points) == len(on)
    svg = CH.area_map(points, 720, 480, highlight="AZN")
    assert svg.count("<circle") >= len(points)
    for p in points:
        assert f">{p['ticker']}<" in svg
    off = AV.off_chart(rows)
    assert len(off) == len(rows) - len(on)


def test_house_style_in_everything_a_reader_sees(page):
    for p in (page, _stripped(page)):
        for key, markup in _everything(p).items():
            text = _visible(markup) + " " + " ".join(
                html.unescape(t) for t in re.findall(r'title="([^"]*)"', markup))
            assert EM_DASH not in text, key
            for word in BANNED:
                assert not re.search(rf"\b{word}\b", text, re.I), (key, word)


def test_a_missing_figure_prints_no_free_data_and_never_a_zero(page):
    p = _stripped(page)
    out = _everything(p)
    table = _visible(out["table"])
    assert "no free data" in table
    assert "$0.00bn" not in table and "$0.0bn" not in table
    figures = _visible(out["figures"])
    assert "no free data" in figures and "$0" not in figures
    rests = _visible(out["rests"])
    assert "no free data" in rests and "$0" not in rests
    for r in p["companies"]:
        assert f'{r["ticker"]}' in table


def test_nothing_marketed_is_said_not_printed_as_zero(page):
    p = copy.deepcopy(page)
    r = p["companies"][0]
    r["value"].update(usd_bn=0.0, basis="none marketed", share=None)
    out = _everything(p, r["ticker"])
    assert "none marketed" in _visible(out["table"])
    assert "nothing marketed" in _visible(out["rests"]).lower()
    card = AV.company_card(p, r["ticker"])
    assert "Nothing marketed" in card["detail"]
    assert "$0" not in card["detail"]


def test_the_card_text_fits_its_box(page):
    """Title on one line, headline in two and detail in three at the narrowest row."""
    cards = list(page["cards"]) + [AV.company_card(page, r["ticker"])
                                   for r in page["companies"]]
    cards.append(AV.company_card(page, "ZZZ", "Absent Pharma Inc."))
    for c in cards:
        assert len(c["title"]) <= AV.CARD_TITLE_MAX, c["title"]
        assert len(c["headline"]) <= AV.CARD_HEAD_MAX, c["headline"]
        assert len(c.get("detail") or "") <= AV.CARD_DETAIL_MAX, c["detail"]
    # The whole of each card is its hover.
    markup = AV.card_html(cards[0])
    assert html.escape(cards[0]["headline"], quote=True) in markup.split('title="')[1]


def test_the_company_card_of_a_company_with_too_little_on_file():
    p = _load("oncology")
    thin = next(r for r in p["companies"] if not r["ranked"])
    c = AV.company_card(p, thin["ticker"])
    assert c["headline"] == f'Too little on file to rank: {thin["pillars"]} of 4 pillars'
    assert len(c["headline"]) <= AV.CARD_HEAD_MAX


def test_no_card_picks_a_company_with_too_little_on_file(page):
    thin = {AV.short_name(r["name"]) for r in page["companies"] if not r["ranked"]}
    for c in page["cards"]:
        assert not any(c["headline"].startswith(t) for t in thin), c


def test_the_company_card_names_a_company_with_nothing_here():
    c = AV.company_card(_load("oncology"), "ZZZ", "Absent Pharma Inc.")
    assert c["title"] == "Absent Pharma's position"
    assert "nothing placed" in c["headline"]
    c = AV.company_card(_load("oncology"), "AZN")
    assert c["title"] == "AstraZeneca's position"
    assert c["headline"].startswith("Ranks ")


def test_the_figures_name_the_area_basis():
    p = _load("oncology")
    cells = dict((k, (v, sub)) for k, v, sub in AV.figure_cells(p, "AZN"))
    assert cells["companies"] == (str(p["totals"]["companies"]), "AZN in it")
    assert f"loses exclusivity by {p['horizon_end']}" in cells
    assert cells["risked value"][0].startswith("$")


def test_the_builders_touch_no_streamlit_network_or_clock():
    tree = ast.parse(BUILDERS.read_text(), feature_version=(3, 9))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names <= {"__future__", "html", "re"}, names
    for call in ("date.today(", "datetime.now(", "time.time(", "open("):
        assert call not in BUILDERS.read_text(), call


# --- the wiring ------------------------------------------------------------------------
def test_disease_areas_sits_between_indications_and_pipelines_on_pharma_only():
    src = APP.read_text()
    assert ('_views = ["Companies"] + (["Indications", "Disease areas"]\n'
            '                                  if _engine == "pharma" else []) + ["Pipelines"]'
            in src)
    assert "_disease_areas(api_base, ticker)" in src
    tree = ast.parse(src, feature_version=(3, 9))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
              and n.name == "_disease_areas")
    body = ast.get_source_segment(src, fn)
    for key in ('key="area_head"', 'key="area_sc_head"', 'key="area_map"'):
        assert key in body
    assert '"/areas/{pick}"' in body or "f\"/areas/{pick}\"" in body


def test_the_theme_sizes_the_view_to_the_screen():
    css = (FRONTEND / "theme.py").read_text()
    assert "--ar-h: clamp(250px, calc(100vh - 402px), 660px)" in css
    assert ".st-key-area_map .land-wrap {{ height: var(--ar-h); overflow: auto; }}" in css


def test_the_route_is_warmed_after_the_reads_it_embeds():
    sys.path.insert(0, str(ROOT / "backend"))
    import response_cache
    assert "/areas" in response_cache.GLOBAL_READS
    reads = response_cache._area_reads()
    assert "/areas/oncology" in reads and "/areas/immunology-and-inflammation" in reads
    assert "/areas/healthy-volunteers" not in reads
