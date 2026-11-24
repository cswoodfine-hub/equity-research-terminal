"""The Trading tab's board: the registry, the grid and the panels' markup.

Pure functions on plain dicts. No API, no database and no Streamlit is needed, so none of
this is ever skipped.
"""

import ast
import html
import pathlib
import re
import sys

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
BUILDERS = FRONTEND / "trading_view.py"
if str(FRONTEND) not in sys.path:
    sys.path.insert(0, str(FRONTEND))

import trading_view as TV  # noqa: E402

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
EM_DASH = "—"
# Words a research view does not use of a stock. The board reads; it does not recommend.
ADVICE = ("buy", "sell", "target price", "recommend", "overweight", "underweight")


def _visible(markup: str) -> str:
    markup = re.sub(r'\stitle="[^"]*"', " ", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


# The street's own count of its ratings, quoted as the source gives it beside its target.
# It is the street's word, not the board's, and the board says nothing of the kind itself.
STREET_COUNT = re.compile(r"\b\d+ buy, \d+ hold, \d+ sell\b")


def _house_style(text: str) -> None:
    assert EM_DASH not in text, text[:200]
    low = STREET_COUNT.sub(" ", text).lower()
    found = [w for w in BANNED + ADVICE if re.search(rf"\b{w}\b", low)]
    assert not found, (found, text[:200])


# ---------------------------------------------------------------------------- registry
def test_every_kind_of_panel_is_described_in_full():
    for panel in TV.PANELS:
        assert set(panel) == {"id", "title", "group", "wide", "cost", "private", "reads",
                              "about"}, panel["id"]
        assert panel["group"] in TV.GROUPS
        assert panel["cost"] in TV.COSTS
        assert isinstance(panel["wide"], bool) and isinstance(panel["private"], bool)
        assert panel["reads"] and all(read.startswith("/") for read in panel["reads"])
        assert panel["about"].endswith(".")


def test_no_two_kinds_share_an_id_or_a_title():
    assert len({p["id"] for p in TV.PANELS}) == len(TV.PANELS)
    assert len({p["title"] for p in TV.PANELS}) == len(TV.PANELS)
    assert all(re.fullmatch(r"[a-z][a-z_]*", p["id"]) for p in TV.PANELS)


def test_titles_and_groups_are_sentence_case():
    names = {"Ask", "FDA", "XBI"}
    for label in [p["title"] for p in TV.PANELS] + list(TV.GROUPS):
        assert label[0].isupper(), label
        rest = [w for w in label.split()[1:] if w[0].isupper() and w not in names]
        assert not rest, label


def test_the_default_board_is_the_price_the_fundamentals_and_the_ask_box_on_one_screen():
    panels = TV.default_layout()["panels"]
    assert [(p["panel"], p["x"], p["y"], p["w"], p["h"]) for p in panels] == [
        ("price", 0, 0, 8, 11), ("ask", 8, 0, 4, 17), ("fundamentals", 0, 11, 8, 6)]
    assert TV.area_px(17) <= 714                         # under the bar of a 900 px screen
    assert TV.BY_ID["price"]["cost"] == "live"


def test_the_default_board_is_made_of_kinds_that_exist():
    layout = TV.default_layout()
    assert sorted(p["panel"] for p in layout["panels"]) == sorted(TV.DEFAULT_PANELS)
    assert sorted(p["id"] for p in layout["panels"]) == ["p1", "p2", "p3"]
    assert all(p["panel"] in TV.BY_ID for p in layout["panels"])
    assert TV.normalise(layout) == (layout, [])


def test_the_picker_lists_every_kind_once_under_its_group():
    listed = [panel["id"] for _group, kinds in TV.picker_options() for panel in kinds]
    assert sorted(listed) == sorted(p["id"] for p in TV.PANELS)
    groups = [group for group, _kinds in TV.picker_options()]
    assert groups == [g for g in TV.GROUPS if g in groups]


# -------------------------------------------------------------------------------- the grid
import itertools  # noqa: E402
import random  # noqa: E402


def _cells(p):
    return {(x, y) for x in range(p["x"], p["x"] + p["w"]) for y in range(p["y"], p["y"] + p["h"])}


def _sound(panels):
    """The board's invariants: every panel on the grid at no less than its kind's
    minimum, no two sharing a cell, none with a hole under the panel above it."""
    seen = set()
    for p in panels:
        size = TV.size_of(p["panel"])
        assert 0 <= p["x"] and p["x"] + p["w"] <= TV.GRID_COLS, p
        assert p["w"] >= size["min_w"] and size["min_h"] <= p["h"] <= TV.MAX_H, p
        assert p["y"] >= 0
        cells = _cells(p)
        assert not cells & seen, ("overlap", p)
        seen |= cells
    for p in panels:                     # risen: the row above it is taken, or it is at the top
        if p["y"]:
            above = {(x, p["y"] - 1) for x in range(p["x"], p["x"] + p["w"])}
            assert above & seen, ("a hole above", p)
    assert panels == TV.reading_order(panels)


def _board(*specs):
    """A board from (kind, x, y, w, h) tuples."""
    return {"panels": [
        TV.item(kind, id=f"p{n}", x=x, y=y, w=w, h=h)
        for n, (kind, x, y, w, h) in enumerate(specs, start=1)]}


def _where(layout):
    return {p["id"]: (p["x"], p["y"], p["w"], p["h"]) for p in layout["panels"]}


def test_a_grid_row_and_its_gap_add_up_to_the_heights_a_panel_is_drawn_at():
    assert TV.area_px(1) == TV.ROW_PX and TV.area_px(9) == 9 * 24 + 8 * 16 == 344
    assert TV.body_px(9) == 344 - TV.HEAD_PX and TV.body_px(1) == 80


def test_the_grid_in_the_stylesheet_is_the_grid_the_model_counts():
    theme = (FRONTEND / "theme.py").read_text()
    assert f"grid-template-columns: repeat({TV.GRID_COLS}, minmax(0, 1fr))" in theme
    assert f"grid-auto-rows: {TV.ROW_PX}px" in theme and f"gap: {TV.GAP_PX}px" in theme


def test_a_panel_put_on_another_pushes_it_down_and_the_rest_rise():
    board = _board(("news", 0, 0, 6, 9), ("filings", 6, 0, 6, 9), ("results", 0, 9, 6, 9))
    moved = TV.place(board, "p3", 6, 0, 6, 9)       # dated ahead onto filings
    _sound(moved["panels"])
    assert _where(moved) == {"p1": (0, 0, 6, 9), "p3": (6, 0, 6, 9), "p2": (6, 9, 6, 9)}


def test_a_panel_dragged_down_into_empty_space_rises_to_the_first_free_row():
    board = _board(("news", 0, 0, 6, 9))
    assert _where(TV.place(board, "p1", 3, 20, 6, 9)) == {"p1": (3, 0, 6, 9)}


def test_a_corner_drag_sizes_a_panel_and_the_board_settles_round_it():
    board = _board(("news", 0, 0, 6, 9), ("filings", 6, 0, 6, 9), ("results", 0, 9, 12, 9))
    wider = TV.place(board, "p1", 0, 0, 9, 12)
    _sound(wider["panels"])
    assert _where(wider)["p1"] == (0, 0, 9, 12)
    assert _where(wider)["p2"][1] >= 12                 # pushed below the wider news
    assert _where(wider)["p3"][1] >= 12


def test_a_place_off_the_grid_or_below_a_minimum_is_brought_to_the_nearest_that_fits():
    board = _board(("news", 0, 0, 6, 9), ("price", 0, 9, 12, 13))
    assert _where(TV.place(board, "p1", 10, -4, 6, 9))["p1"] == (6, 0, 6, 9)
    assert _where(TV.place(board, "p1", 0, 0, 1, 1))["p1"] == (0, 0, 3, 5)
    assert _where(TV.place(board, "p1", 0, 0, 40, 400))["p1"] == (0, 0, 12, TV.MAX_H)
    assert _where(TV.place(board, "p2", 0, 0, 2, 2))["p2"][2:] == (4, 8)    # the price's own


def test_a_place_for_a_panel_not_on_the_board_or_not_in_whole_cells_changes_nothing():
    board = _board(("news", 0, 0, 6, 9))
    for bad in (("p9", 0, 0, 6, 9), ("p1", 0.5, 0, 6, 9), ("p1", "0", 0, 6, 9),
                ("p1", None, 0, 6, 9), ("p1", True, 0, 6, 9)):
        assert _where(TV.place(board, *bad)) == {"p1": (0, 0, 6, 9)}


def test_any_sequence_of_drags_leaves_a_sound_board():
    """Two hundred random places and sizes, each settled: the board stays on the grid
    with no panel overlapping another and no hole under any."""
    rng = random.Random(23)
    kinds = ["price", "news", "filings", "results", "trend", "results", "trend"]
    layout, _ = TV.normalise({"panels": [TV.item(k) for k in kinds]})
    for _n in range(200):
        p = rng.choice(layout["panels"])
        layout = TV.place(layout, p["id"], rng.randint(-2, 13), rng.randint(-2, 40),
                          rng.randint(1, 14), rng.randint(1, 35))
        _sound(layout["panels"])
    assert sorted(p["panel"] for p in layout["panels"]) == sorted(kinds)


def test_a_board_saved_before_the_grid_is_laid_out_as_it_was_drawn():
    layout, left_out = TV.normalise({"columns": 3, "ask": False, "panels": [
        {"panel": "price", "ticker": None, "wide": True}, {"panel": "news"},
        {"panel": "filings"}, {"panel": "results", "wide": False}]})
    assert left_out == [] and set(layout) == {"panels"}
    assert [(p["panel"], p["x"], p["y"], p["w"]) for p in layout["panels"]] == [
        ("price", 0, 0, 12, ), ("news", 0, 11, 4), ("filings", 4, 11, 4),
        ("results", 8, 11, 4)]
    assert [p["id"] for p in layout["panels"]] == ["p1", "p2", "p3", "p4"]
    _sound(layout["panels"])


def test_overlapping_places_in_a_saved_board_are_settled_and_ids_kept_or_given():
    layout, _ = TV.normalise({"panels": [
        {"panel": "news", "id": "p7", "x": 0, "y": 0, "w": 6, "h": 9},
        {"panel": "filings", "id": "p7", "x": 0, "y": 0, "w": 6, "h": 9},
        {"panel": "results", "id": "<b>", "x": 2, "y": 3, "w": 6, "h": 9}]})
    _sound(layout["panels"])
    assert sorted(p["id"] for p in layout["panels"]) == ["p7", "p8", "p9"]


def test_a_panel_with_no_place_in_a_board_that_has_places_goes_to_the_foot():
    layout, _ = TV.normalise({"panels": [
        {"panel": "news", "id": "p1", "x": 0, "y": 0, "w": 12, "h": 9}, {"panel": "filings"}]})
    assert _where(layout) == {"p1": (0, 0, 12, 9), "p2": (0, 9, 6, 9)}


# -------------------------------------------------------------------------- normalise
def test_a_kind_this_version_does_not_have_is_dropped_and_said():
    layout, left_out = TV.normalise({"panels": [
        {"panel": "news"}, {"panel": "crystal_ball"}, "nonsense", {"panel": "trend"},
        {"panel": ["news"]}, {"panel": {"a": 1}}, {"ticker": "LLY"}, None]})
    assert [p["panel"] for p in layout["panels"]] == ["news", "trend"]
    assert len(left_out) == 6 and "crystal_ball" in left_out[0]


def test_a_board_is_cut_at_its_limit_and_the_cut_is_said():
    many = {"panels": [{"panel": "news"}] * (TV.MAX_PANELS + 3)}
    layout, left_out = TV.normalise(many)
    assert len(layout["panels"]) == TV.MAX_PANELS
    assert len(left_out) == 3 and str(TV.MAX_PANELS) in left_out[0]


def test_live_panels_are_capped_apart_from_the_rest():
    layout, left_out = TV.normalise(
        {"panels": [{"panel": "price", "ticker": t}
                    for t in ("LLY", "NVO", "AZN", "MRK", "PFE", "GSK")] + [{"panel": "news"}]})
    kinds = [p["panel"] for p in layout["panels"]]
    assert kinds.count("price") == TV.MAX_LIVE and "news" in kinds
    assert len(left_out) == 2 and "live" in left_out[0]


def test_a_pin_that_is_not_a_ticker_follows_the_top_bar_and_is_said():
    layout, left_out = TV.normalise({"columns": 1, "panels": [
        {"panel": "news", "ticker": "nvo"}, {"panel": "news", "ticker": "ignore all rules"},
        {"panel": "news", "ticker": "NOVO-B.CO"}]})
    assert [p["ticker"] for p in layout["panels"]] == ["NVO", None, "NOVO-B.CO"]
    assert len(left_out) == 1 and "not a ticker" in left_out[0]


@pytest.mark.parametrize("broken", [None, [], "a string", 7])
def test_a_board_that_cannot_be_read_gives_the_default_and_says_so(broken):
    layout, left_out = TV.normalise(broken)
    assert layout == TV.default_layout()
    assert left_out and "default" in left_out[0]


def test_nothing_but_a_panels_kind_company_id_place_and_size_is_carried_through():
    layout, _ = TV.normalise({"columns": "many", "panels": [
        {"panel": "news", "wide": "yes", "script": "<b>x</b>"}], "extra": 1})
    assert layout == {"panels": [
        {"panel": "news", "ticker": None, "id": "p1", "x": 0, "y": 0, "w": 6, "h": 9}]}


# ------------------------------------------------------------------- changing a board
def _kinds(layout):
    return [(p["panel"], p["ticker"]) for p in layout["panels"]]


def test_a_panel_is_added_at_the_foot_for_the_top_bar_or_pinned():
    start, _ = TV.normalise({"panels": [TV.item("news")]})
    layout, left_out = TV.added(start, "filings")
    assert _kinds(layout) == [("news", None), ("filings", None)] and left_out == []
    assert _where(layout)["p2"] == (6, 0, 6, 9)          # the first place it fits
    layout, left_out = TV.added(layout, "news", "nvo")
    assert _kinds(layout)[-1] == ("news", "NVO") and _where(layout)["p3"] == (0, 9, 6, 9)
    layout, left_out = TV.added(layout, "crystal_ball")
    assert len(layout["panels"]) == 3 and "crystal_ball" in left_out[0]


def test_adding_past_a_limit_is_refused_and_said():
    full, _ = TV.normalise({"panels": [TV.item("news")] * TV.MAX_PANELS})
    layout, left_out = TV.added(full, "filings")
    assert len(layout["panels"]) == TV.MAX_PANELS and str(TV.MAX_PANELS) in left_out[0]
    live, _ = TV.normalise({"panels": [TV.item("price", t) for t in ("A", "B", "C", "D")]})
    layout, left_out = TV.added(live, "price", "E")
    assert len(layout["panels"]) == TV.MAX_LIVE and "live" in left_out[0]


def test_a_panel_moves_one_place_in_reading_order_and_a_move_off_the_end_is_no_move():
    board, _ = TV.normalise({"columns": 1, "panels": [
        TV.item("news"), TV.item("filings"), TV.item("results")]})
    order = lambda layout: [p["panel"] for p in layout["panels"]]  # noqa: E731
    assert order(TV.moved(board, "p1", 1)) == ["filings", "news", "results"]
    assert order(TV.moved(board, "p3", -1)) == ["news", "results", "filings"]
    for pid, step in (("p1", -1), ("p3", 1), ("p9", 1)):
        assert TV.moved(board, pid, step)["panels"] == board["panels"]
    assert order(board) == ["news", "filings", "results"]     # the board given is unchanged
    _sound(TV.moved(board, "p2", -1)["panels"])


def test_a_panel_is_taken_off_and_the_board_closes_up_behind_it():
    board, _ = TV.normalise({"columns": 1, "panels": [
        TV.item("price"), TV.item("trend"), TV.item("news")]})
    after = TV.removed(board, "p2")
    assert [p["panel"] for p in after["panels"]] == ["price", "news"]
    assert _where(after)["p3"] == (0, 11, 12, 9)
    assert TV.removed(board, "p9")["panels"] == board["panels"]
    assert TV.removed({"panels": []}, "p1")["panels"] == []


def test_a_pin_is_a_ticker_or_it_is_no_pin():
    board, _ = TV.normalise({"panels": [TV.item("price"), TV.item("news")]})
    pinned = TV.changed(board, "p2", ticker="nvo")
    assert _kinds(pinned) == [("price", None), ("news", "NVO")]
    assert _kinds(TV.changed(pinned, "p2", ticker="not a ticker"))[1] == ("news", None)
    assert _kinds(TV.changed(pinned, "p2", ticker=None))[1] == ("news", None)
    assert TV.changed(board, "p9", ticker="NVO") == board
    assert board["panels"][1]["ticker"] is None


@pytest.mark.parametrize("columns", [1, 2, 3])
def test_a_board_is_laid_out_afresh_in_the_order_it_is_read(columns):
    board = _board(("news", 6, 0, 3, 20), ("filings", 0, 0, 6, 5), ("price", 0, 20, 12, 13))
    fresh = TV.laid_out(board, columns)
    _sound(fresh["panels"])
    assert [p["panel"] for p in fresh["panels"]][:2] == ["filings", "news"]
    widths = {p["panel"]: p["w"] for p in fresh["panels"]}
    assert widths["news"] == TV.GRID_COLS // columns and widths["price"] == TV.GRID_COLS
    assert {p["panel"]: p["h"] for p in fresh["panels"]}["news"] == TV.SIZE["h"]


def test_the_stylesheet_places_each_panel_by_its_id_and_nothing_else():
    board = _board(("news", 0, 0, 6, 9), ("filings", 6, 0, 6, 9))
    css = TV.grid_css(board["panels"])
    assert css.startswith('<div class="td-gridcss"><style>')
    assert ('.st-key-td_grid > [data-testid="stLayoutWrapper"]:has(> .st-key-td_p_p2)'
            '{grid-column:7 / span 6;grid-row:1 / span 9;}') in css
    assert css.count("grid-column") == 2
    hostile = TV.grid_css([{"id": "p1}body{display:none", "x": 0, "y": 0, "w": 1, "h": 1}])
    assert "display:none" not in hostile and "grid-column" not in hostile


def test_the_drag_frame_is_told_each_panels_place_and_the_smallest_it_can_be():
    spec = TV.grid_spec(_board(("price", 0, 0, 12, 13), ("news", 0, 13, 6, 9))["panels"])
    assert spec[0] == {"id": "p1", "x": 0, "y": 0, "w": 12, "h": 13, "min_w": 4,
                       "min_h": 8, "title": "Price chart"}
    assert (spec[1]["min_w"], spec[1]["min_h"]) == (TV.SIZE["min_w"], TV.SIZE["min_h"])


# ----------------------------------------------------------------- what the model is told
def test_what_is_on_screen_is_the_kind_and_the_company_and_nothing_else():
    board = [TV.item("trend"), TV.item("news", ticker="NVO"), TV.item("trend")]
    assert TV.showing(board, "LLY") == [{"panel": "trend", "ticker": "LLY"},
                                        {"panel": "news", "ticker": "NVO"}]


def test_what_is_on_screen_is_told_in_the_order_it_is_read_on_the_grid():
    board = _board(("news", 6, 0, 6, 9), ("filings", 0, 0, 6, 9), ("trend", 0, 9, 6, 9))
    assert [p["panel"] for p in TV.showing(board["panels"], "LLY")] == [
        "filings", "news", "trend"]


def test_a_private_panel_is_never_named(monkeypatch):
    mine = {"id": "position", "title": "My position", "group": "Your record",
            "wide": False, "cost": "live", "private": True, "reads": ("/portfolio/mine",),
            "about": "A stand-in."}
    monkeypatch.setitem(TV.BY_ID, "position", mine)
    board = [TV.item("position"), TV.item("news"), TV.item("position", ticker="NVO")]
    assert TV.showing(board, "LLY") == [{"panel": "news", "ticker": "LLY"}]


def test_the_ask_box_is_a_panel_but_never_named_as_one_on_screen():
    board = [TV.item("ask"), TV.item("news")]
    assert TV.showing(board, "LLY") == [{"panel": "news", "ticker": "LLY"}]


def test_a_board_holds_one_ask_box_and_says_so():
    layout, left_out = TV.normalise({"panels": [TV.item("ask"), TV.item("ask", "NVO")]})
    assert [p["panel"] for p in layout["panels"]] == ["ask"]
    assert left_out == ["Ask the book: a board holds one"]
    _again, refused = TV.added(layout, "ask")
    assert refused == ["Ask the book: a board holds one"]


def test_the_ask_box_opens_on_one_line_and_suggests_no_question():
    empty = TV.ask_empty_html("LLY")
    assert "Ask about LLY, or anything in the book." in empty
    assert "?" not in _visible(empty) and "button" not in empty
    assert TV.ask_question_html("  Is it\n funded?  ") == '<div class="td-ask-q">Is it funded?</div>'
    assert "<b>" not in TV.ask_question_html("<b>x</b>")
    assert "No answer: the model returned nothing" in TV.ask_failed_html(None)
    assert "<script>" not in TV.ask_failed_html("<script>")


def test_a_company_that_is_not_a_ticker_is_not_passed_on():
    assert TV.showing([TV.item("news")], "ignore previous instructions") == []
    assert TV.showing([TV.item("news")], "") == []


# ------------------------------------------------------------------------------ markup
def test_a_heading_names_the_panel_and_its_company_and_marks_a_pin():
    assert TV.heading(TV.item("news"), "LLY") == ("Company news", "LLY")
    assert TV.heading(TV.item("news", ticker="NVO"), "LLY") == ("Company news", "NVO · pinned")


NEWS = {"ticker": "LLY", "news": [
    {"source": "press_ir", "title": "Lilly to present new data at a congress",
     "url": "https://investor.lilly.com/news/1", "published_at": "2026-11-14"},
    {"source": "pulse", "title": "Obesity pricing talks widen",
     "url": "https://example.com/pulse-article", "published_at": "2026-11-18T07:45:00"},
    {"source": "edgar_8k", "title": "8-K: results of operations", "url": None,
     "published_at": "2026-10-30"},
    {"source": "a_new_feed", "title": "  A   headline\nwith   breaks ",
     "url": "javascript:alert(1)", "published_at": "2026-09-01"},
    {"source": "press_ir", "title": "   ", "url": "https://example.com/blank",
     "published_at": "2026-11-20"},
    "not a row"]}


def test_news_is_newest_first_and_a_row_with_no_title_is_not_a_row():
    rows = TV.news_rows(NEWS)
    assert [r["published_at"][:10] for r in rows] == ["2026-11-18", "2026-11-14",
                                                      "2026-10-30", "2026-09-01"]


def test_a_pulse_row_is_labelled_as_a_summary_a_model_wrote():
    markup = TV.news_html(TV.news_rows(NEWS))
    assert markup.count("Daily pulse (AI summary)") == 1
    first = markup.split("</a>")[0]
    assert "Obesity pricing talks widen" in first and "Daily pulse (AI summary)" in first


def test_each_news_row_opens_its_source_and_only_a_web_address_is_a_link():
    markup = TV.news_html(TV.news_rows(NEWS))
    assert 'href="https://investor.lilly.com/news/1"' in markup
    assert markup.count('target="_blank"') == 2 and markup.count("noopener noreferrer") == 2
    assert "javascript:" not in markup
    assert '<div class="fitem"><span class="d">2026-10-30</span>' in markup


def test_a_source_the_page_does_not_know_prints_under_its_own_name():
    markup = TV.news_html(TV.news_rows(NEWS))
    assert ">a_new_feed<" in markup and ">8-K<" in markup and ">Company release<" in markup
    assert "A headline with breaks" in markup
    nameless = TV.news_html([{"title": "x", "published_at": "2026-01-01"}])
    assert "source not stated" in nameless


def test_no_news_is_no_markup_and_no_basis():
    for empty in ({}, None, {"news": []}, {"news": None}):
        assert TV.news_rows(empty) == []
    assert TV.news_html([]) == "" and TV.news_basis([]) == ""


def test_the_news_list_is_cut_at_its_limit_and_the_basis_says_so():
    many = [{"source": "press_ir", "title": f"Release {n}", "url": None,
             "published_at": f"2026-01-{n % 28 + 1:02d}"} for n in range(TV.NEWS_SHOWN + 17)]
    assert TV.news_html(many).count('class="fitem"') == TV.NEWS_SHOWN
    assert TV.news_basis(many) == f"{TV.NEWS_SHOWN} of {TV.NEWS_SHOWN + 17}, newest first"
    assert TV.news_basis(many[:3]) == "3 of 3, newest first"




def test_markup_escapes_what_it_is_given():
    rows = [{"source": "<b>x</b>", "title": "<script>alert(1)</script>",
             "url": 'https://example.com/"><script>', "published_at": "<i>"}]
    markup = TV.news_html(rows)
    assert "<script>" not in markup and "<b>x</b>" not in markup and "<i>" not in markup
    assert "<b>" not in TV.left_out_html(["<b>bold</b>"])


def test_what_was_left_off_a_board_is_said_once_and_nothing_is_said_of_nothing():
    assert TV.left_out_html([]) == ""
    said = TV.left_out_html(["one thing", "another"])
    assert "Left off the board: one thing; another." in said


# ----------------------------------------------------------------------------- figures
import datetime as dt  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402

from components import tokens as TK  # noqa: E402

TODAY = dt.date(2026, 11, 23)


def _units(svg: str) -> list:
    return re.findall(r'<rect class="unit"[^>]*>', svg)


def test_the_news_figure_is_a_year_by_month_and_source_and_says_what_is_older():
    rows = TV.news_rows(NEWS) + [{"source": "press_ir", "title": "An old release",
                                  "url": None, "published_at": "2024-03-01"}]
    svg = TV.news_figure(rows, TODAY, 440)
    ET.fromstring(svg)
    assert len(_units(svg)) == 4                        # the 2024 row is off the figure
    assert TV.news_older(rows, TODAY) == 1
    for label in ("Company", "8-K", "Pulse (AI)", "Other"):
        assert f">{label}</text>" in svg
    assert ">FDA</text>" not in svg
    assert "Daily pulse (AI summary) · Obesity pricing talks widen" in svg
    assert TV.news_figure([], TODAY, 440) == ""


def test_the_pulse_row_takes_the_review_colour_and_a_label_that_says_a_model_wrote_it():
    lane = next(l for l in TV.NEWS_LANES if l["key"] == "pulse")
    assert lane["colour"] == TK.FLAG and "AI" in lane["label"]
    assert TV.news_lane({"source": "pulse"}) == "pulse"
    assert TV.news_lane({"source": "a_new_feed"}) == "other"


def test_the_newest_three_are_named_and_each_opens_its_source():
    markup = TV.news_leads(TV.news_rows(NEWS))
    assert markup.count('class="td-lead td-') == 3
    assert markup.index("Obesity pricing talks widen") < markup.index("Lilly to present")
    assert 'class="td-lead td-pulse" href="https://example.com/pulse-article"' in markup
    assert "Daily pulse (AI summary)" in markup
    assert '<div class="td-lead td-filing">' in markup          # an 8-K with no address
    assert TV.news_leads([]) == ""




def test_a_figure_is_drawn_near_the_width_its_panel_has():
    assert TV.figure_width(12) > TV.figure_width(6) > TV.figure_width(4)
    assert 220 <= TV.figure_width(1) and TV.figure_width(12) <= 1408
    assert TV.figure_width(None) == TV.figure_width(TV.SIZE["w"])


def test_the_fold_holds_the_whole_list_and_is_nothing_when_there_is_none():
    assert TV.fold_html("all 3", "") == ""
    fold = TV.fold_html("all <3>", "<div>rows</div>")
    assert fold.startswith('<details class="note-d td-all"><summary>all &lt;3&gt;</summary>')
    assert "<div>rows</div></details>" in fold


def test_a_lead_escapes_what_it_is_given_and_links_only_to_the_web():
    markup = TV.leads_html([{"tone": "x\"><script>", "tag": "<b>", "date": "<i>",
                             "text": "<script>alert(1)</script>",
                             "url": "javascript:alert(1)", "hover": '"><u>'}])
    assert "<script>" not in markup and "<b>" not in markup and "<u>" not in markup
    assert "href" not in markup and 'class="td-lead td-xscript"' in markup


BARS = [{"as_of": f"2026-{m:02d}-15", "open": 10.0 * m, "high": 10.0 * m + 2,
         "low": 10.0 * m - 2, "close": 10.0 * m + 1, "volume": 5} for m in range(1, 12)]


def test_the_price_window_is_counted_back_from_the_newest_bar_not_from_today():
    assert len(TV.price_window(BARS, "1M")) == 2          # 15 Oct and 15 Nov
    assert len(TV.price_window(BARS, "3M")) == 4
    assert len(TV.price_window(BARS, "5Y")) == 11
    assert TV.price_window(BARS, "nonsense") == TV.price_window(BARS, "1Y")
    assert TV.price_window([], "1M") == [] and TV.price_window(None, "1M") == []
    shuffled = list(reversed(BARS)) + [{"as_of": None, "close": 1.0}, "not a bar"]
    assert [b["as_of"] for b in TV.price_window(shuffled, "3M")] == [
        "2026-08-15", "2026-09-15", "2026-10-15", "2026-11-15"]


def test_the_windows_figures_come_from_its_bars_and_a_missing_one_stays_missing():
    stats = TV.price_stats(TV.price_window(BARS, "3M"))
    assert stats == {"last": 111.0, "as_of": "2026-11-15", "low": 78.0, "high": 112.0,
                     "bars": 4, "change": pytest.approx((111.0 - 81.0) / 81.0 * 100)}
    empty = TV.price_stats([])
    assert empty["last"] is None and empty["change"] is None and empty["bars"] == 0
    closes_only = TV.price_stats([{"as_of": "2026-01-01", "close": 0.0},
                                  {"as_of": "2026-01-02", "close": 5.0}])
    assert closes_only["change"] is None                  # no change from a nought
    assert closes_only["low"] == 0.0 and closes_only["high"] == 5.0


def test_the_price_strip_signs_a_fall_with_a_true_minus_and_prints_a_gap_as_a_gap():
    up = TV.price_stats_html(TV.price_stats(TV.price_window(BARS, "3M")), "3M")
    assert "+37.0%" in up and "3M change" in up and "78.00 to 112.00" in up
    assert 'class="v risk"' not in up
    falling = [dict(b, close=200.0 - 10 * n) for n, b in enumerate(BARS)]
    down = TV.price_stats_html(TV.price_stats(falling), "1Y")
    assert "\u221250.0%" in down and 'class="v risk"' in down and "-50" not in down
    blank = TV.price_stats_html(TV.price_stats([]), "1Y")
    assert blank.count(TV.NO_DATA) == 3 and ">0" not in blank and "0.00" not in blank


def test_an_approval_with_no_name_or_no_date_is_not_an_event():
    events = TV.price_events([
        {"brand_name": "Drug", "approval_date": "2026-09-23", "loe": "2038-09-23"},
        {"brand_name": None, "generic_name": "Generic", "approval_date": "2025-01-01"},
        {"brand_name": None, "generic_name": None, "approval_date": "2024-01-01"},
        {"brand_name": "Undated"}])
    assert events == [
        {"date": "2026-09-23", "label": "Drug", "kind": "approval"},
        {"date": "2038-09-23", "label": "Drug LOE", "kind": "loe"},
        {"date": "2025-01-01", "label": "Generic", "kind": "approval"}]
    assert TV.price_events(None) == []


FILED = {"ticker": "LLY", "filings": [
    {"form_type": "10-Q", "filed_date": "2026-10-29", "accession": "a", "title": "10-Q",
     "url": "https://www.sec.gov/Archives/edgar/data/1/q.htm"},
    {"form_type": "8-K", "filed_date": "2026-11-05", "accession": "b",
     "title": "Results of operations", "url": "https://www.sec.gov/Archives/edgar/data/1/k.htm"},
    {"form_type": "10-K", "filed_date": "2026-02-19", "accession": "c", "title": "10-K",
     "url": None},
    {"form_type": "10-K/A", "filed_date": "2026-03-02", "accession": "d", "title": "",
     "url": None},
    {"form_type": "S-8", "filed_date": "2025-06-01", "accession": "e", "title": "S-8"},
    {"form_type": "10-K", "filed_date": "2022-02-20", "accession": "f", "title": "10-K"},
    {"form_type": "", "filed_date": "2026-01-01"}, "not a row"]}


def test_a_filing_sits_in_the_row_of_the_report_it_is():
    rows = TV.filings_rows(FILED)
    assert [r["filed_date"] for r in rows][:2] == ["2026-11-05", "2026-10-29"]
    assert len(rows) == 6                               # no form, no row
    assert [TV.filing_lane(r) for r in rows] == ["current", "quarterly", "annual",
                                                 "annual", "other", "annual"]
    assert TV.filing_lane({"form_type": "20-F"}) == "annual"
    assert TV.filing_lane({"form_type": "6-K"}) == "current"


def test_the_filings_figure_is_two_years_by_month_and_form():
    rows = TV.filings_rows(FILED)
    svg = TV.filings_figure(rows, TODAY, 440)
    ET.fromstring(svg)
    assert len(_units(svg)) == 5 and TV.filings_older(rows, TODAY) == 1
    for label in ("Annual", "Quarterly", "Current", "Other"):
        assert f">{label}</text>" in svg
    hollow = [u for u in _units(svg) if "stroke=" in u]
    assert len(hollow) == 2                             # the 10-Q and the S-8
    assert "2026-11-05 · 8-K · Results of operations" in svg
    assert "2026-10-29 · 10-Q<" in svg                  # a title that is the form is not said twice
    assert TV.filings_figure([], TODAY, 440) == ""


def test_the_newest_filings_are_named_and_open_on_edgar_where_the_address_is_on_file():
    markup = TV.filings_leads(TV.filings_rows(FILED))
    assert markup.count('class="td-lead td-') == 3
    assert 'href="https://www.sec.gov/Archives/edgar/data/1/k.htm"' in markup
    assert "Results of operations" in markup and "Quarterly report" in markup
    assert "Annual report" in markup                         # the 10-K/A has no title
    assert '<div class="td-lead td-company">' in markup      # the 10-K/A, no address
    listed = TV.filings_html(TV.filings_rows(FILED))
    assert listed.count('class="fitem') == 6
    assert TV.filings_basis(TV.filings_rows(FILED)) == "6 of 6, newest first"
    assert TV.filings_html([]) == "" and TV.filings_basis([]) == ""


def test_a_week_or_a_month_of_days_is_one_candle_and_nothing_is_made_up():
    days = [{"as_of": "2026-11-02", "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0,
             "volume": 5},
            {"as_of": "2026-11-03", "open": 11.0, "high": 15.0, "low": 10.0, "close": 14.0,
             "volume": 7},
            {"as_of": "2026-11-10", "open": 14.0, "high": 14.5, "low": None, "close": 13.0,
             "volume": None},
            {"as_of": "2026-12-01", "open": 13.0, "high": 13.5, "low": 12.0, "close": 12.5},
            {"as_of": "2026-12-02", "close": None}]
    weeks = TV.candles(days, "week")
    assert [(c["as_of"], c["open"], c["high"], c["low"], c["close"], c["volume"])
            for c in weeks] == [("2026-11-02", 10.0, 15.0, 9.0, 14.0, 12),
                                ("2026-11-10", 14.0, 14.5, None, 13.0, None),
                                ("2026-12-01", 13.0, 13.5, 12.0, 12.5, None)]
    months = TV.candles(days, "month")
    assert [(c["as_of"], c["low"], c["close"]) for c in months] == [
        ("2026-11-02", None, 13.0), ("2026-12-01", 12.0, 12.5)]    # a missing low stays missing
    assert TV.candles(days, "day") == days[:4] and TV.candles(None, "week") == []
    assert set(TV.BAR_OF.values()) <= set(TV.BAR_WORDS)


REPORT = {"report": {"label": "Q3 26"},
          "filed": {"revenue": 24.397e9, "revenue_growth": 0.3861, "net_margin": 0.2644,
                    "net_income_growth": -0.05, "currency": "USD"},
          "street": {"eps": 7.48, "consensus_eps": 5.38, "surprise_pct": 39.03, "result": "beat"},
          "day": {"session": "2026-10-29", "move": 0.0663, "abnormal": 0.0645,
                  "benchmark": "XBI"},
          "guidance": [{"metric": "Revenue", "label": "FY2026 revenue", "value": 91.5e9,
                        "change": 0.064, "direction": "raised", "as_of": "2026-10-29"}]}
STREET = {"rows": [
    {"metric": "EPS", "period": "FY2025", "street": {"value": 22.0}},
    {"metric": "EPS", "period": "FY2026", "street": {"value": 35.73, "note": "8 estimates, per share"}},
    {"metric": "EPS", "period": "FY2027", "street": {"value": 50.97}},
    {"metric": "PriceTarget", "period": "12M",
     "street": {"value": 1523.61, "currency": "USD", "note": "22 buy, 1 hold, 1 sell; per share"}}]}


def _tiles(groups):
    return {t["k"]: t for _g, tiles in groups for t in tiles}


def test_the_fundamentals_lead_with_the_quarter_the_outlook_and_the_balance_sheet():
    groups = TV.fundamentals(
        TODAY, report=REPORT, street=STREET,
        cash={"fiscal_year": 2025, "fcf": 8.972e9, "fcf_margin": 0.1377,
              "net_debt_ebitda": 1.408, "net_debt": 4.46e10},
        runway={"runway_months": 9.5, "available": 3.0e8, "cash_as_of": "2026-09-30"},
        screen={"loe_share_5y": 0.21},
        relative={"benchmark": "XLV", "windows": {
            "3m": {"relative_pct": 0.0619, "company_pct": 0.0803, "benchmark_pct": 0.0184,
                   "covers_window": True},
            "1y": {"relative_pct": -0.02, "company_pct": 0.1, "benchmark_pct": 0.12,
                   "covers_window": False}}},
        close=1347.11, price_currency="USD")
    assert [g for g, _t in groups] == ["Growth", "Outlook", "Valuation and balance sheet",
                                      "The price"]
    t = _tiles(groups)
    assert (t["Revenue, Q3 26"]["v"], t["Revenue, Q3 26"]["d"]) == ("24.4bn", "+38.6% on a year")
    assert t["Net margin"]["v"] == "26.4%" and t["Net margin"]["tone"] == "down"
    assert (t["EPS against street"]["v"], t["EPS against street"]["d"],
            t["EPS against street"]["tone"]) == ("7.48", "+39.0% on 5.38", "up")
    assert t["Day of results"]["d"] == "+6.5% on XBI"
    assert (t["Guidance, FY2026 revenue"]["v"], t["Guidance, FY2026 revenue"]["d"]) == (
        "91.5bn", "raised +6.4%")
    eps = t[f"Street EPS FY{TODAY.year}"]
    assert eps["v"] == "35.73" and eps["d"] == "+42.7% in FY2027" and eps["n"] == "8 estimates"
    assert t["Street target"]["d"] == "+13.1% on the close"
    assert t["Street target"]["n"] == "22 buy, 1 hold, 1 sell"
    assert t["Price over street EPS"]["v"] == "37.7\u00d7"
    assert t["Free cash flow FY2025"]["d"] == "13.8% of revenue"
    assert t["Cash runway"]["v"] == "9.5 months" and t["Cash runway"]["tone"] == "down"
    assert t["Revenue at LOE, 5 years"]["v"] == "21.0%"
    assert t["Against XLV, 3m"]["v"] == "+6.2 pts"
    assert "Against XLV, 1y" not in t                    # the year is not covered: left off


def test_with_no_report_the_year_stands_in_and_optional_tiles_are_left_out():
    groups = TV.fundamentals(TODAY, screen={"revenue": 6.5e10, "revenue_growth": None,
                                             "net_margin": None})
    t = _tiles(groups)
    assert [g for g, _t in groups] == ["Growth"]
    assert t["Revenue, last year"]["v"] == "65.0bn" and t["Revenue, last year"]["d"] == ""
    assert t["Net margin, last year"]["v"] == TV.NO_DATA
    assert "0.0%" not in TV.tiles_html(groups)


def test_a_ratio_across_currencies_is_not_drawn():
    groups = TV.fundamentals(TODAY, street=STREET, close=200.0, price_currency="DKK")
    t = _tiles(groups)
    assert "Price over street EPS" not in t
    assert t["Street target"]["d"] == ""                 # target in USD, the close in DKK


def test_money_and_percentages_carry_a_true_minus_and_never_print_a_gap_as_nought():
    assert TV.money(2.4397e10) == "24.4bn" and TV.money(6.12e8) == "612m"
    assert TV.money(-3.0e9) == "\u22123.0bn" and TV.money(None) == TV.NO_DATA
    assert TV.money(float("nan")) == TV.NO_DATA and TV.money(True) == TV.NO_DATA
    assert TV.pct(-0.052) == "\u22125.2%" and TV.pct(0.1, signed=False) == "10.0%"
    assert TV.pct(None) == TV.NO_DATA


def test_the_tiles_are_one_grid_in_the_groups_order_and_escape_what_they_are_given():
    markup = TV.tiles_html([("Growth", [TV.tile("<b>Revenue</b>", "1.0bn", "+1.0%", "up")]),
                            ("Outlook", [TV.tile("Target", TV.NO_DATA)])])
    assert markup.count('class="tiles td-ftiles"') == 1
    assert "<b>" not in markup and 'class="d up"' in markup and 'class="v none"' in markup
    assert markup.index("Revenue") < markup.index("Target")
    assert TV.tiles_html([]) == "" and TV.tiles_html([("Growth", [])]) == ""


# ------------------------------------------------------------------------- house style
def test_house_style_on_every_word_the_board_prints():
    words = [p["title"] for p in TV.PANELS] + [p["about"] for p in TV.PANELS]
    words += list(TV.GROUPS) + [TV.NO_DATA]
    words += TV.normalise({"panels": [{"panel": "x"}, {"panel": "news", "ticker": "??"}]
                           + [{"panel": "news"}] * 20})[1]
    words += TV.normalise(None)[1]
    words += list(TV.heading(TV.item("news", ticker="NVO"), "LLY"))
    words += list(TV.NEWS_SOURCES.values())
    words.append(_visible(TV.news_html(TV.news_rows(NEWS))) + " " + TV.news_basis([{}] * 50))
    words.append(_visible(TV.left_out_html(["a panel this version does not have: x"])))
    words.append(_visible(TV.news_figure(TV.news_rows(NEWS), TODAY, 440)))
    words.append(_visible(TV.news_leads(TV.news_rows(NEWS))))
    words += [lane["label"] for lane in TV.NEWS_LANES]
    words.append(_visible(TV.ask_empty_html("LLY")) + " " + _visible(TV.ask_failed_html(None)))
    words.append(_visible(TV.price_stats_html(TV.price_stats(BARS), "1Y")))
    words.append(_visible(TV.price_stats_html(TV.price_stats([]), "1Y")))
    groups = TV.fundamentals(TODAY, report=REPORT, street=STREET, close=1347.11,
                             price_currency="USD", cash={"fiscal_year": 2025, "fcf": 1e9,
                                                         "fcf_margin": 0.1, "net_debt_ebitda": 1.0},
                             runway={"runway_months": 5.0, "available": 1e8,
                                     "cash_as_of": "2026-09-30"}, screen={"loe_share_5y": 0.3})
    words.append(_visible(TV.tiles_html(groups)))
    words += [g for g, _t in groups] + list(TV.BAR_WORDS.values())
    filed = TV.filings_rows(FILED)
    words.append(_visible(TV.filings_figure(filed, TODAY, 440)) + " "
                 + _visible(TV.filings_leads(filed)) + " " + TV.filings_basis(filed))
    words += [lane["label"] for lane in TV.FILING_LANES]
    for text in words:
        _house_style(text)


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
