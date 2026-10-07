"""The Catalysts tab as a dated readout list, drawn: one read, the builders, the frame and
the dialogs.

``catalysts_readouts`` builds the page as one string from the payload of
``GET /companies/{t}/catalysts/view``; this module is the Streamlit glue around it, kept
out of streamlit_app.py so the change there stays the switch and the calls. The page is
one ``catnav`` frame: the header, the list and the rail, filling the screen under the
app's chrome. The area filter works inside the frame, with no rerun. A row on a priced
gate, a readout's row or an index row comes back as a click, which sets the open dialog in
the session; the dialog is drawn on every run while it is set, so the record control's
arming rerun keeps it open, and closing it clears it.

The gate dialog prints the Next gate block's facts and tables with the Forecast tab's own
builders, passed in as ``kit`` (streamlit_app's ``_gate_*`` and ``_stake_*``), so the cost
to reach, the net, the launch floor and the two-click record control read and act the
same on both tabs. Every figure on the page comes from the payload or from those
builders; nothing here computes one.
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.parse
import urllib.request

import streamlit as st

import catalysts_readouts as CR
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


def fact_rows(kit, r: dict, error=None) -> list:
    """The Next gate rows the dialog's band prints as figures: chance, cost to reach, net,
    DiMasi's level and the earliest approval."""
    s = _summary(kit, r, error)
    return [x for x in kit.gate_rows(s) if x.get("k") in CV.CARD_FACTS] if s else []


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


def _resolvable(r, kit) -> bool:
    """Whether the gate's stake row takes a recorded outcome, by the At stake list's own
    rule: priced and marked resolvable by the back end."""
    stake = (r or {}).get("stake")
    return bool(kit is not None and stake and kit.stake_resolvable(stake))


def _record(api_base: str, ticker: str, r, kit) -> None:
    """The record control under the dialog's tabs: met and missed, two clicks each, in a
    popover, drawn only where the stake row takes a recorded outcome. The control is the
    At stake row's own (``kit.stake_row``); its first click arms and reruns the app, and
    the dialog, kept open in the session, is drawn again around it."""
    if _resolvable(r, kit):
        with st.container(key="cx_dlg_rec"), st.popover("Record the outcome"):
            kit.stake_row(st.container(), api_base, ticker, r["stake"])


# --------------------------------------------------------------------------- dialogs
def open_key(ticker: str) -> str:
    """The session key holding the open dialog: {"gate": asset id}, {"ev": event id} or
    {"more": key, "area": name or None}."""
    return f"cx_open_{ticker}"


def _close(ticker: str) -> None:
    st.session_state.pop(open_key(ticker), None)


def _take(ticker: str, clicked) -> None:
    """A click on the frame, once: a new nonce sets the dialog to open."""
    nkey = f"_cx_nonce_{ticker}"
    if not isinstance(clicked, dict) or clicked.get("nonce") == st.session_state.get(nkey):
        return
    st.session_state[nkey] = clicked.get("nonce")
    if clicked.get("gate") is not None:
        try:
            st.session_state[open_key(ticker)] = {"gate": int(clicked["gate"])}
        except (TypeError, ValueError):
            pass
    elif clicked.get("ev") is not None:
        st.session_state[open_key(ticker)] = {"ev": str(clicked["ev"])}
    elif clicked.get("more"):
        st.session_state[open_key(ticker)] = {"more": str(clicked["more"]),
                                              "area": clicked.get("area") or None}


def _gate_dialog(api_base: str, ticker: str, p: dict, gid, kit) -> None:
    r = next((x for x in p.get("gates") or [] if x.get("asset_id") == gid), None)

    @st.dialog(CV.dialog_title(p, gid), width="large", on_dismiss=lambda: _close(ticker))
    def _body():
        err = p.get("development_error")
        facts = fact_rows(kit, r, err) if kit is not None else []
        cost, ladder, studies = dialog_parts(kit, r, err)
        top, panes = CR.gate_dialog(p, gid, facts, cost, ladder, studies,
                                    can_record=_resolvable(r, kit))
        _show(top)
        if panes:
            for tab, (_label, markup) in zip(st.tabs([x[0] for x in panes]), panes):
                with tab:
                    _show(markup)
            _record(api_base, ticker, r, kit)

    _body()


