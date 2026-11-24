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
# Forty daily bars ending yesterday, and a session still trading today.
PRICES = {{"ticker": "LLY", "interval": "1d", "currency": "USD", "last_fetch_at": None,
           "points": [{{"as_of": (today - dt.timedelta(days=40 - n)).isoformat(),
                        "open": 100.0 + n, "high": 102.0 + n, "low": 99.0 + n,
                        "close": 101.0 + n, "volume": 1000}} for n in range(40)]}}
LIVE = {{"ok": True, "currency": "USD", "fetched_at": "2026-11-23T15:00:00Z", "bars": {{}},
         "live_daily": {{"as_of": today.isoformat(), "open": 141.0, "high": 150.0,
                         "low": 140.0, "close": 149.5, "volume": 10, "complete": False}},
         "market": {{"regular_open": {market_open!r}, "exchange": "NYSE"}}}}
asked = st.session_state.setdefault("asked", [])
FAIL = {fail!r}

def fetch(api_base, path, timeout):
    asked.append(path)
    if FAIL and FAIL in path:
        raise urllib.error.URLError("connection refused")
    if path.endswith("/news"):
        return NEWS
    if path.endswith("/prices"):
        return PRICES
    if path.endswith("/report"):
        return {{"report": {{"period": "Q3 2026"}}, "verdict": "up"}} if {has_report!r} else {{}}
    if path.endswith("/statements?basis=annual"):
        return {{"currency": "USD", "basis": "annual",
                 "snapshot": {{"label": "FY25", "revenue": 45.0}},
                 "trend": [{{"label": f"FY{{20 + n}}", "revenue_growth": 0.05 * n,
                             "net_margin": 0.2 + 0.01 * n}} for n in range(6)]}}
    if path.endswith("/filings"):
        return {{"filings": [{{"form_type": "8-K", "filed_date": today.isoformat(),
                               "title": "Results of operations",
                               "url": "https://www.sec.gov/x.htm"}},
                              {{"form_type": "10-K", "filed_date": "2019-02-01",
                               "title": "10-K", "url": None}}]}}
    if path.endswith("/approvals"):
        return {{"approvals": [{{"brand_name": "Drug", "loe": "2040-01-01",
                                 "approval_date": PRICES["points"][-5]["as_of"]}},
                                {{"brand_name": None, "approval_date": "2026-01-01"}}]}}
    if path.startswith("/catalysts?"):
        return DATED
    if path.startswith("/changes?"):
        return [{{"ticker": "NVO", "date": today.isoformat(), "headline": "NVO a pinned change",
                  "significance": "high"}}]
    raise AssertionError("a read the board was not expected to make: " + path)
fetch.clear = lambda: None
trading_page._fetch = fetch
def live_prices(api_base, company):
    st.session_state.setdefault("live_asked", []).append(company)
    return LIVE
trading_page.live_prices = live_prices
# The saved boards, stood in: a store in the session behind the same two calls.
SAVED = st.session_state.setdefault("saved", {saved!r})
def boards_read(api_base):
    if {boards_fail!r}:
        return {{"boards": {{}}, "current": None,
                 "problem": "Boards cannot be saved or opened: HTTP Error 404: Not Found."}}
    st.session_state.setdefault("boards_read", []).append(1)
    return dict(SAVED, problem=None)
def send(api_base, method, path, body=None):
    st.session_state.setdefault("writes", []).append((method, path, body))
    if method == "PUT":
        if body["name"] == "refuse me":
            raise OSError("That name is not one a board can take.")
        SAVED["boards"][body["name"]] = body["layout"]
        SAVED["current"] = body["name"]
    else:
        SAVED["boards"].pop(urllib.parse.unquote(path.rsplit("/", 1)[1]), None)
        SAVED["current"] = None
    return dict(SAVED, problem=None)
import urllib.parse
real_boards = trading_page.boards
def boards(api_base):
    if trading_page.BOARDS_KEY not in st.session_state:
        st.session_state[trading_page.BOARDS_KEY] = boards_read(api_base)
    return st.session_state[trading_page.BOARDS_KEY]
