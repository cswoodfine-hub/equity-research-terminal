"""The Trading tab, drawn: a board of panels the reader picks, for the top bar's company.

``trading_view`` holds what a board is and builds the markup; this module is the
Streamlit side, kept out of streamlit_app.py so the change there stays the tab and the
call. The house's own helpers (the section rule, the state block, the change feed's row)
come in as ``kit``, the way ``catalysts_page`` takes the gate builders, so a panel here
reads the same as the page it was lifted from.

Two rules the page is built around:

- The app runs every tab on every rerun, so a board nobody is looking at must cost next
  to nothing. Every read goes through one reader held for a minute (``_fetch``), and the
  board is a fragment: a click on it redraws the board and not the other tabs.
- The board reads. It has no control that writes to the book, places an order or reaches
  the broker, and ``test_trading_page_ui.py`` reads this file to hold it there.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

import calendar_view
import price_chart
import trading_view as TV
import trend
from components import tokens as TK

# Bumped when the page's calls change: a server running from a worktree does not
# re-import a module under a dot-directory, so streamlit_app reloads one behind this.
REVISION = 7

PANEL_HEIGHT = 340           # a panel's body; past it the panel scrolls, not the page
CALENDAR_MONTHS = 24         # the span a readout calendar is read over, as on Catalysts
HOLD_SECONDS = 60
CHANGE_LEVELS = ("high", "medium", "low")
CHANGES_SHOWN = 40
# The board against the Ask column beside it: about two thirds to one, which leaves the
# box the measure its answers are set at and the board room for two panels across.
BESIDE = (2.05, 1)
ASK_SLOT = "td_"             # the Ask box's second place on the page (see _ask_tab)
SHOWING_KEY = "td_showing"   # where the session holds what is on the board, for the box
PRICE_HEIGHT = 300           # the chart in a panel: fixed, so the panels under it stay put
LIVE_TIMEOUT_S = 12


@st.cache_data(ttl=HOLD_SECONDS, show_spinner=False)
def _fetch(api_base: str, path: str, timeout: int):
    """One GET of the API, held a minute. A failure raises and is never held, so the
    next run asks again."""
    with urllib.request.urlopen(api_base.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def read(api_base: str, path: str, timeout: int = 30) -> tuple:
    """(the payload, None), or (None, why it could not be read). Never raises: a panel
    whose read fails says so in its own space and the rest of the board still draws."""
    try:
        return _fetch(api_base, path, timeout), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(exc).rstrip(".")


def clear() -> None:
    """Drop every held read. Called where the app knows the book has changed."""
    _fetch.clear()


# --------------------------------------------------------------------------- the panels
# Each takes the API's address, the company the panel is for, the kit, the panel's rule
# (label and basis), its slot on the board, the width its figure is drawn at, and what
# the page has already read for this company (``have``: its change feed and its stored
# prices, where the company is the top bar's, so those cost the board no read). Each
# draws its rule first, so the count beside it is the count of what is under it.
#
# A panel leads with a figure: when and how much, read at a glance. The few items worth
# naming sit under it, and the whole list is folded beneath, one click away.
def _body(slot: str):
    return st.container(height=PANEL_HEIGHT, border=False, key=f"td_body_{slot}")


def _failed(kit, what: str, problem: str) -> None:
    kit.state(f"{what} did not load", TV.esc(problem), error=True)


def _figure(svg: str) -> None:
    if svg:
        st.markdown(f'<div class="chart-mount stretch td-fig">{svg}</div>',
                    unsafe_allow_html=True)


def _changes(api_base, company, kit, rule, slot, width, have):
    label, basis = rule
    feed, problem = have.get("feed"), None
    if feed is None:
        feed, problem = read(api_base, f"/changes?ticker={urllib.parse.quote(company)}")
    today = dt.date.today()
    rows = kit.changes(feed or [], company, today, CHANGE_LEVELS)
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The change feed", problem)
        elif not rows:
            kit.state(f"Nothing detected for {TV.esc(company)} in {TV.CHANGE_DAYS} days",
                      "The book records a change when two refreshes differ. None has.")
        else:
            _figure(TV.changes_figure(rows, today, width))
            st.markdown(TV.kinds_html(rows) + TV.changes_leads(rows, company)
                        + TV.fold_html(
                            f"The list: {min(len(rows), CHANGES_SHOWN)} of {len(rows)}, "
                            "newest first",
                            '<div class="feed td-list">'
                            + "".join(kit.change_row(it) for it in rows[:CHANGES_SHOWN])
                            + "</div>"),
                        unsafe_allow_html=True)
            kit.note(f"A square is one change the book detected between two refreshes, on "
                     f"the day it was detected and in the row of its rating, over "
                     f"{TV.CHANGE_DAYS} days. Hover a square for what it was. The three "
                     "named are the highest rated, newest first. What is dated ahead is "
                     "on the Dated ahead panel.")


def _news(api_base, company, kit, rule, slot, width, have):
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/news")
    rows = TV.news_rows(payload)
    today = dt.date.today()
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The news", problem)
        elif not rows:
            kit.state(f"No news on file for {TV.esc(company)}",
                      "Company releases, 8-K headlines, the FDA's feeds and the daily "
                      "pulse are read on each refresh. None names this company yet.")
        else:
            figure = TV.news_figure(rows, today, width)
            _figure(figure)
            st.markdown(TV.news_leads(rows)
                        + TV.fold_html(f"The list: {TV.news_basis(rows)}",
                                       TV.news_html(rows)),
                        unsafe_allow_html=True)
            older = TV.news_older(rows, today)
            kit.note((f"A square is one item, in the month it was published and the row "
                      f"of its source, over {TV.NEWS_MONTHS} months. "
                      if figure else
                      f"Nothing on file is from the last {TV.NEWS_MONTHS} months, so no "
                      "figure is drawn. ")
                     + (f"{older} older {'item is' if older == 1 else 'items are'} in the "
                        "list and not on the figure. " if older else "")
                     + "The three named are the newest, and each opens its source. Pulse "
                       "(AI) is the daily pulse, a model's summary of the trade press that "
                       "links the article it summarises; it moves no value, deal term or "
                       "catalyst.")


def _catalysts(api_base, company, kit, rule, slot, width, have):
    label, basis = rule
    payload, problem = read(
        api_base, f"/catalysts?within_days={CALENDAR_MONTHS * 31}"
                  f"&ticker={urllib.parse.quote(company)}")
    listed = payload if isinstance(payload, list) else []
    today = dt.date.today()
    rows = TV.dated_rows(calendar_view.within(listed, CALENDAR_MONTHS, today))
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The calendar", problem)
        elif not rows:
            kit.state(f"Nothing dated for {TV.esc(company)} in the next "
                      f"{CALENDAR_MONTHS} months", calendar_view.SOURCES)
        else:
            _figure(TV.dated_figure(rows, today, CALENDAR_MONTHS, width))
            st.markdown(TV.dated_next(rows, today)
                        + TV.fold_html(f"The list: {TV.dated_basis(rows, CALENDAR_MONTHS)}, "
                                       "soonest first", TV.dated_html(rows)),
                        unsafe_allow_html=True)
            kit.note("A square is one dated event, in its month and in the row of its "
                     "phase, which is read from the start of its registry title. "
                     + calendar_view.caption(listed, CALENDAR_MONTHS, today)
                     + " A date here is the registry's or the filing's, not a "
                       "commitment. The odds and the value at stake are on Catalysts.")


def _results(api_base, company, kit, rule, slot, width, have):
    """The last reported period, drawn by the Financials tab's own builders."""
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/report")
    report = payload if (payload or {}).get("report") else None
    kit.section(label, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The report", problem)
        elif not report:
            kit.state(f"No report on file for {TV.esc(company)}",
                      "A report is built when a results release and the street's "
                      "estimates for the same period are both on file. "
                      f"For this company one of them is {TV.NO_DATA}.")
        else:
            kit.report_lead(report)
            kit.report_landed(report)


def _trend(api_base, company, kit, rule, slot, width, have):
    """Growth and margin by year as two lines, under the latest period's figures."""
    label, basis = rule
    built, problem = read(
        api_base, f"/companies/{urllib.parse.quote(company)}/statements?basis=annual")
    built = built or {}
    points, snapshot = built.get("trend") or [], built.get("snapshot") or {}
    kit.section(label, basis=" · ".join(part for part in (
        basis, snapshot.get("label"), built.get("currency")) if part))
    with _body(slot):
        figure = trend.render(points, "annual")
        if problem:
            _failed(kit, "The statements", problem)
        elif not figure and not snapshot:
            kit.state(f"No statements on file for {TV.esc(company)}",
                      "Filed financials are read on each refresh. Two periods are "
                      "needed before a trend can be drawn.")
        else:
            if snapshot:
                st.markdown(kit.snapshot_strip(snapshot), unsafe_allow_html=True)
            _figure(figure)
            if figure:
                kit.note(TV.esc(trend.caption(points, "annual"))
                         + " Filed figures by fiscal year. A year missing a figure "
                           "breaks that line there. The statements in full are on "
                           "Financials.")


def _filings(api_base, company, kit, rule, slot, width, have):
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/filings")
    rows = TV.filings_rows(payload)
    today = dt.date.today()
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The filings", problem)
        elif not rows:
            kit.state(f"No filings on file for {TV.esc(company)}",
                      "Filings are read from EDGAR on each refresh. A company outside "
                      "the SEC files none there.")
        else:
            figure = TV.filings_figure(rows, today, width)
            _figure(figure)
            st.markdown(TV.filings_leads(rows)
                        + TV.fold_html(f"The list: {TV.filings_basis(rows)}",
                                       TV.filings_html(rows)),
                        unsafe_allow_html=True)
            older = TV.filings_older(rows, today)
            kit.note((f"A square is one filing, in the month it was filed and the row of "
                      f"its form, over {TV.FILING_MONTHS} months. An annual report is "
                      "filled and a quarterly one an outline. "
                      if figure else
                      f"Nothing was filed in the last {TV.FILING_MONTHS} months, so no "
                      "figure is drawn. ")
                     + (f"{older} older {'filing is' if older == 1 else 'filings are'} in "
                        "the list and not on the figure. " if older else "")
                     + "The three named are the newest, and each opens on EDGAR.")


def live_prices(api_base: str, company: str) -> dict:
    """Yahoo's live read for one company, or the reason there is none. Never raises, and
    never held here: the API holds the answer for about a minute and writes nothing, so
    asking it again costs nothing and files no price."""
    path = f"/companies/{urllib.parse.quote(company)}/prices/live"
    try:
        with urllib.request.urlopen(api_base.rstrip("/") + path,
                                    timeout=LIVE_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "reason": f"the API did not answer: {exc}", "bars": {},
                "live_daily": None, "market": None, "fetched_at": None}


def _price(api_base, company, kit, rule, slot, width, have):
    """The daily price with the live session over it, at a fixed height.

    The same builders as the Prices tab (``price_chart``) in a smaller frame: daily bars
    only, a window, line or candle, and the approvals marked. The intraday views, the
    fair value line and why it moved stay on the Prices tab, which is their page.
    """
    label, basis = rule
    # The timer belongs to the chart alone, so a tick redraws one chart and not the
    # board. It is set from the market's state when the panel is drawn: a minute while
    # the session is open, the wait for the bell when that is near, and none otherwise.
    timer = price_chart.poll_seconds(live_prices(api_base, company))

    @st.fragment(run_every=timer)
    def chart():
        stored, problem = have.get("prices"), None
        if stored is None:
            stored, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/prices")
        stored = stored or {}
        live = live_prices(api_base, company)
        kit.section(label, basis=" · ".join(part for part in (
            basis, stored.get("currency") or live.get("currency"),
            price_chart.live_status(live)) if part))
        with st.container(key=f"td_pricectl_{slot}", horizontal=True,
                          vertical_alignment="center"):
            span = st.segmented_control(
                "Window", [name for name, _days in TV.PRICE_SPANS], default=TV.DEFAULT_SPAN,
                key=f"td_span_{slot}", label_visibility="collapsed") or TV.DEFAULT_SPAN
            view = st.segmented_control(
                "View", [price_chart.LINE, price_chart.CANDLE], default=price_chart.LINE,
                key=f"td_view_{slot}", label_visibility="collapsed") or price_chart.LINE
        points = stored.get("points") or []
        over = ([live["live_daily"]] if price_chart.live_daily_applies(
            points, live.get("live_daily"), stored.get("last_fetch_at")) else [])
        bars = TV.price_window(price_chart.merge_live(points, over), span)
        if problem:
            _failed(kit, "The price history", problem)
            return
        if not bars:
            kit.state(f"No price history for {TV.esc(company)} yet",
                      "Refresh all, in the top bar, files the daily history from Yahoo. "
                      "The live read returned no bar to draw in the meantime: "
                      f"{TV.esc(str(live.get('reason') or TV.NO_DATA))}.")
            return
        st.markdown(TV.price_stats_html(TV.price_stats(bars), span), unsafe_allow_html=True)
        approvals, _problem = read(
            api_base, f"/companies/{urllib.parse.quote(company)}/approvals")
        markers = price_chart.event_markers(
            bars, TV.price_events((approvals or {}).get("approvals")), False)
        kit.draw_chart(
            data=price_chart.series_data(bars, view, False), markers=markers, fair=[],
            mode=view, intraday=False, lines=[], draw_mode=False,
            theme={"ground": TK.GROUND, "muted": TK.MUTED, "rule": TK.GROUND,
                   "rule_strong": TK.RULE_STRONG, "up": TK.UP, "down": TK.DOWN,
                   "flag": TK.FLAG},
            gutter=0, view_key=f"{company}|{span}|{view}", height=PRICE_HEIGHT,
            fill=False, key=f"td_chart_{slot}")
        legend = (f'<span style="color:var(--up)">▲</span> FDA approval &nbsp;'
                  f'<span style="color:var(--down)">▼</span> loss of exclusivity '
                  f'&nbsp;·&nbsp; {len(markers)} on this view')
        words = price_chart.live_bar_words(live, "1d", over, points)
        if words:
            legend += f" &nbsp;·&nbsp; {TV.esc(words)}"
        st.markdown(f'<div class="byline chart-legend">{legend}</div>',
                    unsafe_allow_html=True)
        kit.note(TV.esc(price_chart.live_note(live))
                 + "Daily bars from the book's stored history, with the current session "
                   "from Yahoo's live read laid over them where the stored series does "
                   "not yet hold that day's close. The live read writes nothing to the "
                   "book. Intraday bars, the fair value line and why the price moved "
                   "are on the Prices tab.")

    chart()


DRAW = {"price": _price, "changes": _changes, "news": _news, "results": _results,
        "trend": _trend, "filings": _filings, "catalysts": _catalysts}


# ----------------------------------------------------------------------------- the board
# The board is one value in the session, ``td_layout``: its panels in order, each with
# the company it is pinned to if any, how many sit across, and whether the Ask box is
# beside it. Every control below changes that value through a callback, which Streamlit
# runs before the page is drawn, so the board is always drawn from the value as it
# stands. A widget's own state is set from it on every run and is never the record.
LAYOUT_KEY = "td_layout"
FOLLOW = "Top bar"


def layout() -> dict:
    """The board as it stands, made safe to draw."""
    held = st.session_state.get(LAYOUT_KEY)
    clean, _left_out = TV.normalise(held if held is not None else TV.default_layout())
    st.session_state[LAYOUT_KEY] = clean
    return clean


def _keep(new: dict, left_out=None) -> None:
    clean, dropped = TV.normalise(new)
    st.session_state[LAYOUT_KEY] = clean
    st.session_state["td_left_out"] = list(left_out or []) + dropped


def _add(kind: str) -> None:
    chosen = st.session_state.get("td_add_for", FOLLOW)
    new, left_out = TV.added(layout(), kind, None if chosen == FOLLOW else chosen)
    _keep(new, left_out)


def _remove(index: int) -> None:
    _keep(TV.removed(layout(), index))


def _move(index: int, step: int) -> None:
    _keep(TV.moved(layout(), index, step))


def _pin(index: int) -> None:
    chosen = st.session_state.get(f"td_co_{index}", FOLLOW)
    _keep(TV.changed(layout(), index, ticker=None if chosen == FOLLOW else chosen))


def _widen(index: int) -> None:
    _keep(TV.changed(layout(), index, wide=st.session_state.get(f"td_wide_{index}")))


def _across() -> None:
    _keep(dict(layout(), columns=st.session_state.get("td_columns") or TV.DEFAULT_COLUMNS))


def _beside() -> None:
    _keep(dict(layout(), ask=bool(st.session_state.get("td_ask"))))


def _reset() -> None:
    _keep(TV.default_layout())


def _show(key: str, value) -> None:
    """Set a widget to what the board holds, before the widget is drawn."""
    st.session_state[key] = value


def _add_menu(tickers) -> None:
    """Every kind of panel, by group, and the company the next one is for."""
    with st.popover("Add panel"):
        st.selectbox("For", [FOLLOW] + list(tickers or []), key="td_add_for",
                     help="The company the panel is drawn for. Top bar follows the "
                          "company picked at the top of the page; a ticker pins it.")
        for group, kinds in TV.picker_options():
            st.markdown(f'<div class="td-group">{TV.esc(group)}</div>',
                        unsafe_allow_html=True)
            # Not "td_add_<group>": a group and a kind can share a name (News, news).
            slug = "".join(ch if ch.isalnum() else "_" for ch in group.lower())
            with st.container(key=f"td_kinds_{slug}", horizontal=True):
                for kind in kinds:
                    st.button(kind["title"], key=f"td_add_{kind['id']}", help=kind["about"],
                              on_click=_add, args=(kind["id"],))


def _arrange_menu(board: dict, ticker: str, tickers) -> None:
    """The board's panels as rows: whose each is, how wide, where it sits, and off."""
    panels = board["panels"]
    with st.popover("Arrange", disabled=not panels):
        last = len(panels) - 1
        for i, entry in enumerate(panels):
            options = [FOLLOW] + list(tickers or [])
            if entry.get("ticker") and entry["ticker"] not in options:
                options.append(entry["ticker"])
            name, co, wide, up, down, off = st.columns([2.6, 2.0, 1.1, 0.6, 0.6, 0.6],
                                                       vertical_alignment="center")
            name.markdown(f'<div class="td-arr">{TV.esc(TV.BY_ID[entry["panel"]]["title"])}'
                          "</div>", unsafe_allow_html=True)
            _show(f"td_co_{i}", entry.get("ticker") or FOLLOW)
            co.selectbox("Company", options, key=f"td_co_{i}", label_visibility="collapsed",
                         on_change=_pin, args=(i,))
            _show(f"td_wide_{i}", TV.is_wide(entry))
            wide.toggle("Wide", key=f"td_wide_{i}", on_change=_widen, args=(i,))
            up.button("↑", key=f"td_up_{i}", disabled=i == 0, help="Earlier on the board",
                      on_click=_move, args=(i, -1))
            down.button("↓", key=f"td_down_{i}", disabled=i == last,
                        help="Later on the board", on_click=_move, args=(i, 1))
            off.button("×", key=f"td_off_{i}", help="Take it off the board",
                       on_click=_remove, args=(i,))
        st.button("Back to the default board", key="td_reset", on_click=_reset)


def _controls(board: dict, ticker: str, tickers) -> None:
    """The row above the board: add a panel, arrange them, how many across, and whether
    the Ask box sits beside them."""
    with st.container(key="td_controls", horizontal=True, vertical_alignment="center"):
        _add_menu(tickers)
        _arrange_menu(board, ticker, tickers)
        _show("td_columns", board["columns"])
        st.segmented_control(
            "Columns", list(TV.COLUMNS), key="td_columns", on_change=_across,
            format_func=lambda n: f"{n} across", label_visibility="collapsed",
            help="How many panels sit side by side.")
        _show("td_ask", board["ask"])
        st.toggle("Ask beside", key="td_ask", on_change=_beside,
                  help="The Ask box in a column beside the board. It is the same "
                       "conversation as the Ask tab's, kept per company.")


@st.fragment
def _board(api_base: str, ticker: str, kit, page: dict, tickers) -> None:
    """The controls and the panels. A fragment: a change to the board redraws the board
    alone."""
    board = layout()
    _controls(board, ticker, tickers)
    # The Ask column is laid out by the page, outside this fragment, so a run of the
    # fragment alone cannot add or remove it. When the switch no longer matches what the
    # page drew, the page is run once to draw it.
    if board["ask"] != st.session_state.get("_td_ask_drawn", board["ask"]):
        st.rerun()
    # What the Ask box may be told is on screen. Kept in the session and read when a
    # question is sent, so it is the board as it stands and not as it stood at the last
    # full run of the page.
    st.session_state[SHOWING_KEY] = TV.showing(board["panels"], ticker)
    left_out = st.session_state.pop("td_left_out", None)
    if left_out:
        st.markdown(TV.left_out_html(left_out), unsafe_allow_html=True)
    if not board["panels"]:
        kit.state("Nothing on the board", "Add a panel from the row above.")
        return
    for r, row in enumerate(TV.pack(board["panels"], board["columns"])):
        alone = len(row) == 1 and (board["columns"] == 1 or TV.is_wide(row[0]))
        cells = [st.container()] if alone else st.columns(board["columns"], gap="medium")
        width = TV.figure_width(1 if alone else board["columns"], board["ask"])
        for c, entry in enumerate(row):
            company = TV.company_of(entry, ticker)
            with cells[c], st.container(key=f"td_panel_{r}_{c}"):
                DRAW[entry["panel"]](
                    api_base, company, kit, TV.heading(entry, ticker), f"{r}_{c}", width,
                    page if company == ticker else {})


def render(api_base: str, ticker: str, name: str, kit, feed=None, prices=None,
           tickers=None, historical: bool = False) -> None:
    """The tab. ``feed`` and ``prices`` are the change feed and the stored daily prices
    the page already read for this company, so the panels built on them cost no read.
    ``tickers`` are the companies a panel can be pinned to."""
    if historical:
        kit.state("The board shows the live book",
                  "A date is set in the sidebar, and the board's panels are not rebuilt "
                  "for a past date. Clear the date to use it.")
        return
    page = {key: value for key, value in (("feed", feed), ("prices", prices))
            if value is not None}
    beside = layout()["ask"]
    st.session_state["_td_ask_drawn"] = beside
    if not beside:
        _board(api_base, ticker, kit, page, tickers)
        return
    board, ask = st.columns(list(BESIDE), gap="medium")
    with board:
        _board(api_base, ticker, kit, page, tickers)
    with ask:
        kit.ask(api_base, ticker, name, slot=ASK_SLOT, showing_key=SHOWING_KEY)
