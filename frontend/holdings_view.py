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
.hd .hd-e{margin:0 0 10px;font-size:12px;color:var(--muted)}
.hd .hd-e .bar{display:flex;height:10px;border-radius:2px;overflow:hidden;margin:5px 0 5px}
.hd .hd-e .bar span{display:block;min-width:2px}
.hd .hd-e .keys{display:flex;flex-wrap:wrap;gap:3px 16px;margin:0 0 4px}
.hd .hd-e .k{white-space:nowrap} .hd .hd-e .k b{color:var(--text);font-weight:600}
.hd .hd-e .k i{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px}
.hd .hd-e .k em{font-style:normal}
.hd .hd-c{margin:0 0 8px}
.hd .hd-c .plot{position:relative;height:130px;margin:0 150px 18px 34px}
.hd .hd-c svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.hd .hd-c path{fill:none;stroke-width:1.8;vector-effect:non-scaling-stroke}
.hd .hd-c path.v{stroke:var(--text)} .hd .hd-c path.s{stroke:var(--up);stroke-dasharray:6 4}
.hd .hd-c path.p{stroke:var(--muted);stroke-dasharray:2 3}
.hd .hd-c .g{stroke:var(--rule);stroke-width:1;vector-effect:non-scaling-stroke}
.hd .hd-c .end{position:absolute;left:calc(100% + 8px);transform:translateY(-50%);
  font-size:11px;white-space:nowrap}
.hd .hd-c .end.v{color:var(--text);font-weight:600} .hd .hd-c .end.s{color:var(--up)}
.hd .hd-c .end.p{color:var(--muted)}
.hd .hd-c .yl{position:absolute;right:calc(100% + 6px);transform:translateY(-50%);
  font-size:10px;color:var(--muted)}
.hd .hd-c .xl{position:absolute;top:calc(100% + 4px);font-size:10px;color:var(--muted)}
.hd .hd-c .cap{font-size:11px;color:var(--muted)}
.hd .hd-t{max-height:calc(100vh - 556px);overflow:auto;border-top:1px solid var(--rule)}
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
    # Transfers of shares are counted as money put in (backend/my_portfolio.py), so what is
    # left is small: currency conversion fees, interest. Said only when it is not.
    if other is not None and abs(other) >= 20:
        note = (f" · not itemised by the API {_money(other, cur, True)} (fees, interest, or a "
                f"movement the API does not list)")
    return f'<div class="hd-k">{head}</div><div class="hd-s">Where the gain came from: {words}{note}.</div>'


# Theme colours from the house tokens, in the order themes are listed (largest first).
_THEME_COLOURS = ("var(--fda)", "var(--phase-approved)", "var(--purple-book)",
                  "var(--orange-book)", "var(--fda-bio)", "var(--phase-filed)",
                  "var(--muted)", "var(--rule-strong)")


def _exposure(mine: dict) -> str:
    """Where the money is: the cash and what it is for, the invested value by theme as one
    bar with each theme's share and return, and how concentrated it is by size. Facts only."""
    e = mine.get("exposure") or {}
    if not e.get("themes"):
        return ""
    cur = mine.get("currency") or "GBP"
    cash = ""
    if e.get("cash") is not None:
        purpose = f", {escape(e['cash_note'])}" if e.get("cash_note") else ""
        cash = (f"Cash {_money(e['cash'], cur)}, {_pct(e.get('cash_share'), signed=False, dp=0)} "
                f"of the account{purpose} · invested {_money(e.get('invested'), cur)} in "
                f"{e.get('positions')} positions")
    segs, keys = [], []
    for i, t in enumerate(e["themes"]):
        colour = _THEME_COLOURS[i % len(_THEME_COLOURS)]
        share = t.get("share") or 0
        segs.append(f'<span style="flex:{share:.4f};background:{colour}" '
                    f'title="{escape(t["theme"])} {share:.0%}"></span>')
        keys.append(f'<span class="k"><i style="background:{colour}"></i>{escape(t["theme"])} '
                    f'<b>{share:.0%}</b> {_money(t["value"], cur)} '
                    f'<em class="{_tone(t.get("return"))}">{_pct(t.get("return"))}</em>'
                    f'{holdings_note(t)}</span>')
    sm = e.get("small") or {}
    size = (f"Top three positions {_pct(e.get('top3_share'), signed=False, dp=0)} of invested · "
            f"{sm.get('count')} under {_money(sm.get('threshold'), cur)}, "
            f"{_money(sm.get('value'), cur)} together, {_pct(sm.get('share'), signed=False, dp=0)} "
            f"of invested")
    return (f'<div class="hd-e"><div class="l">{cash}</div><div class="bar">{"".join(segs)}</div>'
            f'<div class="keys">{"".join(keys)}</div><div class="l">{size}</div></div>')


