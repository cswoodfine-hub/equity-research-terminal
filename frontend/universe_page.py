"""The redesigned Universe tab, drawn: one read, the builders, a fragment and a dialog.

``universe_cc`` builds every block as a string from the payload of ``GET /universe/command``;
this module is the Streamlit glue around it, kept out of streamlit_app.py so the change
there stays the switch and the calls.

The tab is the week across the group on one 1440 by 780 screen: a control row (the week,
the regions against the company picked over a window, the close and the view switch), the
band (the ranked feed beside the company board, the cheap to expensive ribbon under them)
and the group's equal-weighted index over three months. The page reads the same whichever
company is picked: that company is washed where it falls, and only the control row's own
figure is about it.

The whole tab sits in one ``@st.fragment``, so the window switch reruns only the tab. A
click on a story's ticker, a board row or a ribbon tile comes back through the ``uvboard``
component and opens the company dialog inside the same fragment.

Every figure on the page comes from the payload; nothing here computes one.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

import universe_cc as UC
from components import tokens as TK

try:                                    # the click component; the page draws without it
    from components import uvboard as _uvboard
except Exception:                       # pragma: no cover - a broken install only
    _uvboard = None

WINDOW_KEYS = {label: key for key, label in UC.WINDOWS}
DEFAULT_WINDOW_LABEL = UC.WIN_LABEL["1y"]
TABS = ("Key insights", "Catalysts", "Comps")
# The token values the frame sets on its own root, for any rule that reads one before
# tokens.css has applied.
FRAME_TOKENS = {"ground": TK.GROUND, "panel": TK.PANEL, "rule": TK.RULE,
                "rule-strong": TK.RULE_STRONG, "text": TK.TEXT, "muted": TK.MUTED,
                "up": TK.UP, "down": TK.DOWN, "flag": TK.FLAG}


def _read(api_base: str, ticker: str, part: str) -> dict:
    path = (f"/universe/command?ticker={urllib.parse.quote(ticker)}"
            f"&part={urllib.parse.quote(part)}")
    with urllib.request.urlopen(api_base.rstrip("/") + path, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _Incomplete(Exception):
    """Carries a read the API marked incomplete out of the cached function: an exception
    is never cached, so the read is used once and asked for again on the next run."""

    def __init__(self, payload: dict):
        super().__init__("incomplete read")
        self.payload = payload


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_complete(api_base: str, ticker: str, part: str) -> dict:
    payload = _read(api_base, ticker, part)
    if not payload.get("complete", True):
        raise _Incomplete(payload)
    return payload


def fetch(api_base: str, ticker: str, part: str = "all") -> dict:
    """The command centre's payload for one company in focus, held five minutes once it
    is complete. A read taken while the API is still valuing the group (``complete`` is
    false: most model values missing) is drawn as it is but never held, so the page does
    not show a partial map for five minutes after the API restarts."""
    try:
        return _fetch_complete(api_base, ticker, part)
    except _Incomplete as exc:
        return exc.payload


def _md(markup: str) -> str:
    """Markup for st.markdown: a dollar sign is written as an entity, so a pair of them can
    never be read as a formula."""
    return markup.replace("$", "&#36;")


def _show(markup: str) -> None:
    if markup:
        st.markdown(_md(markup), unsafe_allow_html=True)


def _frame_css() -> str:
    """What the uvboard frame needs to draw the band as the page would: the tokens, the
    research primitives and universe.css, the same text the page carries."""
    import theme
    return theme._TOKENS_CSS + "\n" + theme._RESEARCH_CSS + "\n" + theme._UNIVERSE_CSS


# ------------------------------------------------------------------ navigation hooks
def apply_goto(tickers) -> None:
    """Called before the company picker reads its key: a dialog button that opens another
    company's tab names it here, and the picker takes it on this run."""
    goto = st.session_state.pop("_uv_goto", None)
    if not isinstance(goto, dict):
        return
    if goto.get("ticker") in tickers:
        st.session_state["company_pick"] = goto["ticker"]
    if goto.get("tab"):
        st.session_state["_uv_tab_click"] = goto["tab"]