trading_page.boards = boards
trading_page._send = send
def draw_chart(**kw):
    st.session_state.setdefault("charts", {{}})[kw["key"]] = kw
    st.markdown("CHART[" + kw["key"] + "]")
def board_grid(**kw):
    """The drag frame, stood in: it records what it was handed and returns the place a
    test has put in the session, as the frame returns the reader's last drag."""
    st.session_state.setdefault("grid_args", []).append(kw)
    return st.session_state.get("drag")

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
def report_lead(report):
    st.markdown("LEAD[" + report["report"]["period"] + "]")
def report_landed(report):
    st.markdown("LANDED[" + report["verdict"] + "]")
def snapshot_strip(snapshot):
    return "<div class='tiles'>STRIP[" + snapshot["label"] + "]</div>"
kit = types.SimpleNamespace(section=section, state=state, note=note, changes=changes,
                            change_row=change_row, ask=ask, draw_chart=draw_chart,
                            report_lead=report_lead, report_landed=report_landed,
                            snapshot_strip=snapshot_strip, board_grid=board_grid)
FEED = [{{"ticker": "LLY", "date": today.isoformat(), "headline": "LLY a high change",
          "significance": "high", "change_type": "status_change"}},
        {{"ticker": "LLY", "date": today.isoformat(), "headline": "LLY a low change",
          "significance": "low"}}]
SEED = {layout!r}
if SEED is not None and "seeded" not in st.session_state:
    st.session_state["td_layout"] = SEED
    st.session_state["seeded"] = True
trading_page.render("http://api.invalid", "LLY", "Eli Lilly", kit, feed=FEED,
                    prices=PRICES if {page_has_prices!r} else None,
                    tickers=["LLY", "NVO", "AZN"], historical={historical!r})
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


def _board_of(*kinds):
    """A saved board of the named kinds, each following the top bar."""
    return {"columns": 2, "ask": True,
            "panels": [{"panel": kind, "ticker": None, "wide": None} for kind in kinds]}


def _page(fail="", historical=False, market_open=False, page_has_prices=True,
          has_report=True, layout=None, saved=None, boards_fail=False):
    from streamlit.testing.v1 import AppTest
    _patch_button_group()
    test = AppTest.from_string(
        _PAGE.format(frontend=str(FRONTEND), fail=fail, historical=historical,
                     market_open=market_open, page_has_prices=page_has_prices,
                     has_report=has_report, layout=layout, boards_fail=boards_fail,
                     saved=saved or {"boards": {}, "current": None}),
        default_timeout=60)
    test.run()
    assert not test.exception, test.exception
    return test


def _md(test) -> str:
    return "\n".join(str(m.value) for m in test.markdown)


def _sections(test) -> list:
    return re.findall(r"SECTION\[([^|]+)\|", _md(test))


def test_the_default_board_draws_its_panels_for_the_top_bars_company():
    test = _page()
    md = _md(test)
    assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]
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
    assert md.index("SECTION[Price chart|") < md.index("CHART[td_chart_p1]")
    for panel, figure in zip(("What changed", "Company news", "Dated ahead"), figures):
        section = md.index(f"SECTION[{panel}|")
        assert section < md.index(figure) < md.index('<details class="note-d td-all">', section)
    assert 'class="td-leads"' in md and 'class="tiles td-next"' in md
    assert 'class="td-kinds"' in md


def test_what_the_page_has_already_read_is_used_and_not_read_a_second_time():
    test = _page()
    asked = test.session_state["asked"]
    assert not [path for path in asked if path.startswith("/changes")]
    assert "/companies/LLY/prices" not in asked
    assert sorted(set(asked)) == sorted({"/companies/LLY/news", "/companies/LLY/approvals",
                                         next(p for p in asked if p.startswith("/catalysts?"))})
    assert "ticker=LLY" in next(p for p in asked if p.startswith("/catalysts?"))


