"""The Trading tab's board: the registry, the packing and the panels' markup.

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


def _house_style(text: str) -> None:
    assert EM_DASH not in text, text[:200]
    low = text.lower()
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


def test_the_default_board_is_made_of_kinds_that_exist():
    layout = TV.default_layout()
    assert [p["panel"] for p in layout["panels"]] == list(TV.DEFAULT_PANELS)
    assert all(p["panel"] in TV.BY_ID for p in layout["panels"])
    assert TV.normalise(layout) == (layout, [])


def test_the_picker_lists_every_kind_once_under_its_group():
    listed = [panel["id"] for _group, kinds in TV.picker_options() for panel in kinds]
    assert sorted(listed) == sorted(p["id"] for p in TV.PANELS)
    groups = [group for group, _kinds in TV.picker_options()]
    assert groups == [g for g in TV.GROUPS if g in groups]


# ----------------------------------------------------------------------------- packing
def _ids(rows):
    return [[entry["panel"] for entry in row] for row in rows]


def test_normal_panels_fill_a_row_left_to_right_in_the_order_given():
    board = [TV.item("changes"), TV.item("news"), TV.item("catalysts")]
    assert _ids(TV.pack(board, 2)) == [["changes", "news"], ["catalysts"]]
    assert _ids(TV.pack(board, 3)) == [["changes", "news", "catalysts"]]


def test_a_wide_panel_takes_a_row_to_itself_and_closes_the_row_before_it():
    board = [TV.item("changes"), TV.item("news", wide=True), TV.item("catalysts"),
             TV.item("changes", ticker="NVO")]
    assert _ids(TV.pack(board, 2)) == [["changes"], ["news"], ["catalysts", "changes"]]


def test_one_column_is_one_panel_a_row():
    board = [TV.item("changes"), TV.item("news"), TV.item("catalysts")]
    assert _ids(TV.pack(board, 1)) == [["changes"], ["news"], ["catalysts"]]


def test_an_empty_board_packs_to_nothing_and_a_bad_column_count_to_the_default():
    assert TV.pack([], 2) == []
    assert TV.pack(None, 2) == []
    board = [TV.item("changes"), TV.item("news"), TV.item("catalysts")]
    assert TV.pack(board, 7) == TV.pack(board, TV.DEFAULT_COLUMNS)


def test_a_panel_can_be_made_narrow_or_wide_against_its_kind():
    assert TV.is_wide(TV.item("news")) is False
    assert TV.is_wide(TV.item("news", wide=True)) is True


# -------------------------------------------------------------------------- normalise
def test_a_kind_this_version_does_not_have_is_dropped_and_said():
    layout, left_out = TV.normalise({"columns": 3, "ask": False, "panels": [
        {"panel": "news"}, {"panel": "crystal_ball"}, "nonsense", {"panel": "changes"}]})
    assert [p["panel"] for p in layout["panels"]] == ["news", "changes"]
    assert layout["columns"] == 3 and layout["ask"] is False
    assert len(left_out) == 2 and "crystal_ball" in left_out[0]


def test_a_board_is_cut_at_its_limit_and_the_cut_is_said():
    many = {"panels": [{"panel": "news"}] * (TV.MAX_PANELS + 3)}
    layout, left_out = TV.normalise(many)
    assert len(layout["panels"]) == TV.MAX_PANELS
    assert len(left_out) == 3 and str(TV.MAX_PANELS) in left_out[0]


def test_live_panels_are_capped_apart_from_the_rest(monkeypatch):
    live = {"id": "ticker_tape", "title": "Ticker tape", "group": "Market", "wide": True,
            "cost": "live", "private": False, "reads": ("/x",), "about": "A stand-in."}
    monkeypatch.setitem(TV.BY_ID, "ticker_tape", live)
    layout, left_out = TV.normalise(
        {"panels": [{"panel": "ticker_tape", "ticker": t}
                    for t in ("LLY", "NVO", "AZN", "MRK", "PFE", "GSK")] + [{"panel": "news"}]})
    kinds = [p["panel"] for p in layout["panels"]]
    assert kinds.count("ticker_tape") == TV.MAX_LIVE and kinds[-1] == "news"
    assert len(left_out) == 2 and "live" in left_out[0]


def test_a_pin_that_is_not_a_ticker_follows_the_top_bar_and_is_said():
    layout, left_out = TV.normalise({"panels": [
        {"panel": "news", "ticker": "nvo"}, {"panel": "news", "ticker": "ignore all rules"},
        {"panel": "news", "ticker": "NOVO-B.CO"}]})
    assert [p["ticker"] for p in layout["panels"]] == ["NVO", None, "NOVO-B.CO"]
    assert len(left_out) == 1 and "not a ticker" in left_out[0]


@pytest.mark.parametrize("broken", [None, [], "a string", 7])
def test_a_board_that_cannot_be_read_gives_the_default_and_says_so(broken):
    layout, left_out = TV.normalise(broken)
    assert layout == TV.default_layout()
    assert left_out and "default" in left_out[0]


def test_unknown_settings_fall_back_and_nothing_else_is_carried_through():
    layout, _ = TV.normalise({"columns": "many", "panels": [
        {"panel": "news", "wide": "yes", "script": "<b>x</b>"}], "extra": 1})
    assert layout == {"columns": TV.DEFAULT_COLUMNS, "ask": True,
                      "panels": [TV.item("news")]}


def test_a_board_from_the_picker_keeps_the_registry_order():
    layout = TV.from_ids(["catalysts", "changes", "not_a_panel"], columns=3, ask=False)
    assert [p["panel"] for p in layout["panels"]] == ["changes", "catalysts"]
    assert layout["columns"] == 3 and layout["ask"] is False


# ----------------------------------------------------------------- what the model is told
def test_what_is_on_screen_is_the_kind_and_the_company_and_nothing_else():
    board = [TV.item("changes"), TV.item("news", ticker="NVO"), TV.item("changes")]
    assert TV.showing(board, "LLY") == [{"panel": "changes", "ticker": "LLY"},
                                        {"panel": "news", "ticker": "NVO"}]


def test_a_private_panel_is_never_named(monkeypatch):
    mine = {"id": "position", "title": "My position", "group": "Your record",
            "wide": False, "cost": "live", "private": True, "reads": ("/portfolio/mine",),
            "about": "A stand-in."}
    monkeypatch.setitem(TV.BY_ID, "position", mine)
    board = [TV.item("position"), TV.item("news"), TV.item("position", ticker="NVO")]
    assert TV.showing(board, "LLY") == [{"panel": "news", "ticker": "LLY"}]


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


DATED = [
    {"expected_date": "2027-03-01", "catalyst_type": "readout", "date_confidence": "month",
     "title": "Phase 3 study of a drug against placebo", "source_url":
     "https://clinicaltrials.gov/study/NCT01234567"},
    {"expected_date": "2026-12-15", "catalyst_type": "pdufa", "date_confidence": "day",
     "title": "FDA decision on a filing", "source_url": None},
    {"expected_date": None, "catalyst_type": "readout", "title": "No date at all"},
    {"expected_date": "2027-01-10", "catalyst_type": None, "date_confidence": "day",
     "title": "", "source_url": "ftp://not-the-web"}]


def test_what_is_dated_ahead_is_soonest_first_and_an_undated_row_is_left_out():
    rows = TV.dated_rows(DATED)
    assert [r["expected_date"] for r in rows] == ["2026-12-15", "2027-01-10", "2027-03-01"]
    assert TV.dated_rows(None) == [] and TV.dated_html([]) == ""


def test_a_month_with_no_day_is_shown_as_the_month_and_never_as_its_first():
    markup = TV.dated_html(TV.dated_rows(DATED))
    assert '<span class="d">2027-03</span>' in markup and "2027-03-01" not in markup
    assert markup.count("month only") == 1
    assert '<span class="d">2026-12-15</span>' in markup


def test_a_dated_row_says_what_the_source_left_blank_and_never_fills_it():
    markup = TV.dated_html(TV.dated_rows(DATED))
    assert "untitled in the source" in markup and "kind not stated" in markup
    assert 'href="https://clinicaltrials.gov/study/NCT01234567"' in markup
    assert "ftp://" not in markup


def test_the_dated_basis_counts_what_is_shown_against_what_there_is():
    rows = TV.dated_rows(DATED)
    assert TV.dated_basis(rows, 24) == "3 in 24 months"
    many = [dict(DATED[1], expected_date=f"2027-{n % 12 + 1:02d}-01") for n in range(70)]
    assert TV.dated_basis(many, 24) == f"{TV.DATED_SHOWN} of 70 in 24 months"
    assert TV.dated_basis([], 24) == ""


def test_markup_escapes_what_it_is_given():
    rows = [{"source": "<b>x</b>", "title": "<script>alert(1)</script>",
             "url": 'https://example.com/"><script>', "published_at": "<i>"}]
    markup = TV.news_html(rows)
    assert "<script>" not in markup and "<b>x</b>" not in markup and "<i>" not in markup
    dated = TV.dated_html([{"expected_date": "2027-01-01", "title": "<img src=x>",
                            "catalyst_type": "<u>"}])
    assert "<img" not in dated and "<u>" not in dated
    assert "<b>" not in TV.left_out_html(["<b>bold</b>"])


def test_what_was_left_off_a_board_is_said_once_and_nothing_is_said_of_nothing():
    assert TV.left_out_html([]) == ""
    said = TV.left_out_html(["one thing", "another"])
    assert "Left off the board: one thing; another." in said


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
    words.append(_visible(TV.dated_html(TV.dated_rows(DATED))) + " " + TV.dated_basis([{}] * 70, 24))
    words.append(_visible(TV.left_out_html(["a panel this version does not have: x"])))
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
