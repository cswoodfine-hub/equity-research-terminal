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
import trading_view as TV

# Bumped when the page's calls change: a server running from a worktree does not
# re-import a module under a dot-directory, so streamlit_app reloads one behind this.
REVISION = 2

PANEL_HEIGHT = 340           # a panel's body; past it the panel scrolls, not the page
CALENDAR_MONTHS = 24         # the span a readout calendar is read over, as on Catalysts
HOLD_SECONDS = 60
CHANGE_LEVELS = ("high", "medium")
CHANGES_SHOWN = 40
# The board against the Ask column beside it: about two thirds to one, which leaves the
# box the measure its answers are set at and the board room for two panels across.
BESIDE = (2.05, 1)
ASK_SLOT = "td_"             # the Ask box's second place on the page (see _ask_tab)


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
# (label and basis) and the page's own change feed where the company is the top bar's.
# Each draws its rule first, so the count beside it is the count of what is under it.
def _body(slot: str):
    return st.container(height=PANEL_HEIGHT, border=False, key=f"td_body_{slot}")


def _failed(kit, what: str, problem: str) -> None:
    kit.state(f"{what} did not load", TV.esc(problem), error=True)


def _changes(api_base, company, kit, rule, slot, feed=None):
    label, basis = rule
    problem = None
    if feed is None:
        feed, problem = read(api_base, f"/changes?ticker={urllib.parse.quote(company)}")
    rows = kit.changes(feed or [], company, dt.date.today(), CHANGE_LEVELS)
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The change feed", problem)
        elif not rows:
            kit.state(f"Nothing rated high or medium for {TV.esc(company)} in 30 days",
                      "Every change, at every level, is on the Universe tab's feed.")
        else:
            st.markdown('<div class="feed td-list">'
                        + "".join(kit.change_row(it) for it in rows[:CHANGES_SHOWN])
                        + "</div>", unsafe_allow_html=True)
            kit.note("Changes the book detected between two refreshes and rated high or "
                     "medium, in the last 30 days, newest first. What is dated ahead is "
                     "on the Dated ahead panel.")


def _news(api_base, company, kit, rule, slot, feed=None):
    label, basis = rule
    payload, problem = read(api_base, f"/companies/{urllib.parse.quote(company)}/news")
    rows = TV.news_rows(payload)
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The news", problem)
        elif not rows:
            kit.state(f"No news on file for {TV.esc(company)}",
                      "Company releases, 8-K headlines, the FDA's feeds and the daily "
                      "pulse are read on each refresh. None names this company yet.")
        else:
            st.markdown(TV.news_html(rows), unsafe_allow_html=True)
            kit.note(f"{TV.news_basis(rows)}. Each row opens its source. A row marked "
                     "Daily pulse (AI summary) is a model's summary of the trade press "
                     "and links the article it summarises; it moves no value, deal term "
                     "or catalyst.")


def _catalysts(api_base, company, kit, rule, slot, feed=None):
    label, basis = rule
    payload, problem = read(
        api_base, f"/catalysts?within_days={CALENDAR_MONTHS * 31}"
                  f"&ticker={urllib.parse.quote(company)}")
    listed = payload if isinstance(payload, list) else []
    rows = TV.dated_rows(calendar_view.within(listed, CALENDAR_MONTHS))
    kit.section(label, count=len(rows) if rows else None, basis=basis)
    with _body(slot):
        if problem:
            _failed(kit, "The calendar", problem)
        elif not rows:
            kit.state(f"Nothing dated for {TV.esc(company)} in the next "
                      f"{CALENDAR_MONTHS} months", calendar_view.SOURCES)
        else:
            st.markdown(TV.dated_html(rows), unsafe_allow_html=True)
            kit.note(f"{TV.dated_basis(rows, CALENDAR_MONTHS)}, soonest first. "
                     + calendar_view.caption(listed, CALENDAR_MONTHS)
                     + " A date here is the registry's or the filing's, not a "
                       "commitment. The odds and the value at stake are on Catalysts.")


DRAW = {"changes": _changes, "news": _news, "catalysts": _catalysts}


# ----------------------------------------------------------------------------- the board
def _controls() -> dict:
    """The row above the board: which panels, how many across, and whether the Ask box
    sits beside them. The widgets' own keys hold the choice for the session."""
    kinds = [panel["id"] for panel in TV.PANELS]
    with st.container(key="td_controls", horizontal=True, vertical_alignment="center"):
        picked = st.pills(
            "Panels", kinds, selection_mode="multi", default=list(TV.DEFAULT_PANELS),
            format_func=lambda kind: TV.BY_ID[kind]["title"], key="td_pick",
            label_visibility="collapsed",
            help="Which panels are on the board. Each is drawn for the company in the "
                 "top bar.")
        columns = st.segmented_control(
            "Columns", list(TV.COLUMNS), default=TV.DEFAULT_COLUMNS, key="td_columns",
            format_func=lambda n: f"{n} across", label_visibility="collapsed",
            help="How many panels sit side by side.") or TV.DEFAULT_COLUMNS
        ask = st.toggle(
            "Ask beside", value=True, key="td_ask",
            help="The Ask box in a column beside the board. It is the same conversation "
                 "as the Ask tab's, kept per company.")
    return TV.from_ids(picked or [], columns=columns, ask=ask)


@st.fragment
def _board(api_base: str, ticker: str, kit, feed) -> None:
    """The controls and the panels. A fragment: picking a panel redraws the board alone."""
    layout, left_out = TV.normalise(_controls())
    # The Ask column is laid out by the page, outside this fragment, so a run of the
    # fragment alone cannot add or remove it. When the switch no longer matches what the
    # page drew, the page is run once to draw it.
    if layout["ask"] != st.session_state.get("_td_ask_drawn", layout["ask"]):
        st.rerun()
    # What the Ask box may be told is on screen. Kept in the session and read when a
    # question is sent, so it is the board as it stands and not as it stood at the last
    # full run of the page.
    st.session_state["td_showing"] = TV.showing(layout["panels"], ticker)
    if left_out:
        st.markdown(TV.left_out_html(left_out), unsafe_allow_html=True)
    if not layout["panels"]:
        kit.state("Nothing on the board", "Pick a panel from the row above.")
        return
    for r, row in enumerate(TV.pack(layout["panels"], layout["columns"])):
        alone = len(row) == 1 and (layout["columns"] == 1 or TV.is_wide(row[0]))
        cells = [st.container()] if alone else st.columns(layout["columns"], gap="medium")
        for c, entry in enumerate(row):
            company = TV.company_of(entry, ticker)
            with cells[c], st.container(key=f"td_panel_{r}_{c}"):
                DRAW[entry["panel"]](
                    api_base, company, kit, TV.heading(entry, ticker), f"{r}_{c}",
                    feed=feed if company == ticker else None)


def render(api_base: str, ticker: str, name: str, kit, feed=None,
           historical: bool = False) -> None:
    """The tab. ``feed`` is the change feed the page already read for this company, so
    the What changed panel costs no read of its own."""
    if historical:
        kit.state("The board shows the live book",
                  "A date is set in the sidebar, and the board's panels are not rebuilt "
                  "for a past date. Clear the date to use it.")
        return
    beside = st.session_state.get("td_ask", True)
    st.session_state["_td_ask_drawn"] = beside
    if not beside:
        _board(api_base, ticker, kit, feed)
        return
    board, ask = st.columns(list(BESIDE), gap="medium")
    with board:
        _board(api_base, ticker, kit, feed)
    with ask:
        kit.ask(api_base, ticker, name, slot=ASK_SLOT)