def test_what_is_on_screen_is_kept_for_the_ask_box_as_kinds_and_tickers_only():
    test = _page()
    assert test.session_state["td_showing"] == [
        {"panel": "price", "ticker": "LLY"}, {"panel": "changes", "ticker": "LLY"},
        {"panel": "news", "ticker": "LLY"}, {"panel": "catalysts", "ticker": "LLY"}]


def test_taking_a_panel_off_redraws_the_board_without_it():
    test = _page()
    test.button(key="td_off_p1").click().run()           # the price chart
    assert not test.exception, test.exception
    test.button(key="td_off_p2").click().run()           # what changed
    assert not test.exception, test.exception
    # The two left rise to the top row, Dated ahead on the left where What changed was.
    assert _sections(test) == ["Dated ahead", "Company news"]
    assert test.session_state["td_showing"] == [
        {"panel": "catalysts", "ticker": "LLY"}, {"panel": "news", "ticker": "LLY"}]


def test_a_panel_is_added_from_the_menu_for_the_top_bar_or_pinned_to_a_company():
    test = _page(layout=_board_of("news"))
    test.button(key="td_add_filings").click().run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Company news", "Filings"]
    test.selectbox(key="td_add_for").set_value("NVO").run()
    test.button(key="td_add_news").click().run()
    assert not test.exception, test.exception
    md = _md(test)
    assert "SECTION[Company news|2|NVO · pinned]" in md
    assert "/companies/NVO/news" in test.session_state["asked"]
    assert test.session_state["td_showing"][-1] == {"panel": "news", "ticker": "NVO"}


def test_pinning_a_panel_draws_it_for_that_company_and_the_rest_follow_the_top_bar():
    test = _page()
    test.selectbox(key="td_co_p2").set_value("NVO").run()        # what changed
    assert not test.exception, test.exception
    md = _md(test)
    assert "SECTION[What changed|1|NVO · pinned]" in md and "A pinned change" in md
    assert "SECTION[Company news|2|LLY]" in md
    # The page's own feed is the top bar's company's, so the pinned panel reads its own.
    assert [p for p in test.session_state["asked"] if p.startswith("/changes?ticker=NVO")]
    assert {"panel": "changes", "ticker": "NVO"} in test.session_state["td_showing"]
    test.selectbox(key="td_co_p2").set_value("Top bar").run()
    assert "SECTION[What changed|2|LLY]" in _md(test)


def test_two_companies_prices_sit_side_by_side_each_with_its_own_chart_and_live_read():
    test = _page(layout={"columns": 2, "ask": False, "panels": [
        {"panel": "price", "ticker": None, "wide": False},
        {"panel": "price", "ticker": "NVO", "wide": False}]})
    assert not test.exception, test.exception
    assert set(test.session_state["charts"]) == {"td_chart_p1", "td_chart_p2"}
    assert set(test.session_state["live_asked"]) == {"LLY", "NVO"}
    assert "/companies/NVO/prices" in test.session_state["asked"]
    assert "/companies/LLY/prices" not in test.session_state["asked"]
    md = _md(test)
    assert "SECTION[Price chart|None|LLY · USD" in md
    assert "SECTION[Price chart|None|NVO · pinned · USD" in md


def test_a_panel_can_be_moved_from_the_arranger_without_a_pointer():
    test = _page(layout=_board_of("news", "filings", "catalysts"))
    test.button(key="td_down_p1").click().run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Filings", "Company news", "Dated ahead"]
    test.button(key="td_up_p3").click().run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Filings", "Dated ahead", "Company news"]
    held = test.session_state["td_layout"]["panels"]
    assert [p["panel"] for p in held] == ["filings", "catalysts", "news"]
    assert test.button(key="td_up_p2").disabled and test.button(key="td_down_p1").disabled


def test_the_drag_frame_is_handed_every_panels_place_and_the_grids_measure():
    test = _page()
    args = test.session_state["grid_args"][-1]
    assert (args["cols"], args["row_px"], args["gap_px"], args["key"]) == (12, 24, 16,
                                                                           "td_gridctl")
    assert [(p["id"], p["x"], p["y"], p["w"], p["h"]) for p in args["panels"]] == [
        ("p1", 0, 0, 12, 13), ("p2", 0, 13, 6, 9), ("p3", 6, 13, 6, 9), ("p4", 0, 22, 6, 9)]
    md = _md(test)
    assert ".st-key-td_p_p3)" in md and "grid-column:7 / span 6;grid-row:14 / span 9;" in md


