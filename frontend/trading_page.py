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
  the broker, and ``test_trading_page_ui.py`` reads this file to hold it there. Its one
  write is its own arrangement, saved by name through ``/desk/layouts`` to a file beside
  the book.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

import price_chart
import trading_view as TV
import trend
from components import tokens as TK

# Bumped when the page's calls change: a server running from a worktree does not
# re-import a module under a dot-directory, so streamlit_app reloads one behind this.
REVISION = 13

HOLD_SECONDS = 60
SHOWING_KEY = "td_showing"   # where the session holds what is on the board, for the box
# What the price panel draws round its chart: the rule, the line of the window's control
# and its figures, the legend and the notes. The chart takes the rest of the panel.
PRICE_CHROME = 128
PRICE_MIN = 140
PRICE_UNDER = 44               # the legend and the notes' handle, under the chart
HEAVY_TIMEOUT_S = 8            # a read that runs the forecast, waited for this long
LIVE_TIMEOUT_S = 12


@st.cache_data(ttl=HOLD_SECONDS, show_spinner=False)
def _fetch(api_base: str, path: str, timeout: int):
    """One GET of the API, held a minute. A failure raises and is never held, so the
    next run asks again."""
    with urllib.request.urlopen(api_base.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


FAIL_HOLD_S = 30


def read(api_base: str, path: str, timeout: int = 30) -> tuple:
    """(the payload, None), or (None, why it could not be read). Never raises: a panel
    whose read fails says so in its own space and the rest of the board still draws.

    A failure is held for half a minute. A heavy read on a cold book (the street's view
    runs the forecast) can take a minute or two; asked again on every click it would
    stack one wait behind another, and the API finishes the first one regardless."""
    held = st.session_state.setdefault("_td_failed", {})
    failed = held.get((api_base, path))
    if failed and time.monotonic() - failed[0] < FAIL_HOLD_S:
        return None, failed[1]
    try:
        return _fetch(api_base, path, timeout), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = str(exc).rstrip(".")
        held[(api_base, path)] = (time.monotonic(), reason)
        return None, reason


def clear() -> None:
    """Drop every held read. Called where the app knows the book has changed."""
    _fetch.clear()


# --------------------------------------------------------------------------- the panels
# Each takes the API's address, the company the panel is for, the kit, the panel's rule
# (label and basis), its id on the board, its frame (the width its figure is drawn at
# and its height in grid rows), and what the page has already read for this company
# (``have``: its change feed and its stored prices, where the company is the top bar's,
# so those cost the board no read). Each draws its rule first, so the count beside it is
# the count of what is under it.
#
# A panel leads with a figure: when and how much, read at a glance. The few items worth
# naming sit under it, and the whole list is folded beneath, one click away.
def _body(slot: str, frame: dict):
    """The panel's body, as tall as the panel is made less its rule. Past it the body
    scrolls, not the page."""
    return st.container(height=TV.body_px(frame["h"]), border=False, key=f"td_body_{slot}")


def _failed(kit, what: str, problem: str) -> None:
    kit.state(f"{what} did not load", TV.esc(problem), error=True)


def _figure(svg: str) -> None:
    if svg:
        st.markdown(f'<div class="chart-mount stretch td-fig">{svg}</div>',
                    unsafe_allow_html=True)


def _news(api_base, company, kit, rule, slot, frame, have):
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/news")
    rows = TV.news_rows(payload)
    today = dt.date.today()
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot, frame):
        if problem:
            _failed(kit, "The news", problem)
        elif not rows:
            kit.state(f"No news on file for {TV.esc(company)}",
                      "Company releases, 8-K headlines, the FDA's feeds and the daily "
                      "pulse are read on each refresh. None names this company yet.")
        else:
            figure = TV.news_figure(rows, today, frame["width"])
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


def _results(api_base, company, kit, rule, slot, frame, have):
    """The last reported period, drawn by the Financials tab's own builders."""
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/report")
    report = payload if (payload or {}).get("report") else None
    kit.section(label, basis=basis)
    with _body(slot, frame):
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