def click_pending_tab() -> None:
    """Called once the tab strip exists: switches the page to the tab a dialog button
    named. Tabs cannot be switched from Python, so a zero-height frame clicks the tab's
    button in the parent document, as covnav does."""
    label = st.session_state.pop("_uv_tab_click", None)
    if not label:
        return
    import streamlit.components.v1 as components
    components.html(
        "<script>(function(){var n=0;function go(){try{var t=window.parent.document"
        ".querySelectorAll('button[data-baseweb=\"tab\"]');for(var i=0;i<t.length;i++)"
        "{if((t[i].textContent||'').trim()===" + json.dumps(label) + "){t[i].click();"
        "return;}}}catch(e){return;}if(++n<30)setTimeout(go,100);}go();})();</script>",
        height=0)


# ---------------------------------------------------------------------------- dialog
def _open_dialog(api_base: str, ticker: str, opened_from: str) -> None:
    try:
        with st.spinner(f"Reading {ticker} against the group"):
            p = fetch(api_base, ticker, "focal")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        st.warning(f"The detail for {ticker} did not load: {exc}")
        return
    name = (p.get("focal") or {}).get("short") or ticker

    @st.dialog(f"{name} in the group", width="large")
    def _body():
        _show(UC.dialog_html(p, opened_from))
        cols = st.columns([1.1, 1, 1, 3.4])
        for i, tab in enumerate(TABS):
            if cols[i].button(f"Open {tab}", key=f"uv_dlg_{tab}",
                              type="primary" if i == 0 else "secondary"):
                st.session_state["_uv_goto"] = {"ticker": ticker, "tab": tab}
                st.rerun()

    _body()


# ----------------------------------------------------------------------- the fragment
def _window_label() -> str:
    label = st.session_state.get("uv_window")
    if label in WINDOW_KEYS:
        st.session_state["_uv_window_last"] = label
        return label
    return st.session_state.get("_uv_window_last") or DEFAULT_WINDOW_LABEL


@st.fragment
def _command(api_base: str, p: dict) -> None:
    # One control line: the week, the regions over a window and the window's switch, the
    # close. The last column is left empty: the view switch is drawn over it
    # (universe.css).
    kick, lead, win, right, _switch = st.columns([0.13, 0.33, 0.17, 0.2, 0.17],
                                                 vertical_alignment="center", gap="small")
    with win:
        st.segmented_control("Moves over", list(WINDOW_KEYS), default=DEFAULT_WINDOW_LABEL,
                             key="uv_window", label_visibility="collapsed")
    w = WINDOW_KEYS[_window_label()]
    with kick:
        _show(f'<div class="uv">{UC.week_kicker(p)}</div>')
    with lead:
        _show(f'<div class="uv">{UC.lead_line(p, w)}</div>')
    with right:
        _show(f'<div class="uv">{UC.status_line(p)}</div>')

    band = UC.front_html(p)
    clicked = None
    if _uvboard is not None:
        clicked = _uvboard.uv_board(band, css=_frame_css(), tokens=FRAME_TOKENS,
                                    key="uv_board")
    else:
        _show(band)
        pick = st.pills("Open detail", UC._tickers(p), key="uv_pick",
                        label_visibility="collapsed", on_change=_pill_picked)
        del pick
        clicked = st.session_state.pop("_uv_pill_click", None)
    if (isinstance(clicked, dict) and clicked.get("ticker")
            and clicked.get("nonce") != st.session_state.get("_uv_board_nonce")):
        st.session_state["_uv_board_nonce"] = clicked.get("nonce")
        _open_dialog(api_base, clicked["ticker"], clicked.get("from") or "the board")
    # Outside the frame, so its height can follow the screen's (universe.css, .uw-idx).
    _show(UC.index_html(p))


def _pill_picked() -> None:
    t = st.session_state.get("uv_pick")
    if t:
        n = st.session_state.get("_uv_pill_n", 0) + 1
        st.session_state["_uv_pill_n"] = n
        st.session_state["_uv_pill_click"] = {"ticker": t, "from": "the board",
                                              "nonce": f"pill-{n}"}


def render(api_base: str, ticker: str) -> bool:
    """Draw the tab for ``ticker``. False when the payload cannot be read, so the caller
    can draw today's overview instead of an empty tab."""
    try:
        p = fetch(api_base, ticker, "all")
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if not p or not p.get("companies"):
        return False
    _command(api_base, p)
    return True