def test_a_panel_dragged_and_dropped_takes_its_new_place_once():
    test = _page(layout=_board_of("news", "filings", "catalysts"))
    test.session_state["drag"] = {"token": "t1", "n": 1, "id": "p3", "x": 6, "y": 0,
                                  "w": 6, "h": 12}
    test.run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Company news", "Dated ahead", "Filings"]
    where = {p["id"]: (p["x"], p["y"], p["w"], p["h"])
             for p in test.session_state["td_layout"]["panels"]}
    assert where == {"p1": (0, 0, 6, 9), "p3": (6, 0, 6, 12), "p2": (6, 12, 6, 9)}
    assert test.session_state["grid_args"][-1]["panels"][1]["h"] == 12
    # The frame returns the same drag on every later run. A keyboard move made since
    # must not be undone by it.
    test.button(key="td_up_p2").click().run()
    assert not test.exception, test.exception
    after = [p["panel"] for p in test.session_state["td_layout"]["panels"]]
    assert after != ["news", "catalysts", "filings"]
    test.run()
    assert [p["panel"] for p in test.session_state["td_layout"]["panels"]] == after


def test_a_drag_for_a_panel_no_longer_on_the_board_changes_nothing():
    test = _page(layout=_board_of("news"))
    test.session_state["drag"] = {"token": "t1", "n": 1, "id": "p9", "x": 6, "y": 0,
                                  "w": 6, "h": 9}
    test.run()
    assert not test.exception, test.exception
    assert [(p["id"], p["x"]) for p in test.session_state["td_layout"]["panels"]] == [("p1", 0)]


def test_a_fifth_live_chart_is_refused_and_the_reader_is_told():
    test = _page(layout={"columns": 3, "ask": False, "panels": [
        {"panel": "price", "ticker": t, "wide": False} for t in ("LLY", "NVO", "AZN", "LLY")]})
    test.button(key="td_add_price").click().run()
    assert not test.exception, test.exception
    assert len(test.session_state["td_layout"]["panels"]) == 4
    assert "Left off the board: Price chart: a board holds 4 live panels." in _md(test)


def test_a_board_is_saved_by_name_and_only_its_arrangement_is_sent():
    test = _page(layout=_board_of("news", "filings"))
    test.text_input(key="td_save_name").set_value("Readout prep").run()
    test.button(key="td_save").click().run()
    assert not test.exception, test.exception
    (method, path, body), = test.session_state["writes"]
    assert (method, path) == ("PUT", "/desk/layouts") and body["name"] == "Readout prep"
    assert set(body) == {"name", "layout"}
    assert set(body["layout"]) == {"ask", "panels"}
    assert [p["panel"] for p in body["layout"]["panels"]] == ["news", "filings"]
    assert all(set(p) == {"panel", "ticker", "id", "x", "y", "w", "h"}
               for p in body["layout"]["panels"])
    assert "Saved as Readout prep. It opens next time." in _md(test)
    assert test.session_state["td_board_name"] == "Readout prep"


def test_the_board_that_was_open_last_time_opens_on_the_next_visit():
    saved = {"boards": {"Earnings day": _board_of("results", "filings"),
                        "Other": _board_of("news")}, "current": "Earnings day"}
    test = _page(saved=saved)
    assert not test.exception, test.exception
    assert _sections(test) == ["Latest results", "Filings"]
    assert test.session_state["td_board_name"] == "Earnings day"
    assert len(test.session_state["boards_read"]) == 1         # read once, not on each run
    test.selectbox(key="td_open").set_value("Other").run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Company news"] and "Opened Other." in _md(test)
    assert len(test.session_state["boards_read"]) == 1


