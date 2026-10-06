"""The redesigned Catalysts tab, drawn: one read, the builders, a fragment and a dialog.

``catalysts_view`` builds every block as a string from the payload of
``GET /companies/{t}/catalysts/view``; this module is the Streamlit glue around it, kept
out of streamlit_app.py so the change there stays the switch and the calls. The tab fits
one 1440 x 900 screen: the header row, then the ``catnav`` frame (the timeline and the
range chart) beside a tabbed rail (the selected gate, next up, the risk register and why
events carry no price); the calendar fold stays under it, drawn by streamlit_app as for
every company.

The frame and the rail sit in one ``@st.fragment``, so a click on a disc or a bar reruns
only them. The selected gate's card prints the Next gate block's facts with the Forecast
tab's own builders, passed in as ``kit`` (streamlit_app's ``_gate_*`` and ``_stake_*``),
so the cost to reach, the net, the launch floor and the two-click record control read
and act the same on both tabs. Every figure on the page comes from the payload or from
those builders; nothing here computes one.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

import catalysts_view as CV
from components import tokens as TK

try:                                    # the click component; the page draws without it
    from components import catnav as _catnav
except Exception:                       # pragma: no cover - a broken install only
    _catnav = None

# The token values the frame sets on its own root, for any rule that reads one before
# tokens.css has applied.
FRAME_TOKENS = {"ground": TK.GROUND, "panel": TK.PANEL, "rule": TK.RULE,
                "rule-strong": TK.RULE_STRONG, "text": TK.TEXT, "muted": TK.MUTED,
                "up": TK.UP, "down": TK.DOWN, "flag": TK.FLAG}
RAIL_TABS = ("Selected gate", "Next up", "Risk register", "Unpriced")
# The frame's drawing width at 1440: the left column of the body.
FRAME_W = 956


def _read(api_base: str, ticker: str) -> dict:
    path = f"/companies/{urllib.parse.quote(ticker)}/catalysts/view"
    with urllib.request.urlopen(api_base.rstrip("/") + path, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


class _Incomplete(Exception):
    """Carries a read the API marked incomplete out of the cached function: an exception
    is never cached, so the read is used once and asked for again on the next run."""

    def __init__(self, payload: dict):
        super().__init__("incomplete read")
        self.payload = payload


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_complete(api_base: str, ticker: str) -> dict:
    payload = _read(api_base, ticker)
    if not payload.get("complete", True):
        raise _Incomplete(payload)
    return payload


def fetch(api_base: str, ticker: str) -> dict:
    """The tab's payload, held five minutes once it is complete. A read taken before the
    scorecard it embeds was warm is drawn as it is but never held."""
    try:
        return _fetch_complete(api_base, ticker)
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
    """What the catnav frame needs to draw as the page would: the tokens, the research
    primitives and catalysts.css, the same text the page carries."""
    import theme
    return theme._TOKENS_CSS + "\n" + theme._RESEARCH_CSS + "\n" + theme._CATALYSTS_CSS


# ------------------------------------------------------------------- the gate's facts
def _summary(kit, r: dict, error=None) -> dict:
    """The Next gate block's summary of this gate, from the verdict's gate, the launch
    floor and the development row, through the Forecast tab's own builder. ``error`` is
    why the development view did not read, where it did not."""
    if kit is None or r is None:
        return {}
    verdict = {"gate": r.get("verdict_gate") or {}, "launch": r.get("launch") or {}}
    return kit.gate_summary(verdict, r.get("development"), error)


def card_facts(kit, r: dict, error=None) -> tuple:
    """(facts table, lines) for the card: the Next gate rows the fork does not draw."""
    s = _summary(kit, r, error)
    if not s:
        return "", []
    rows = [x for x in kit.gate_rows(s) if x.get("k") in CV.CARD_FACTS]
    lines = [x for x in kit.gate_lines(s)
             if not str(x).startswith("The cost to reach is") and "Trial costs are at" not in x]
    return kit.gate_table_html(rows), lines


def dialog_parts(kit, r: dict, error=None) -> tuple:
    """(cost table, ladder, studies) for the dialog, with the Forecast tab's builders."""
    s = _summary(kit, r, error)
    if not s:
        return "", "", ""
    rows = [x for x in kit.gate_rows(s)
            if x.get("k") in ("cost to reach", "net", "at DiMasi's level")]
    lines = "".join(f'<div class="cx-line">{html.escape(x)}</div>' for x in kit.gate_lines(s))
    dev = r.get("development")
    return (kit.gate_table_html(rows) + lines, kit.gate_ladder_html(dev),
            kit.gate_studies_html(dev))


# --------------------------------------------------------------------------- dialog
def _open_dialog(api_base: str, ticker: str, p: dict, gid, kit) -> None:
    r = next((x for x in p.get("gates") or [] if x.get("asset_id") == gid), None)

    @st.dialog(CV.dialog_title(p, gid), width="large")
    def _body():
        cost, ladder, studies = dialog_parts(kit, r, p.get("development_error"))
        _show(CV.dialog_html(p, gid, cost, ladder, studies))
        _record(api_base, ticker, r, kit, where="dialog")

    _body()


