"""The Trading tab's board, drawn through Streamlit on stand-in reads.

``trading_page`` is run in AppTest with its one reader replaced, so no API, no database
and no network is needed and nothing here is ever skipped. The house's helpers arrive as
a kit; a plain stand-in for each is enough to see what the page asks them to draw.
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

_PAGE = '''
import datetime as dt, sys, types, urllib.error
sys.path.insert(0, {frontend!r})
import streamlit as st
import trading_page

today = dt.date.today()
ahead = (today + dt.timedelta(days=70)).isoformat()
NEWS = {{"ticker": "LLY", "news": [
    {{"source": "press_ir", "title": "A release about a readout", "url": "https://example.com/a",
      "published_at": "2026-11-14"}},
    {{"source": "pulse", "title": "A pulse item", "url": "https://example.com/b",
      "published_at": "2026-11-18"}}]}}
DATED = [{{"expected_date": ahead, "catalyst_type": "readout", "date_confidence": "day",
           "title": "Phase 3 readout of a study", "source_url": None}}]
asked = st.session_state.setdefault("asked", [])
FAIL = {fail!r}

def fetch(api_base, path, timeout):
    asked.append(path)
    if FAIL and FAIL in path:
        raise urllib.error.URLError("connection refused")
    if path.endswith("/news"):
        return NEWS
    if path.startswith("/catalysts?"):
        return DATED
    if path.startswith("/changes?"):
        return [{{"ticker": "NVO", "date": today.isoformat(), "headline": "NVO a pinned change",
                  "significance": "high"}}]
    raise AssertionError("a read the board was not expected to make: " + path)
fetch.clear = lambda: None
trading_page._fetch = fetch

def section(label, count=None, basis=""):
    st.markdown(f"SECTION[{{label}}|{{count}}|{{basis}}]")
def state(title, detail, error=False):
    st.markdown(f"STATE[{{title}}|{{detail}}|{{error}}]")
def note(text):
    st.markdown(f"NOTE[{{text}}]")
def changes(feed, ticker, today, levels):
    return [it for it in feed if it.get("ticker") == ticker and it.get("significance") in levels]
def change_row(item):
    return f"<div class='fitem'>{{item['headline']}}</div>"
def ask(api_base, ticker, name, slot="", showing_key=""):
    st.markdown(f"ASK[{{ticker}}|{{name}}|{{slot}}|{{showing_key}}]")
kit = types.SimpleNamespace(section=section, state=state, note=note, changes=changes,
                            change_row=change_row, ask=ask)
FEED = [{{"ticker": "LLY", "date": today.isoformat(), "headline": "LLY a high change",
          "significance": "high", "change_type": "status_change"}},
        {{"ticker": "LLY", "date": today.isoformat(), "headline": "LLY a low change",
          "significance": "low"}}]
trading_page.render("http://api.invalid", "LLY", "Eli Lilly", kit, feed=FEED,
                    historical={historical!r})
'''


def _patch_button_group():
    """AppTest's ButtonGroup.indices iterates a single-select value's characters and
    compares raw values with labels (as test_forecast_tab_ui notes). Rebuilt to take a
    scalar as one value and to compare what the frontend would send."""
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


def _page(fail="", historical=False):
    from streamlit.testing.v1 import AppTest
    _patch_button_group()
    test = AppTest.from_string(
        _PAGE.format(frontend=str(FRONTEND), fail=fail, historical=historical),
        default_timeout=60)
    test.run()
    assert not test.exception, test.exception
    return test


def _md(test) -> str:
    return "\n".join(str(m.value) for m in test.markdown)


def _sections(test) -> list:
    return re.findall(r"SECTION\[([^|]+)\|", _md(test))


def test_the_default_board_draws_its_three_panels_for_the_top_bars_company():
    test = _page()
    md = _md(test)
    assert _sections(test) == ["What changed", "Company news", "Dated ahead"]
    assert "SECTION[What changed|2|LLY]" in md and "A high change" in md
    assert "SECTION[Company news|2|LLY]" in md and "Daily pulse (AI summary)" in md
    assert "SECTION[Dated ahead|1|LLY]" in md and "Phase 3 readout of a study" in md


def test_each_panel_leads_with_a_figure_and_folds_its_list_under_it():
    """A panel is not a list. The figure comes first, the named items next, and the
    rows are there for whoever opens the fold."""
    test = _page()
    blocks = [str(m.value) for m in test.markdown]
    figures = [b for b in blocks if 'class="chart-mount stretch td-fig"' in b]
    assert len(figures) == 3 and all("<svg" in b and 'class="unit"' in b for b in figures)
    md = _md(test)
    assert md.count('<details class="note-d td-all">') == 3
    for panel, figure in zip(("What changed", "Company news", "Dated ahead"), figures):
        section = md.index(f"SECTION[{panel}|")
        assert section < md.index(figure) < md.index('<details class="note-d td-all">', section)
    assert 'class="td-leads"' in md and 'class="tiles td-next"' in md
    assert 'class="td-kinds"' in md


def test_the_top_bars_change_feed_is_used_and_not_read_a_second_time():
    test = _page()
    asked = test.session_state["asked"]
    assert not [path for path in asked if path.startswith("/changes")]
    assert sorted(set(asked)) == sorted({"/companies/LLY/news",
                                         next(p for p in asked if p.startswith("/catalysts?"))})
    assert "ticker=LLY" in next(p for p in asked if p.startswith("/catalysts?"))


def test_what_is_on_screen_is_kept_for_the_ask_box_as_kinds_and_tickers_only():
    test = _page()
    assert test.session_state["td_showing"] == [
        {"panel": "changes", "ticker": "LLY"}, {"panel": "news", "ticker": "LLY"},
        {"panel": "catalysts", "ticker": "LLY"}]


def test_taking_a_panel_off_redraws_the_board_without_it():
    test = _page()
    test.button_group(key="td_pick").set_value(["news", "catalysts"]).run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Company news", "Dated ahead"]
    assert test.session_state["td_showing"] == [
        {"panel": "news", "ticker": "LLY"}, {"panel": "catalysts", "ticker": "LLY"}]


def test_an_empty_board_says_what_to_do_next():
    test = _page()
    test.button_group(key="td_pick").set_value([]).run()
    assert not test.exception, test.exception
    assert _sections(test) == [] and "STATE[Nothing on the board|" in _md(test)
    assert test.session_state["td_showing"] == []


def test_the_board_draws_at_one_two_and_three_across():
    test = _page()
    for across in (1, 3, 2):
        test.button_group(key="td_columns").set_value(across).run()
        assert not test.exception, test.exception
        assert _sections(test) == ["What changed", "Company news", "Dated ahead"]


def test_the_ask_box_sits_beside_the_board_in_its_own_place_on_the_page():
    test = _page()
    assert _md(test).count("ASK[LLY|Eli Lilly|td_|td_showing]") == 1
    assert len(test.columns) >= 2


def test_the_ask_box_can_be_put_away_and_the_board_takes_the_width():
    test = _page()
    test.toggle(key="td_ask").set_value(False).run()
    assert not test.exception, test.exception
    assert "ASK[" not in _md(test)
    assert _sections(test) == ["What changed", "Company news", "Dated ahead"]
    test.toggle(key="td_ask").set_value(True).run()
    assert not test.exception, test.exception
    assert _md(test).count("ASK[LLY|Eli Lilly|td_|td_showing]") == 1


def test_a_read_that_fails_is_said_in_its_own_panel_and_the_rest_still_draw():
    test = _page(fail="/news")
    md = _md(test)
    assert _sections(test) == ["What changed", "Company news", "Dated ahead"]
    assert "STATE[The news did not load|" in md and "|True]" in md
    assert "A high change" in md and "Phase 3 readout of a study" in md


def test_with_a_date_set_the_board_says_it_is_the_live_book_and_reads_nothing():
    test = _page(historical=True)
    assert "STATE[The board shows the live book|" in _md(test)
    assert _sections(test) == [] and not test.session_state["asked"]


def test_no_two_widgets_or_containers_on_the_board_share_a_key():
    """A second panel of one kind, or the Ask box drawn beside its own tab, must not
    reuse a key: Streamlit stops the page on the first duplicate."""
    source = (FRONTEND / "trading_page.py").read_text()
    keys = re.findall(r'key=f?"([^"]+)"', source)
    assert keys and all(key.startswith("td_") for key in keys), keys
    fixed = [key for key in keys if "{" not in key]
    assert len(fixed) == len(set(fixed))


def test_the_page_module_only_reads():
    """Every request it builds is a GET: no body, no method, and no write route named."""
    source = (FRONTEND / "trading_page.py").read_text()
    assert not re.search(r"\bmethod\s*=|\bdata\s*=", source)
    assert "broker_t212" not in source and "fetchers" not in source
    assert not re.search(r"/portfolio/|/tearsheet|/brief|/refresh", source)