def test_a_saved_board_with_a_kind_this_version_lacks_opens_without_it_and_says_so():
    saved = {"boards": {"Old": {"columns": 2, "ask": True, "panels": [
        {"panel": "news"}, {"panel": "crystal_ball"}]}}, "current": "Old"}
    test = _page(saved=saved)
    assert not test.exception, test.exception
    assert _sections(test) == ["Company news"]
    assert "Left off the board: a panel this version does not have: crystal_ball." in _md(test)


def test_deleting_the_open_board_forgets_it_and_leaves_the_panels_up():
    saved = {"boards": {"Earnings day": _board_of("results")}, "current": "Earnings day"}
    test = _page(saved=saved)
    test.button(key="td_delete").click().run()
    assert not test.exception, test.exception
    assert test.session_state["writes"] == [("DELETE", "/desk/layouts/Earnings%20day", None)]
    assert _sections(test) == ["Latest results"] and "Deleted Earnings day." in _md(test)
    assert test.session_state["td_board_name"] is None
    assert test.button(key="td_delete").disabled


def test_a_save_the_api_refuses_is_said_and_a_save_with_no_name_asks_for_one():
    test = _page()
    test.button(key="td_save").click().run()
    assert "Give the board a name to save it." in _md(test)
    assert "writes" not in test.session_state
    test.text_input(key="td_save_name").set_value("refuse me").run()
    test.button(key="td_save").click().run()
    assert not test.exception, test.exception
    assert "Not saved: That name is not one a board can take." in _md(test)
    assert "td_board_name" not in test.session_state


def test_an_api_that_cannot_keep_boards_is_said_and_the_board_still_draws():
    test = _page(boards_fail=True)
    assert not test.exception, test.exception
    assert "Boards cannot be saved or opened" in _md(test)
    assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]
    assert not [b for b in test.button if b.key == "td_save"]


def test_the_default_board_comes_back_at_a_click():
    test = _page(layout=_board_of("filings"))
    test.button(key="td_reset").click().run()
    assert not test.exception, test.exception
    assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]


def test_an_empty_board_says_what_to_do_next():
    test = _page(layout=_board_of())
    assert not test.exception, test.exception
    assert _sections(test) == [] and "STATE[Nothing on the board|" in _md(test)
    assert test.session_state["td_showing"] == []


def test_the_board_is_laid_out_afresh_one_two_or_three_across():
    test = _page()
    for across in (1, 3, 2):
        test.button(key=f"td_across_{across}").click().run()
        assert not test.exception, test.exception
        assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]
        widths = [p["w"] for p in test.session_state["td_layout"]["panels"]]
        assert widths == [12] + [12 // across] * 3


def test_the_ask_box_sits_beside_the_board_in_its_own_place_on_the_page():
    test = _page()
    assert _md(test).count("ASK[LLY|Eli Lilly|td_|td_showing]") == 1
    assert len(test.columns) >= 2


def test_the_ask_box_can_be_put_away_and_the_board_takes_the_width():
    test = _page()
    test.toggle(key="td_ask").set_value(False).run()
    assert not test.exception, test.exception
    assert "ASK[" not in _md(test)
    assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]
    test.toggle(key="td_ask").set_value(True).run()
    assert not test.exception, test.exception
    assert _md(test).count("ASK[LLY|Eli Lilly|td_|td_showing]") == 1


def test_the_price_chart_keeps_its_height_and_carries_the_session_still_trading():
    test = _page()
    assert "CHART[td_chart_p1]" in _md(test)
    chart = test.session_state["charts"]["td_chart_p1"]
    # The default price panel is 13 rows: 504 px, of which the chart takes all but what
    # the panel draws round it.
    assert chart["fill"] is False and chart["height"] == 504 - 196 and chart["intraday"] is False
    assert chart["lines"] == [] and chart["draw_mode"] is False and chart["fair"] == []
    # Forty stored bars and today's session laid over them: the last point is the live one.
    assert len(chart["data"]) == 41 and chart["data"][-1]["value"] == 149.5
    assert chart["data"][-2]["value"] == 140.0
    assert len(chart["markers"]) == 1                 # the approval; the LOE is off the view
    md = _md(test)
    assert "SECTION[Price chart|None|LLY · USD" in md
    assert "149.50" in md and "1Y change" in md and "+48.0%" in md
    assert "is live: the session so far" in md and "not a close" in md
    assert "writes nothing to the book" in md