def _trend(api_base, company, kit, rule, slot, frame, have):
    """Growth and margin by year as two lines, under the latest period's figures."""
    label, basis = rule
    built, problem = read(
        api_base, f"/companies/{urllib.parse.quote(company)}/statements?basis=annual")
    built = built or {}
    points, snapshot = built.get("trend") or [], built.get("snapshot") or {}
    kit.section(label, basis=" · ".join(part for part in (
        basis, snapshot.get("label"), built.get("currency")) if part))
    with _body(slot, frame):
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


def _filings(api_base, company, kit, rule, slot, frame, have):
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/filings")
    rows = TV.filings_rows(payload)
    today = dt.date.today()
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot, frame):
        if problem:
            _failed(kit, "The filings", problem)
        elif not rows:
            kit.state(f"No filings on file for {TV.esc(company)}",
                      "Filings are read from EDGAR on each refresh. A company outside "
                      "the SEC files none there.")
        else:
            figure = TV.filings_figure(rows, today, frame["width"])
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


def _fundamentals(api_base, company, kit, rule, slot, frame, have):
    """The figures a price is set on, as tiles: growth, the outlook, valuation and the
    balance sheet, and the price against its sector. Every figure is a read's own."""
    label, basis = rule
    q = urllib.parse.quote(company)
    report, _p1 = read(api_base, f"/companies/{q}/report")
    street, street_problem = read(api_base, f"/companies/{q}/street", HEAVY_TIMEOUT_S)
    cash, _p2 = read(api_base, f"/companies/{q}/cashflow")
    runway, _p3 = read(api_base, f"/companies/{q}/runway")
    relative, _p4 = read(api_base, f"/companies/{q}/relative")
    screen, _p5 = read(api_base, "/screen")
    prices = have.get("prices")
    if prices is None:
        prices, _p6 = read(api_base, f"/companies/{q}/prices")
    latest = (prices or {}).get("latest") or {}
    row = next((r for r in screen or [] if isinstance(r, dict) and r.get("ticker") == company),
               None)
    groups = TV.fundamentals(dt.date.today(), report=report, street=street, cash=cash,
                             runway=runway, screen=row, relative=relative,
                             close=latest.get("close"),
                             price_currency=(prices or {}).get("currency"))
    currency = ((report or {}).get("filed") or {}).get("currency") or (cash or {}).get(
        "currency") or (row or {}).get("currency")
    kit.section(label, basis=" · ".join(part for part in (basis, currency) if part))
    with _body(slot, frame):
        markup = TV.tiles_html(groups)
        if not markup:
            kit.state(f"No fundamentals on file for {TV.esc(company)}",
                      "Filed results, the street's estimates and the cash flow statement "
                      f"are read on each refresh. For this company they are {TV.NO_DATA}.")
            return
        st.markdown(markup, unsafe_allow_html=True)
        kit.note("Growth is the last reported quarter against the same quarter a year "
                 "before, and EPS against the street is the street's own count. The "
                 "outlook is the company's latest guidance and the street's consensus and "
                 "12 month target; price to street EPS is the last close over the street's "
                 "EPS for this fiscal year. Free cash flow and leverage are the last full "
                 "year. Against the sector is the price's move less the sector fund's."
                 + (" The street's estimates did not load and are left off: "
                    f"{TV.esc(street_problem)}. The book may still be working them out; "
                    "they are tried again in half a minute." if street_problem else ""))


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