def _record(api_base: str, ticker: str, r, kit, where: str = "card") -> None:
    """The record control: met and missed, two clicks each, drawn only where the stake row
    is priced and the back end marks it resolvable; otherwise the row's own note."""
    stake = (r or {}).get("stake")
    if kit is not None and stake and kit.stake_resolvable(stake):
        if where == "card":
            with st.popover("Record the outcome"):
                kit.stake_row(st.container(), api_base, ticker, stake)
        else:
            kit.stake_row(st.container(), api_base, ticker, stake)
    elif where == "card":
        st.caption(CV.resolve_text(r))


# ------------------------------------------------------------------- the fragment
def _selected(p: dict, ticker: str, clicked=None):
    """The gate the card shows: the last click on the frame, else the last pick in this
    session, else the largest swing."""
    nkey, skey = f"_cx_nonce_{ticker}", f"cx_gate_{ticker}"
    for v in (st.session_state.get(f"cx_nav_{ticker}"), clicked):
        if (isinstance(v, dict) and v.get("gate")
                and v.get("nonce") != st.session_state.get(nkey)):
            st.session_state[nkey] = v.get("nonce")
            st.session_state[skey] = v.get("gate")
    return CV.selected_gate(p, st.session_state.get(skey))


def _pick_changed(ticker: str) -> None:
    pick = st.session_state.get(f"cx_pick_{ticker}")
    if pick is not None:
        st.session_state[f"cx_gate_{ticker}"] = pick


@st.fragment
def _body(api_base: str, ticker: str, p: dict, kit) -> None:
    gid = _selected(p, ticker)
    with st.container(key="cx_body"):
        left, right = st.columns([0.685, 0.315], gap="small")
        with left:
            markup = CV.frame_html(p, gid, FRAME_W)
            if _catnav is not None:
                clicked = _catnav.cat_nav(markup, css=_frame_css(), tokens=FRAME_TOKENS,
                                          key=f"cx_nav_{ticker}")
                new = _selected(p, ticker, clicked)
                if new != gid:
                    st.rerun(scope="fragment")
            else:
                _show(markup)
        with right, st.container(key="cx_side"):
            tabs = st.tabs(list(RAIL_TABS))
            r = next((x for x in CV.gate_rows(p) if x["asset_id"] == gid), None)
            with tabs[0]:
                if _catnav is None and CV.gate_rows(p):
                    names = {x["asset_id"]: f'{x.get("name")} · {x["glabel"]}'
                             for x in CV.gate_rows(p)}
                    st.selectbox("Gate", list(names), index=list(names).index(gid),
                                 format_func=names.get, key=f"cx_pick_{ticker}",
                                 on_change=_pick_changed, args=(ticker,),
                                 label_visibility="collapsed")
                facts, lines = card_facts(kit, r, p.get("development_error"))
                _show(CV.card_html(p, gid, facts, lines))
                said = (kit.stake_resolved_note(st.session_state.pop(f"cat_resolved_{ticker}", None))
                        if kit is not None else "")
                if said:
                    st.info(said)
                if r is not None:
                    with st.container(key="cx_acts"):
                        a, b, c = st.columns([0.3, 0.5, 0.2], vertical_alignment="center")
                        with a:
                            if st.button("Full detail", key=f"cx_detail_{ticker}", type="primary"):
                                _open_dialog(api_base, ticker, p, gid, kit)
                        with b:
                            _record(api_base, ticker, r, kit)
                        with c:
                            nct = (r.get("trial") or {}).get("nct_id")
                            if nct:
                                _show(f'<a class="cx-src" href="https://clinicaltrials.gov/study/'
                                      f'{html.escape(nct)}" target="_blank" rel="noopener">'
                                      f'ClinicalTrials.gov</a>')
            with tabs[1]:
                _show(f'<div class="cx">{CV.next_html(p)}</div>')
            with tabs[2]:
                _show(f'<div class="cx">{CV.risks_html(p)}</div>')
            with tabs[3]:
                _show(f'<div class="cx">{CV.unpriced_html(p)}'
                      f'<details class="cx-more"><summary>Sources</summary>'
                      f'<div class="cx-line" style="padding: 0 8px 6px">'
                      f'{html.escape(CV.notes_text(p))}</div></details></div>')


def render(api_base: str, ticker: str, kit=None) -> bool:
    """Draw the tab body for ``ticker``. False when the payload cannot be read or the
    model was not, so the caller can draw today's tab instead of an empty one."""
    if st.session_state.get(f"cat_resolved_{ticker}") is not None:
        _fetch_complete.clear()          # a resolve moved the book: read it again
    try:
        p = fetch(api_base, ticker)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if not p or not p.get("model_ok"):
        return False
    _show(CV.header_html(p))
    _body(api_base, ticker, p, kit)
    return True