def test_a_shorter_window_draws_fewer_bars_and_tells_the_chart_to_refit():
    test = _page()
    before = test.session_state["charts"]["td_chart_p1"]
    test.button_group(key="td_span_p1").set_value("1M").run()
    assert not test.exception, test.exception
    after = test.session_state["charts"]["td_chart_p1"]
    assert len(after["data"]) < len(before["data"]) and after["data"][-1]["value"] == 149.5
    assert after["view_key"] != before["view_key"] and "1M change" in _md(test)
    test.button_group(key="td_view_p1").set_value("Candlestick").run()
    assert not test.exception, test.exception
    candle = test.session_state["charts"]["td_chart_p1"]
    assert candle["mode"] == "Candlestick" and "open" in candle["data"][0]


def test_the_price_panel_reads_the_history_itself_when_the_page_has_not():
    test = _page(page_has_prices=False)
    assert "/companies/LLY/prices" in test.session_state["asked"]
    assert len(test.session_state["charts"]["td_chart_p1"]["data"]) == 41


def test_the_price_panel_draws_with_the_market_open_and_with_it_closed():
    for market_open in (True, False):
        test = _page(market_open=market_open)
        assert not test.exception, test.exception
        assert "CHART[td_chart_p1]" in _md(test)
        assert set(test.session_state["live_asked"]) == {"LLY"}


def test_with_no_price_history_the_panel_says_so_and_draws_no_chart():
    test = _page(fail="/prices", page_has_prices=False)
    md = _md(test)
    assert "STATE[The price history did not load|" in md and "CHART[" not in md
    assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]


FISCAL = ["results", "trend", "filings"]


def test_the_fiscal_panels_are_drawn_by_the_financials_tabs_own_builders():
    test = _page(layout=_board_of(*FISCAL))
    assert not test.exception, test.exception
    md = _md(test)
    assert _sections(test) == ["Latest results", "Growth and margin", "Filings"]
    assert "LEAD[Q3 2026]" in md and "LANDED[up]" in md
    assert "SECTION[Growth and margin|None|LLY · FY25 · USD]" in md and "STRIP[FY25]" in md
    figures = [str(m.value) for m in test.markdown if "td-fig" in str(m.value)]
    assert len(figures) == 2                       # the trend's lines and the filings' grid
    assert "<polyline" in figures[0] and 'class="unit"' in figures[1]
    assert "SECTION[Filings|2|LLY]" in md and "1 older filing is in the list" in md
    assert test.session_state["td_showing"] == [
        {"panel": panel, "ticker": "LLY"} for panel in FISCAL]


def test_a_company_with_no_report_is_told_what_is_missing_and_shown_no_figure():
    test = _page(has_report=False, layout=_board_of("results"))
    assert not test.exception, test.exception
    md = _md(test)
    assert "STATE[No report on file for LLY|" in md and "no free data" in md
    assert "LEAD[" not in md and "LANDED[" not in md


def test_a_read_that_fails_is_said_in_its_own_panel_and_the_rest_still_draw():
    test = _page(fail="/news")
    md = _md(test)
    assert _sections(test) == ["Price chart", "What changed", "Company news", "Dated ahead"]
    assert "STATE[The news did not load|" in md and "|True]" in md
    assert "A high change" in md and "Phase 3 readout of a study" in md


def test_with_a_date_set_the_board_says_it_is_the_live_book_and_reads_nothing():
    test = _page(historical=True)
    assert "STATE[The board shows the live book|" in _md(test)
    assert _sections(test) == [] and not test.session_state["asked"]
    assert "live_asked" not in test.session_state


