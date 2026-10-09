"""Your holdings: the user's own Trading 212 account beside the model, on the Universe tab.

Reads ``/portfolio/performance`` and ``/portfolio/mine`` (backend/my_portfolio.py), both
live and never cached by the API; held here so a rerun does not call Trading
212 again within five minutes. Every figure is from the payloads; nothing here computes one. The model's view
beside a holding is the model's, not a recommendation to buy or sell.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from html import escape

import streamlit as st

_CSS = """<style>
.hd{font-size:13px;color:var(--text)}
.hd .hd-k{display:flex;flex-wrap:wrap;gap:6px 28px;margin:2px 0 10px}
.hd .hd-k div{display:flex;flex-direction:column}
.hd .hd-k span{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.hd .hd-k b{font-size:20px;font-weight:600}
.hd .hd-k i{font-style:normal;font-size:11.5px;color:var(--muted)}
.hd .hd-s{color:var(--muted);margin:0 0 12px;line-height:1.5}
.hd .up{color:var(--up)} .hd .down{color:var(--down)}
.hd .hd-t{max-height:calc(100vh - 286px);overflow:auto;border-top:1px solid var(--rule)}
.hd table{border-collapse:collapse;width:100%}
.hd th{position:sticky;top:0;background:var(--ground);z-index:1;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  text-align:right;font-weight:500;padding:4px 8px;border-bottom:1px solid var(--rule)}
.hd th:first-child,.hd td:first-child{text-align:left}
.hd td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;vertical-align:top}
.hd td .sub{display:block;font-size:11px;color:var(--muted)}
.hd tr.out td{color:var(--muted)}
.hd td.up,.hd tr.out td.up{color:var(--up)} .hd td.down,.hd tr.out td.down{color:var(--down)}
.hd .hd-n{color:var(--muted);font-size:11.5px;margin-top:10px;line-height:1.5}
</style>"""


# Five minutes, keyed on the path alone: the tab is drawn on every rerun whichever company
# is picked, so a change of company never waits on Trading 212.
@st.cache_data(ttl=300, show_spinner=False)
def _read(api_base: str, path: str):
    with urllib.request.urlopen(api_base.rstrip("/") + path, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _money(v, cur="GBP", signed=False, pence=False):
    if v is None:
        return "no free data"
    sym = {"GBP": "£", "USD": "$", "EUR": "€"}.get(cur, cur + " ")
    fmt = "{:,.2f}" if pence or abs(v) < 100 else "{:,.0f}"
    text = fmt.format(abs(v))
    sign = ("+" if v >= 0 else "−") if signed else ("−" if v < 0 else "")
    return f"{sign}{sym}{text}"


def _pct(v, signed=True, dp=1):
    if v is None:
        return "no free data"
    sign = ("+" if v >= 0 else "−") if signed else ""
    return f"{sign}{abs(v) * 100:.{dp}f}%"


def _tone(v):
    return "" if v is None else ("up" if v >= 0 else "down")


def _summary(perf: dict) -> str:
    cur = perf.get("currency") or "GBP"
    total, cash = perf.get("total"), perf.get("cash")
    cells = [("Account value", _money(total, cur), "", f"cash {_money(cash, cur)}"
              + (f", {cash / total:.0%}" if total and cash is not None else "")),
             ("Gain since " + str(perf.get("since") or "")[:10],
              _money(perf.get("gain"), cur, True), _tone(perf.get("gain")),
              f"{_pct(perf.get('return'))} money-weighted, not annualised")]
    for b in perf.get("benchmarks") or []:
        cells.append((f"Same cash in {b['label']}", _money(b.get("gain"), cur, True),
                      _tone(b.get("gain")), f"{_pct(b.get('return'))} over the same days"))
    head = "".join(f'<div><span>{escape(k)}</span><b class="{tone}">{v}</b><i>{escape(i)}</i></div>'
                   for k, v, tone, i in cells)
    split = perf.get("split") or {}
    parts = [("price", split.get("unrealised_price")), ("currency", split.get("unrealised_currency")),
             ("dividends", split.get("dividends")), ("realised", split.get("realised"))]
    words = " · ".join(f"{k} {_money(v, cur, True)}" for k, v in parts if v is not None)
    other = split.get("not_itemised")
    note = ""
    if other is not None and abs(other) >= 1:
        rest = (perf.get("gain") or 0) - other
        note = (f" · not itemised by the API {_money(other, cur, True)}: interest on cash or a "
                f"promotion is a gain; money paid in that the API does not list as a deposit is "
                f"not, and then the gain is {_money(rest, cur, True)}")
    return f'<div class="hd-k">{head}</div><div class="hd-s">Where the gain came from: {words}{note}.</div>'


def _gate_cell(row: dict, cur: str) -> str:
    gates = [g for g in row.get("gates") or [] if g.get("pass_adds") is not None]
    if not gates:
        return "no priced gate" if row.get("covered") else ""
    g = max(gates, key=lambda x: abs(x.get("miss_takes") or 0) + abs(x.get("pass_adds") or 0))
    return (f'{escape(str(g.get("asset") or ""))} {escape(str(g.get("date") or "")[:7])}'
            f'<span class="sub">{g["odds"]:.0%} odds · pass {_money(g["pass_adds"], cur, True, True)} '
            f'({_pct(g.get("pass_pct"), dp=2)}) · miss {_money(g["miss_takes"], cur, True, True)} '
            f'({_pct(g.get("miss_pct"), dp=2)})</span>')


def _table(mine: dict) -> str:
    cur = mine.get("currency") or "GBP"
    head = ("<tr><th>Holding</th><th>Value</th><th>Return</th><th>S&amp;P 500, same days</th>"
            "<th>Pick</th><th>Currency</th><th>Model view</th><th>Next catalyst</th>"
            "<th>Biggest priced gate, for this holding</th><th>This week</th></tr>")
    rows = []
    for r in mine.get("rows") or []:
        m = r.get("model") or {}
        model = ""
        if m:
            moved = (f" (was {escape(r['previous_rating'])})"
                     if r.get("previous_rating") and r["previous_rating"] != m.get("rating") else "")
            model = (f'{escape(str(m.get("rating") or ""))}{moved}'
                     f'<span class="sub">{_pct(m.get("upside_12m"))} 12-month upside</span>')
        nxt = r.get("next_catalyst") or {}
        nxt_html = (f'{escape(str(nxt.get("expected_date") or "")[:10])}'
                    f'<span class="sub">{escape(str(nxt.get("asset") or nxt.get("catalyst_type") or ""))}</span>'
                    if nxt else "")
        flags = r.get("flags") or {}
        week = ""
        if flags.get("count"):
            lead = "; ".join(escape(h) for h in flags.get("high") or [])
            week = f'{flags["count"]} changes' + (f'<span class="sub">{lead}</span>' if lead else "")
        rows.append(
            f'<tr class="{"" if r.get("covered") else "out"}">'
            f'<td>{escape(str(r.get("name") or r.get("t212_ticker")))}'
            f'<span class="sub">{escape(str(r.get("t212_ticker") or ""))}</span></td>'
            f'<td>{_money(r.get("value"), cur)}</td>'
            f'<td class="{_tone(r.get("return"))}">{_pct(r.get("return"))}</td>'
            f'<td>{_pct(r.get("market"))}</td>'
            f'<td class="{_tone(r.get("pick"))}">{_pct(r.get("pick"))}</td>'
            f'<td class="{_tone(r.get("fx_effect"))}">'
            f'{_money(r.get("fx_effect"), cur, True) if r.get("fx_effect") is not None else "in pounds"}</td>'
            f'<td>{model}</td><td>{nxt_html}</td><td>{_gate_cell(r, cur)}</td><td>{week}</td></tr>')
    return f'<div class="hd-t"><table>{head}{"".join(rows)}</table></div>'


def render(api_base: str) -> None:
    try:
        with st.spinner("Reading your Trading 212 account"):
            perf = _read(api_base, "/portfolio/performance")
            mine = _read(api_base, "/portfolio/mine")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        st.warning(f"Your holdings did not load: {exc}")
        return
    if not perf.get("ok") or not mine.get("ok"):
        st.info("Your Trading 212 account is not connected: add T212_API_KEY and "
                "T212_API_SECRET to .env (read permissions only).")
        return
    covered = mine.get("covered") or 0
    note = (f"{mine.get('positions')} positions, {covered} in the universe the model covers. "
            "Return is since each holding was first bought, in pounds; the S&amp;P 500 column is "
            "its return over the same days in pounds, and Pick is the difference. A gate's "
            "pounds scale the model's swing a share to this holding's value. The model's view "
            "is the model's, not a recommendation to buy or sell. Read live from your Trading "
            "212 account, read only.")
    st.markdown(_CSS + f'<div class="hd">{_summary(perf)}{_table(mine)}'
                f'<div class="hd-n">{note}</div></div>', unsafe_allow_html=True)