def _readout_dialog(ticker: str, p: dict, ev_id) -> None:
    """A readout on no priced gate: the trial's card, and where the line has a priced gate,
    a button that opens the gate's own dialog in its place."""
    @st.dialog(CR.readout_title(p, ev_id), width="large", on_dismiss=lambda: _close(ticker))
    def _body():
        markup, gid = CR.readout_card(p, ev_id)
        _show(markup)
        if gid is not None and st.button("Open the line's gate", key=f"cx_ev_gate_{ticker}"):
            st.session_state[open_key(ticker)] = {"gate": gid}
            st.rerun()

    _body()


def _more_dialog(ticker: str, p: dict, key: str, area=None) -> None:
    @st.dialog(CR.more_title(key, area), width="large" if key == "cal" else "medium",
               on_dismiss=lambda: _close(ticker))
    def _body():
        _show(CR.more_dialog_html(p, key, area))

    _body()


def _picker(p: dict, ticker: str) -> None:
    """Without the click component: one list of what the frame would open."""
    rows = CR.readouts(p)
    opts = {f"g{r['asset_id']}": f"{r.get('name')} · {r['glabel']}" for r in CV.gate_rows(p)}
    opts.update({f"e{r['id']}": f"{r['drug']} · {r['ph_txt']} · {CR.group_label(r['group'])}"
                 for r in rows if r["kind"] == "event" and r["gate"] is None})
    opts.update({f"m{k}": label for k, label, *_ in CR.index_items(p, rows)})

    def pick():
        v = st.session_state.get(f"cx_pick_{ticker}")
        if v and v.startswith("g"):
            st.session_state[open_key(ticker)] = {"gate": int(v[1:])}
        elif v and v.startswith("e"):
            st.session_state[open_key(ticker)] = {"ev": v[1:]}
        elif v:
            st.session_state[open_key(ticker)] = {"more": v[1:], "area": None}

    st.selectbox("Open the full detail of", list(opts), index=None, format_func=opts.get,
                 key=f"cx_pick_{ticker}", on_change=pick, placeholder="Open the full detail of")


# ------------------------------------------------------------------- the fragment
@st.fragment
def _body(api_base: str, ticker: str, p: dict, kit) -> None:
    markup = CR.page_html(p)
    with st.container(key="cx_body"):
        if _catnav is not None:
            _take(ticker, _catnav.cat_nav(markup, css=_frame_css(), tokens=FRAME_TOKENS,
                                          key=f"cx_nav_{ticker}"))
        else:
            _show(markup)
            _picker(p, ticker)
    want = st.session_state.get(open_key(ticker))
    if isinstance(want, dict) and want.get("gate") is not None:
        _gate_dialog(api_base, ticker, p, want["gate"], kit)
    elif isinstance(want, dict) and want.get("ev") is not None:
        _readout_dialog(ticker, p, want["ev"])
    elif isinstance(want, dict) and want.get("more"):
        _more_dialog(ticker, p, want["more"], want.get("area"))


def render(api_base: str, ticker: str, kit=None) -> bool:
    """Draw the tab body for ``ticker``. False when the payload cannot be read or the
    model was not, so the caller can draw today's tab instead of an empty one."""
    resolved = st.session_state.pop(f"cat_resolved_{ticker}", None)
    if resolved is not None:
        _fetch_complete.clear()          # a resolve moved the book: read it again
        _close(ticker)
    try:
        p = fetch(api_base, ticker)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    if not p or not p.get("model_ok"):
        return False
    said = kit.stake_resolved_note(resolved) if (kit is not None and resolved is not None) else ""
    if said:
        st.toast(said)
    _body(api_base, ticker, p, kit)
    return True