def test_no_two_widgets_or_containers_on_the_board_share_a_key():
    """A second panel of one kind, or the Ask box drawn beside its own tab, must not
    reuse a key: Streamlit stops the page on the first duplicate."""
    source = (FRONTEND / "trading_page.py").read_text()
    keys = re.findall(r'(?<![a-z_])key=f?"([^"]+)"', source)
    assert keys and all(key.startswith("td_") for key in keys), keys
    fixed = [key for key in keys if "{" not in key]
    assert len(fixed) == len(set(fixed))


def test_the_page_module_only_reads():
    """Every request it builds is a GET: no body, no method, and no write route named."""
    import ast
    source = (FRONTEND / "trading_page.py").read_text()
    tree = ast.parse(source)
    # One place builds a request that can carry a body: _send, the board saving its own
    # arrangement. Every other call is urlopen on an address, which is a GET.
    built = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and getattr(node.func, "attr", "") == "Request"]
    assert len(built) == 1
    sender = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_send")
    assert built[0] in list(ast.walk(sender))
    sent = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "_send"]
    assert len(sent) == 2
    for call in sent:                        # a PUT and a DELETE, both to the boards
        assert call.args[1].value in ("PUT", "DELETE")
        assert "BOARDS_PATH" in ast.unparse(call.args[2])
    assert 'BOARDS_PATH = "/desk/layouts"' in source
    opened = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and getattr(node.func, "attr", "") == "urlopen"]
    for call in opened:
        assert len(call.args) == 1 and {kw.arg for kw in call.keywords} == {"timeout"}
    assert "broker_t212" not in source and "fetchers" not in source
    assert not re.search(r"/portfolio/|/tearsheet|/brief|/refresh", source)


def test_the_chart_component_has_a_height_it_keeps():
    """On its own tab the chart grows to the window. In a panel it must not."""
    component = FRONTEND / "components" / "drawchart"
    wrapper = (component / "__init__.py").read_text()
    frame = (component / "index.html").read_text()
    assert "fill: bool = True" in wrapper and "fill=fill" in wrapper
    assert "state.fill = a.fill !== false;" in frame
    assert "if (state.fill === false) return floor;" in frame
    # Fitted again when its width changes, and only in a panel: drawn in a hidden tab it
    # is a few pixels wide, and the bars stayed bunched at the right edge.
    assert "if (state.fill !== false || !chart) return;" in frame
    assert frame.count("refit();") == 2


def test_the_drag_frame_draws_only_in_its_own_layer_and_sends_a_place_a_drag_at_a_time():
    """The frame's script is not run here (node is not installed on every machine), so
    what it may do is held by reading it: it adds to the page one layer of its own and
    nothing to what Streamlit draws, it sends a place only on release and marks each with
    the frame's token and a count, and it takes its layer and listeners away with it."""
    frame = (FRONTEND / "components" / "boardgrid" / "index.html").read_text()
    script = frame.split("<script>", 1)[1]
    # Every element it adds goes into its own layer, and the layer onto the page's body.
    added = re.findall(r"([\w.]+)\.appendChild\(", script)
    assert added and set(added) <= {"layer", "doc.body"}, added
    assert "doc.body.appendChild(layer)" in script
    assert "insertBefore" not in script and "innerHTML" not in script
    assert ".remove()" in script and 'addEventListener("pagehide", cleanup)' in script
    assert script.count("Streamlit.value(") == 1
    assert "token: TOKEN, n: sent" in script
    assert 'zIndex: "110"' in script                         # under the top bar's 120
    wrapper = (FRONTEND / "components" / "boardgrid" / "__init__.py").read_text()
    assert "default=None" in wrapper and 'declare_component("boardgrid"' in wrapper


def test_the_frame_measures_the_grid_the_stylesheet_and_the_model_describe():
    frame = (FRONTEND / "components" / "boardgrid" / "index.html").read_text()
    source = (FRONTEND / "trading_page.py").read_text()
    assert "cols=TV.GRID_COLS" in source and "row_px=TV.ROW_PX" in source
    assert "gap_px=TV.GAP_PX" in source
    assert '.querySelector(".st-key-td_grid")' in frame
    assert '".st-key-td_p_" + id' in frame and 'key=f"td_p_{entry[\'id\']}"' in source