def holdings_note(theme: dict) -> str:
    n = theme.get("holdings") or 0
    return f" · {n} holdings" if n > 1 else ""


def _chart(hist: dict) -> str:
    """The account as a unit price, 100 on the day it first held 100 or more, so money put
    in moves the value and never the line, beside the S&P 500 and PPH in the account's
    currency on the same base. The lines are an SVG stretched to the width; the labels are
    HTML laid over it, so the type never stretches with them."""
    dates = hist.get("dates") or []
    lines = [("You", hist.get("index") or [], "v"),
             ("S&P 500", hist.get("sp500_index") or [], "s"),
             ("PPH", hist.get("pph_index") or [], "p")]
    first = next((i for i, v in enumerate(lines[0][1]) if v is not None), None)
    if first is None or len(dates) - first < 2:
        return ""
    allv = [v for _l, seq, _c in lines for v in seq[first:] if v is not None]
    lo, hi = min(allv + [100.0]), max(allv + [100.0])
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    n = len(dates) - first
    x = lambda i: 100 * (i - first) / (n - 1)
    y = lambda v: 100 * (1 - (v - lo) / (hi - lo))
    paths = []
    for _label, seq, cls in lines:
        pts = [f"{'M' if not k else 'L'}{x(i):.2f},{y(v):.2f}"
               for k, (i, v) in enumerate((i, v) for i, v in enumerate(seq)
                                         if i >= first and v is not None)]
        paths.append(f'<path d="{"".join(pts)}" class="{cls}"/>')
    base = f'<line x1="0" x2="100" y1="{y(100):.2f}" y2="{y(100):.2f}" class="g"/>'
    # End labels sorted by height and pushed apart, so two lines ending close together
    # never print over each other.
    placed = sorted(((y(last), label, cls, last) for label, seq, cls in lines
                     for last in [next((v for v in reversed(seq) if v is not None), None)]
                     if last is not None))
    tops, gap = [], 11.0
    for top, *_rest in placed:
        tops.append(max(top, tops[-1] + gap) if tops else top)
    ends = [f'<span class="end {cls}" style="top:{top:.1f}%">{escape(label)} '
            f'{_pct((last - 100) / 100)}</span>'
            for top, (_y, label, cls, last) in zip(tops, placed)]
    ticks = [f'<span class="yl" style="top:{y(v):.1f}%">{v:.0f}</span>'
             for v in sorted({round(lo + pad), 100, round(hi - pad)})]
    months, seen, last_x = [], set(), -100.0
    for i in range(first, len(dates)):
        if dates[i][:7] not in seen:
            seen.add(dates[i][:7])
            if x(i) - last_x >= 8:               # a month a few days in is not labelled
                months.append(f'<span class="xl" style="left:{x(i):.1f}%">'
                              f'{dt_label(dates[i])}</span>')
                last_x = x(i)
    return (f'<div class="hd-c"><div class="plot"><svg viewBox="0 0 100 100" '
            f'preserveAspectRatio="none" role="img" aria-label="Account unit price since '
            f'{dates[first]}">{base}{"".join(paths)}</svg>{"".join(ticks)}{"".join(ends)}'
            f'{"".join(months)}</div><div class="cap">Your account as a unit price, 100 on '
            f'{escape(dates[first])}: deposits and transfers move the value, not the line. '
            f'The S&amp;P 500 and PPH in pounds on the same base.</div></div>')


def dt_label(day: str) -> str:
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    return f"{int(day[8:10])} {months[int(day[5:7]) - 1]}"


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
            hist = _read(api_base, "/portfolio/history")
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
    chart = _chart(hist) if hist.get("ok") else ""
    if hist.get("ok") and hist.get("left_out"):
        note += (" Left out of the chart, no matching price series: "
                 + ", ".join(escape(n) for n in hist["left_out"]) + ".")
    st.markdown(_CSS + f'<div class="hd">{_summary(perf)}{_exposure(mine)}{chart}'
                f'{_table(mine)}'
                f'<div class="hd-n">{note}</div></div>', unsafe_allow_html=True)