def _price(api_base, company, kit, rule, slot, frame, have):
    """The daily price with the live session over it, at a fixed height.

    The same builders as the Prices tab (``price_chart``) in a smaller frame: candles, a
    day, a week or a month each by the window, and the approvals marked. The intraday
    views, the fair value line and why it moved stay on the Prices tab, their page.
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
            basis, stored.get("currency") or live.get("currency")) if part))
        points = stored.get("points") or []
        over = ([live["live_daily"]] if price_chart.live_daily_applies(
            points, live.get("live_daily"), stored.get("last_fetch_at")) else [])
        span = st.session_state.get(f"td_span_{slot}") or TV.DEFAULT_SPAN
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
        # The window and what it shows on one line: a control a few characters wide, and
        # the last close, the window's change and its range beside it.
        with st.container(key=f"td_pricectl_{slot}", horizontal=True,
                          vertical_alignment="center", gap="small"):
            st.segmented_control(
                "Window", [name for name, _days in TV.PRICE_SPANS], default=TV.DEFAULT_SPAN,
                key=f"td_span_{slot}", label_visibility="collapsed",
                help="How far back the chart reaches. A candle is a day up to six "
                     "months, a week for a year and a month for five.")
            st.markdown(TV.price_stats_html(TV.price_stats(bars), span),
                        unsafe_allow_html=True)
        step = TV.BAR_OF.get(span, "day")
        sticks = TV.candles(bars, step)
        approvals, _problem = read(
            api_base, f"/companies/{urllib.parse.quote(company)}/approvals")
        markers = price_chart.event_markers(
            sticks, TV.price_events((approvals or {}).get("approvals")), False)
        kit.draw_chart(
            data=price_chart.series_data(sticks, price_chart.CANDLE, False), markers=markers,
            fair=[], mode=price_chart.CANDLE, intraday=False, lines=[], draw_mode=False,
            theme={"ground": TK.GROUND, "muted": TK.MUTED, "rule": TK.RULE_FAINT,
                   "rule_strong": TK.RULE_STRONG, "up": TK.UP, "down": TK.DOWN,
                   "flag": TK.FLAG},
            gutter=PRICE_UNDER, view_key=f"{company}|{span}",
            height=max(PRICE_MIN, TV.area_px(frame["h"]) - PRICE_CHROME),
            fill=False, key=f"td_chart_{slot}")
        legend = (f'{TV.BAR_WORDS[step]} candles &nbsp;·&nbsp; '
                  f'<span style="color:var(--up)">▲</span> approval &nbsp;'
                  f'<span style="color:var(--down)">▼</span> loss of exclusivity')
        words = price_chart.live_bar_words(live, "1d", over, points)
        if words:
            legend += f" &nbsp;·&nbsp; {TV.esc(words)}"
        st.markdown(f'<div class="byline chart-legend td-legend">{legend}</div>',
                    unsafe_allow_html=True)
        kit.note(TV.esc(price_chart.live_status(live)) + ". "
                 + TV.esc(price_chart.live_note(live))
                 + "Candles from the book's stored daily history, with the current session "
                   "from Yahoo's live read laid over them where the stored series does "
                   "not yet hold that day's close. The live read writes nothing to the "
                   "book. Intraday bars, the fair value line and why the price moved "
                   "are on the Prices tab.")

    chart()


def _ask(api_base, company, kit, rule, slot, frame, have):
    """The Ask box as a panel: a question about the company or the book, answered by a
    model that reads the book through the desk tools.

    One conversation a company, the same as the Ask tab's. The transcript scrolls inside
    the panel, the newest at the foot, and the box sits under it. Nothing is suggested:
    the panel opens on a blank box and one line saying what it is for. Drawn as a fragment
    of its own, so asking redraws the conversation and not the board."""
    label, basis = rule

    @st.fragment
    def box():
        status, problem = read(api_base, "/ask/status")
        kit.section(label, basis=basis)
        if problem or not (status or {}).get("ready"):
            with _body(slot, frame):
                kit.state("No model key is set" if not problem else "The Ask box did not load",
                          "The Ask box is answered by a language model reading the book. Set "
                          "GEMINI_API_KEY, GROQ_API_KEY or ANTHROPIC_API_KEY in .env and "
                          "restart the API. Every other panel works without one."
                          if not problem else TV.esc(problem), error=bool(problem))
            return
        key = f"ask_turns_{company}"
        turns = st.session_state.setdefault(key, [])
        pending = st.session_state.pop(f"td_pending_{slot}", None)
        with st.container(key=f"td_chat_{slot}", border=False):
            if not turns and not pending:
                st.markdown(TV.ask_empty_html(company), unsafe_allow_html=True)
            for i, turn in enumerate(turns):
                st.markdown(TV.ask_question_html(turn.get("q")), unsafe_allow_html=True)
                if turn.get("ok"):
                    with st.container(key=f"td_ans_{slot}_{i}"):
                        # A pair of dollar signs is mathematics to Streamlit's markdown.
                        st.markdown(str(turn.get("answer") or "").replace("$", "\\$"))
                else:
                    st.markdown(TV.ask_failed_html(turn.get("reason")),
                                unsafe_allow_html=True)
                st.markdown(kit.ask_reads(turn.get("steps") or []), unsafe_allow_html=True)
            if pending:
                st.markdown(TV.ask_question_html(pending), unsafe_allow_html=True)
                with st.spinner("Reading the book"):
                    kit.ask_send(api_base, company, have.get("name") or "", key, pending,
                                 SHOWING_KEY)
                _rerun_board()
        with st.container(key=f"td_askbox_{slot}", horizontal=True,
                          vertical_alignment="center", gap="small"):
            typed = st.chat_input(f"Ask about {company} or anything in the book",
                                  key=f"td_input_{slot}")
            if turns:
                st.button("Clear", key=f"td_clear_{slot}", type="tertiary",
                          on_click=_clear_turns, args=(key,),
                          help="Start the conversation about this company again.")
        if typed:
            st.session_state[f"td_pending_{slot}"] = typed
            _rerun_board()
        kit.note("A language model answers from the book's own reads and lists each one "
                 "under its answer. It values nothing and changes nothing; the figures are "
                 f"the book's. Research, not advice. Model: {TV.esc(status.get('model'))}. "
                 "It is told which panels are open on the board, by name, and not what "
                 "they show. The conversation is the Ask tab's too.")

    box()


def _clear_turns(key: str) -> None:
    st.session_state[key] = []


DRAW = {"price": _price, "fundamentals": _fundamentals, "news": _news, "results": _results,
        "trend": _trend, "filings": _filings, "ask": _ask}


# ----------------------------------------------------------------------------- the board
# The board is one value in the session, ``td_layout``: its panels, each with an id, the
# company it is pinned to if any, and its place and size on the grid (trading_view), and
# whether the Ask box is beside it. Every control below changes that value through a
# callback, which Streamlit runs before the page is drawn, and a drag on the board comes
# back as a place to put one panel; so the board is always drawn from the value as it
# stands. A widget's own state is set from it on every run and is never the record.
LAYOUT_KEY = "td_layout"
FOLLOW = "Top bar"
ARRANGE = [2.6, 2.8, 0.6, 0.6, 0.6]     # the arranger's columns, as shares of its width
GRID_KEY = "td_gridctl"                 # the drag and resize frame
PLACED_KEY = "_td_grid_placed"          # the last placing applied, so none is applied twice


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


def _remove(pid: str) -> None:
    _keep(TV.removed(layout(), pid))


def _move(pid: str, step: int) -> None:
    _keep(TV.moved(layout(), pid, step))


def _pin(pid: str) -> None:
    chosen = st.session_state.get(f"td_co_{pid}", FOLLOW)
    _keep(TV.changed(layout(), pid, ticker=None if chosen == FOLLOW else chosen))


def _lay_out(columns: int) -> None:
    _keep(TV.laid_out(layout(), columns))


def _reset() -> None:
    _keep(TV.default_layout())


def placed(value) -> bool:
    """Apply a place the reader dragged a panel to, once. True where the board changed.

    The frame sends ``{token, n, id, x, y, w, h}`` and keeps returning it on every later
    run, so the pair (token, n) that was last applied is kept and the same one is not
    applied again: a second application would undo nothing, but it would settle the
    board round a place the reader has since moved away from."""
    if not isinstance(value, dict):
        return False
    stamp = (value.get("token"), value.get("n"))
    if stamp == st.session_state.get(PLACED_KEY):
        return False
    st.session_state[PLACED_KEY] = stamp
    before = layout()
    after = TV.place(before, value.get("id"), value.get("x"), value.get("y"),
                     value.get("w"), value.get("h"))
    if after["panels"] == before["panels"]:
        return False
    _keep(after)
    return True


# --- saved boards ---------------------------------------------------------------------
BOARDS_KEY = "td_boards"     # the saved boards as the API gave them, read once a session
NAME_KEY = "td_board_name"   # the saved board that is open, if the board is one
BOARDS_PATH = "/desk/layouts"


def _send(api_base: str, method: str, path: str, body=None) -> dict:
    """The board's one kind of write: its own arrangement, to ``/desk/layouts``. Raises
    on a failure, with the API's reason where it gave one."""
    request = urllib.request.Request(
        api_base.rstrip("/") + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail")
        except (ValueError, OSError):
            detail = None
        raise OSError(str(detail or f"the API answered {exc.code}")) from exc


def boards(api_base: str) -> dict:
    """The saved boards, read once a session and kept. An API that does not answer, or
    one from before boards could be saved, is no boards and the reason."""
    held = st.session_state.get(BOARDS_KEY)
    if held is None:
        try:
            with urllib.request.urlopen(api_base.rstrip("/") + BOARDS_PATH,
                                        timeout=LIVE_TIMEOUT_S) as resp:
                held = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            held = {"boards": {}, "current": None,
                    "problem": f"Boards cannot be saved or opened: {str(exc).rstrip('.')}."}
        st.session_state[BOARDS_KEY] = held
    return held


def _open_first(api_base: str) -> None:
    """On the first run of a session, the board that was open last time."""
    if LAYOUT_KEY in st.session_state:
        return
    held = boards(api_base)
    current = held.get("current")
    if current and current in (held.get("boards") or {}):
        _keep(held["boards"][current])
        st.session_state[NAME_KEY] = current


def _open(api_base: str) -> None:
    name = st.session_state.get("td_open")
    held = boards(api_base).get("boards") or {}
    if name in held:
        _keep(held[name])
        st.session_state[NAME_KEY] = name
        st.session_state["td_board_note"] = f"Opened {name}."


def _save(api_base: str) -> None:
    name = " ".join(str(st.session_state.get("td_save_name") or "").split())
    if not name:
        st.session_state["td_board_note"] = "Give the board a name to save it."
        return
    try:
        st.session_state[BOARDS_KEY] = _send(api_base, "PUT", BOARDS_PATH,
                                             {"name": name, "layout": layout()})
        st.session_state[NAME_KEY] = name
        st.session_state["td_board_note"] = f"Saved as {name}. It opens next time."
    except (urllib.error.URLError, OSError, ValueError) as exc:
        st.session_state["td_board_note"] = f"Not saved: {str(exc).rstrip('.')}."


def _delete(api_base: str) -> None:
    name = st.session_state.get(NAME_KEY)
    if not name:
        return
    try:
        st.session_state[BOARDS_KEY] = _send(
            api_base, "DELETE", f"{BOARDS_PATH}/{urllib.parse.quote(name)}")
        st.session_state[NAME_KEY] = None
        st.session_state["td_board_note"] = (f"Deleted {name}. The panels on screen "
                                             "are as they were.")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        st.session_state["td_board_note"] = f"Not deleted: {str(exc).rstrip('.')}."


def _boards_menu(api_base: str) -> None:
    """Open a saved board, save this one under a name, or delete the one that is open."""
    held = boards(api_base)
    names = sorted(held.get("boards") or {})
    open_name = st.session_state.get(NAME_KEY)
    with st.popover(f"Board: {open_name}" if open_name else "Boards"):
        if held.get("problem"):
            st.markdown(f'<div class="byline td-left-out">{TV.esc(held["problem"])}</div>',
                        unsafe_allow_html=True)
            return
        if names:
            _show("td_open", open_name if open_name in names else None)
            st.selectbox("Open a saved board", names, index=None, key="td_open",
                         placeholder="Pick one", on_change=_open, args=(api_base,))
        if "td_save_name" not in st.session_state:
            st.session_state["td_save_name"] = open_name or ""
        st.text_input("Save this board as", key="td_save_name", max_chars=40,
                      placeholder="Readout prep")
        with st.container(key="td_board_buttons", horizontal=True):
            st.button("Save", key="td_save", on_click=_save, args=(api_base,))
            st.button("Delete", key="td_delete", disabled=not open_name,
                      on_click=_delete, args=(api_base,),
                      help="Forget the saved board that is open. The panels stay up.")
        st.markdown('<div class="byline">Kept on this machine, in a file beside the book. '
                    "Saving changes nothing in the book.</div>", unsafe_allow_html=True)


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
    """The board's panels as rows, in the order they are read: whose each is, a place
    earlier or later, and off. Dragging does the moving and sizing; this is the way to do
    it from the keyboard, and to lay the whole board out afresh."""
    panels = board["panels"]
    with st.popover("Arrange", disabled=not panels):
        last = len(panels) - 1
        # The columns are named once, over the rows, so a row is its controls and not a
        # label on each of them.
        for cell, text in zip(st.columns(ARRANGE), ("Panel", "Company", "", "", "")):
            cell.markdown(f'<div class="td-group">{text}</div>', unsafe_allow_html=True)
        for i, entry in enumerate(panels):
            pid = entry["id"]
            options = [FOLLOW] + list(tickers or [])
            if entry.get("ticker") and entry["ticker"] not in options:
                options.append(entry["ticker"])
            name, co, up, down, off = st.columns(ARRANGE, vertical_alignment="center")
            name.markdown(f'<div class="td-arr">{TV.esc(TV.BY_ID[entry["panel"]]["title"])}'
                          "</div>", unsafe_allow_html=True)
            _show(f"td_co_{pid}", entry.get("ticker") or FOLLOW)
            co.selectbox("Company", options, key=f"td_co_{pid}",
                         label_visibility="collapsed", on_change=_pin, args=(pid,))
            up.button("↑", key=f"td_up_{pid}", disabled=i == 0, help="Earlier on the board",
                      on_click=_move, args=(pid, -1))
            down.button("↓", key=f"td_down_{pid}", disabled=i == last,
                        help="Later on the board", on_click=_move, args=(pid, 1))
            off.button("×", key=f"td_off_{pid}", help="Take it off the board",
                       on_click=_remove, args=(pid,))
        st.markdown('<div class="td-group">Lay the board out afresh</div>',
                    unsafe_allow_html=True)
        with st.container(key="td_relayout", horizontal=True):
            for n, words in ((1, "One across"), (2, "Two across"), (3, "Three across")):
                st.button(words, key=f"td_across_{n}", on_click=_lay_out, args=(n,))
            st.button("The default board", key="td_reset", on_click=_reset)


def _controls(api_base: str, board: dict, ticker: str, tickers) -> None:
    """The row above the board: the saved boards, add a panel, and arrange them."""
    with st.container(key="td_controls", horizontal=True, vertical_alignment="center"):
        _boards_menu(api_base)
        _add_menu(tickers)
        _arrange_menu(board, ticker, tickers)
        st.markdown('<div class="byline td-hint">Drag a panel by its heading to move it, '
                    "and by a corner to size it.</div>", unsafe_allow_html=True)


@st.fragment
def _board(api_base: str, ticker: str, kit, page: dict, tickers, name: str = "") -> None:
    """The controls and the panels. A fragment: a change to the board redraws the board
    alone."""
    # A drag the reader has just finished. Applied first, so this run draws the board
    # where it was left; then the board is run once more so the frame is handed the
    # places it now has.
    if placed(st.session_state.get(GRID_KEY)):
        _rerun_board()
    board = layout()
    _controls(api_base, board, ticker, tickers)
    said = st.session_state.pop("td_board_note", None)
    if said:
        st.markdown(f'<div class="byline td-said">{TV.esc(said)}</div>',
                    unsafe_allow_html=True)
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
    # Where each panel sits, then the frame that lets the reader take hold of them, then
    # the panels themselves in reading order, which is the order a screen reader meets
    # them in whatever the grid does with them.
    st.markdown(TV.grid_css(board["panels"]), unsafe_allow_html=True)
    value = kit.board_grid(panels=TV.grid_spec(board["panels"]), cols=TV.GRID_COLS,
                           row_px=TV.ROW_PX, gap_px=TV.GAP_PX,
                           theme={"up": TK.UP, "rule_strong": TK.RULE_STRONG,
                                  "muted": TK.MUTED, "panel": TK.PANEL},
                           key=GRID_KEY)
    if placed(value):
        _rerun_board()
    with st.container(key="td_grid"):
        for entry in board["panels"]:
            company = TV.company_of(entry, ticker)
            frame = {"width": TV.figure_width(entry["w"]), "h": entry["h"]}
            with st.container(key=f"td_p_{entry['id']}"):
                DRAW[entry["panel"]](
                    api_base, company, kit, TV.heading(entry, ticker), entry["id"], frame,
                    dict(page, name=name) if company == ticker else {})


def _rerun_board() -> None:
    """Run the fragment this is called from again, the board or the Ask box, and only it
    where Streamlit allows that; in a run of the whole page it runs the page."""
    try:
        st.rerun(scope="fragment")
    except st.errors.StreamlitAPIException:
        st.rerun()


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
    _open_first(api_base)
    _board(api_base, ticker, kit, page, tickers, name)
