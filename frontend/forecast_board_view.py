"""The Forecast tab's figures, built from the board (``GET /companies/{t}/forecast-board``).

The page is two parts, the company and its assets, and each part is charts the reader
can change: what is plotted, how it is split, each year or cumulative, weighted by the
chances or in full. Everything here is pure: a board in, a string of SVG or HTML out, so
every choice of every chart can be drawn in a test without a server.

Nothing is computed that the board does not carry. A choice picks series and adds bands
up; where a series is not on file the chart draws a gap and the caption says why, and a
missing value is never drawn as nil.
"""

from __future__ import annotations

import hashlib
import html
import math

from components import charts as CH
from components import tokens as TK

REVISION = 7

# ----------------------------------------------------------------------- the choices
MEASURES = {"revenue": "Revenue", "operating_profit": "Operating profit",
            "free_cash_flow": "Free cash flow", "cash_uses": "Where cash went",
            "costs": "Costs", "rd": "R&D", "capex": "Capex"}
SPLITS = {"group": "By source", "product": "By product", "none": "Total"}
VIEWS = {"year": "Each year", "cum": "Cumulative"}
BASES = {"weighted": "Weighted by chances", "success": "If all succeed"}
VALUE_VIEWS = {"source": "By source", "area": "By area", "evidence": "By evidence"}
ASSET_MEASURES = {"value": "Value a share", "peak": "Peak revenue",
                  "revenue_year": "Revenue in a year", "fcf_year": "Cash flow in a year",
                  "chance": "Chance", "exclusivity": "Exclusivity left"}
ASSET_SHOWS = {"all": "All", "marketed": "On sale", "pipeline": "Pipeline"}
ASSET_VIEWS = {"time": "Over time", "pair": "Two measures"}
TIME_MEASURES = {"revenue": "Revenue", "free_cash_flow": "Free cash flow",
                 "cum_cash": "Cumulative cash"}
TOP_PRODUCTS = 8
USES_YEARS = 10
TOP_LINES = 5

GROUP_NAME = {"marketed": "Products on sale", "lines": "Other revenue lines",
              "pipeline": "Named pipeline", "assumed": "Launches the model assumes"}
GROUP_ORDER = ("marketed", "lines", "pipeline", "assumed")
NEW_PLANT = "New plant for added revenue"
# The part of a reported year's revenue no product's own filed figure carries.
REPORTED_REST = "Reported, not by product"
WORKING = "Working capital for growth"
USE_NAME = {"capex": "Capex", "acquisitions": "Acquisitions",
            "intangibles": "Intangibles bought", "dividends": "Dividends",
            "buybacks": "Share buybacks"}
COST_NAME = {"cost_of_goods": "Cost of goods", "sga": "SG&A", "rd": "R&D",
             "other_costs": "Other costs", "tax": "Tax"}
EVIDENCE_NAME = {"evidence": "Filed or measured", "partial evidence": "Analogue or range",
                 "assumption": "Judgement or convention"}


def _mix(a: str, b: str, t: float) -> str:
    """Token colour ``a`` moved a share ``t`` of the way to ``b``: a derived shade."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


GREY = _mix(TK.MUTED, TK.GROUND, 0.35)
GROUP_COLOUR = {"marketed": TK.UP, "lines": GREY, "pipeline": TK.PURPLE_BOOK,
                "assumed": TK.ORANGE_BOOK}
COST_COLOUR = {"cost_of_goods": TK.ORANGE_BOOK, "sga": TK.PURPLE_BOOK, "rd": TK.UP,
               "other_costs": GREY, "tax": TK.FLAG}
EVIDENCE_COLOUR = {"evidence": TK.UP, "partial evidence": TK.FLAG, "assumption": TK.DOWN}
USE_COLOUR = {"capex": TK.ORANGE_BOOK, "acquisitions": TK.PURPLE_BOOK,
              "intangibles": TK.FDA_BIO, "dividends": TK.UP, "buybacks": TK.FLAG}
_BASE = [TK.UP, TK.PURPLE_BOOK, TK.FLAG, TK.FDA, TK.DOWN, TK.FDA_BIO,
         TK.PHASE_RAMP["Phase 2"], _mix(TK.UP, TK.TEXT, 0.5)]
REPORTED_COLOUR = _mix(TK.MUTED, TK.GROUND, 0.15)


# ------------------------------------------------------------------------ small tools
def _esc(text) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def at(series, year):
    """A year's value from a board series. The API sends year keys as text and a test
    builds them as numbers; both read."""
    if not series:
        return None
    got = series.get(str(year))
    return series.get(year) if got is None else got


def scale(values) -> tuple:
    """(divisor, unit word, formatter) for figures held in millions: billions once the
    largest is ten thousand million, so an axis never prints six digits."""
    top = max((abs(v) for v in values if v is not None), default=0.0)
    if top >= 10000:
        return 1000.0, "bn", lambda v: f"{CH.MINUS if v < 0 else ''}{abs(v) / 1000:,.1f}"
    return 1.0, "mm", lambda v: f"{CH.MINUS if v < 0 else ''}{abs(v):,.0f}"


def _ticks(lo: float, hi: float, count: int = 4) -> list:
    """Round axis values across lo..hi, always through zero where the span crosses it."""
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / max(count, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    out, v = [], math.floor(lo / step + 1e-9) * step
    while True:                                # the last tick is at or above the top
        out.append(round(v, 10))
        if v >= hi - step * 1e-9:
            return out
        v += step


# What makes a chart answer the hand: a readout that follows the cursor, columns that
# rise from the axis when the choice changes, and a legend entry that dims the bands it
# does not name. All of it CSS inside the drawing, so it works wherever the SVG is put.
# The rise holds no transform once it has run, and the card is opaque: a column left on
# a layer of its own under a translucent card was painted dim for the card's whole width.
SLOTS = 14
CHART_CSS = (
    ".fb-hit .fb-tip{display:none;pointer-events:none}"
    ".fb-hit:hover .fb-tip{display:block}"
    ".fb-col{animation:fbgrow .22s ease-out}"
    "@keyframes fbgrow{from{transform:scaleY(0)}to{transform:scaleY(1)}}"
    ".fb-bar{transition:opacity .12s}.fb-lg{cursor:default}"
    + "".join(f"svg:has(.fb-lg.l{i}:hover) .fb-bar:not(.b{i}){{opacity:.2}}"
              for i in range(SLOTS))
    + "@media (prefers-reduced-motion:reduce){.fb-col{animation:none}}")


def _key(*parts) -> str:
    """An id for a drawing's own patterns, from what it draws. The same chart drawn twice
    is the same markup, so a rerun that changed nothing does not replay its columns."""
    return "fb" + hashlib.md5(repr(parts).encode("utf-8")).hexdigest()[:8]


def _legend(entries: list, width: float, pad_l: float, pad_r: float, hid: str) -> tuple:
    """A wrapping legend: (markup, height). Laid out first, since the plot starts under
    it and nine bands need two rows at half a page. Each entry is a group of its own, so
    resting on one dims every band it does not name."""
    out, lx, row = [], pad_l, 0
    for e in entries:
        w = 16 + 6.3 * len(str(e["name"])) + 14
        if lx + w > width - pad_r and lx > pad_l:
            lx, row = pad_l, row + 1
        ly = 12 + 16 * row
        fill = f"url(#{hid}{e['slot']})" if e.get("hatched") else e["colour"]
        out.append(f'<g class="fb-lg l{e["slot"]}"><rect x="{lx - 2:.1f}" y="{ly - 11}"'
                   f' width="{w - 8:.1f}" height="14" fill="transparent"/>'
                   f'<rect x="{lx:.1f}" y="{ly - 9}" width="10" height="10" fill="{fill}"'
                   + (f' stroke="{e["colour"]}" stroke-width="0.8"' if e.get("hatched")
                      else "") + "/>"
                   + CH._text(lx + 14, ly, e["name"], 10, TK.TEXT, family=CH.UI) + "</g>")
        lx += w
    return "".join(out), 20 + 16 * row


def _readout(cx: float, top: float, floor: float, left: float, right: float, title: str,
             rows: list, foot: str = "", gap: float = 10.0) -> str:
    """The card a column shows while the cursor is on it: the year, then a line a band
    with its figure and its share, and a foot for what else is true of the year. Set to
    the side of the column with the room, so it never covers the column it reads. No
    rule is drawn down the plot: the column under the cursor is the mark."""
    names = max([len(r["name"]) for r in rows] + [len(title), 8])
    figures = max([len(r["figure"]) + len(r.get("share") or "") for r in rows] + [4])
    w = min(max(54 + names * 5.6 + figures * 6.2, 150), 300)
    foot_lines = [foot[i:i + 46] for i in range(0, len(foot), 46)] if foot else []
    h = 24 + 14 * len(rows) + (6 + 12 * len(foot_lines) if foot_lines else 0)
    x0 = cx + gap if cx + gap + w <= right else cx - gap - w
    x0 = min(max(x0, left), right - w)
    y0 = top + 2
    out = [f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h}" rx="2"'
           f' fill="{TK.PANEL}" stroke="{TK.RULE_STRONG}"/>',
           CH._text(x0 + 9, y0 + 15, title, 10.5, TK.TEXT, family=CH.MONO, weight="700")]
    for k, r in enumerate(rows):
        ry = y0 + 30 + 14 * k
        if r.get("colour"):
            out.append(f'<rect x="{x0 + 9:.1f}" y="{ry - 8}" width="8" height="8"'
                       f' fill="{r["colour"]}"' + (' fill-opacity="0.35" stroke="'
                                                  + r["colour"] + '" stroke-width="0.8"'
                                                  if r.get("hatched") else "") + "/>")
        strong = "700" if r.get("strong") else ""
        out.append(CH._text(x0 + 22, ry, r["name"], 9.5, TK.TEXT, family=CH.UI,
                            weight=strong))
        out.append(CH._text(x0 + w - (40 if r.get("share") is not None else 9), ry,
                            r["figure"], 9.5, TK.TEXT, "end", CH.MONO, strong))
        if r.get("share"):
            out.append(CH._text(x0 + w - 9, ry, r["share"], 9, TK.MUTED, "end", CH.MONO))
    for k, line in enumerate(foot_lines):
        out.append(CH._text(x0 + 9, y0 + 34 + 14 * len(rows) + 12 * k, line, 9, TK.FLAG,
                            family=CH.UI))
    return "".join(out)


# ---------------------------------------------------------------------- chart builders
def columns(x_labels: list, bands: list, *, width: int = 820, height: int = 330,
            fmt=None, split_at: int | None = None, notes: dict | None = None,
            notes_label: str = "", label: str = "columns", rule_at: tuple | None = None,
            reference: dict | None = None, unit: str = "") -> str:
    """Stacked columns by year. Each band is {name, colour, values, hatched?}.

    A positive value stacks up from nil and a negative one down, so a charge is seen
    under the cash it comes off, and where a column carries both the net is marked on it
    and printed above it. A None is a gap in its band, never a nil. ``split_at`` is the
    index of the first forecast year: a rule is drawn before it and the years on either
    side are named, because a filed figure and a modelled one are two kinds of number.
    ``notes`` is {index: [{name, share}]}, the products that lose exclusivity in a year:
    a strip under the axis with a tick a product, its height the product's share of the
    value. ``rule_at`` is (index, words): a second rule before that column, for the year
    the figures change kind again. ``reference`` is {name, values, colour}, a line with a
    dot a year over the columns, for the figure the stack is read against. ``unit`` is
    printed once, at the head of the axis.

    The cursor on a column shows that year's card: each band's figure and its share of
    the total, the net, the reference and the products that lose exclusivity in it. Only
    on the column: the space above a short one is not it, so a card never opens for a
    year the cursor is merely passing over.
    """
    fmt = fmt or (lambda v: f"{v:,.0f}")
    bands = [b for b in bands if any(v is not None for v in b["values"])]
    n = len(x_labels)
    if not bands or not n:
        return ""
    pad_l, pad_r, bottom = 50, 12, 24 + (26 if notes else 0)
    hid = _key(x_labels, [b["name"] for b in bands], width)
    entries = [{**b, "slot": i} for i, b in enumerate(bands)]
    ref_vals = list((reference or {}).get("values") or [])
    legend, legend_h = _legend(
        entries + ([{**reference, "slot": "r"}] if reference else []),
        width, pad_l, pad_r, hid)
    top = legend_h + 16
    floor = height - bottom
    ups = [sum(max(b["values"][i] or 0.0, 0.0) for b in bands) for i in range(n)]
    downs = [sum(min(b["values"][i] or 0.0, 0.0) for b in bands) for i in range(n)]
    seen = [v for v in ref_vals if v is not None]
    ticks = _ticks(min(downs + seen + [0.0]), max(ups + seen + [0.0]) or 1.0)
    lo, hi = ticks[0], ticks[-1]
    y = CH._scale((lo, hi), (floor, top))
    slot = (width - pad_l - pad_r) / n
    col_w = min(slot * 0.68, 40)
    out = [CH._svg_open(width, height, label), f"<style>{CHART_CSS}</style>",
           "<defs>" + "".join(CH._hatch(f"{hid}{e['slot']}", e["colour"])
                              for e in entries if e.get("hatched")) + "</defs>", legend]
    if unit:
        out.append(CH._text(pad_l - 6, top - 10, unit, 8.5, TK.MUTED, "end", CH.MONO))
    for t in ticks:
        out.append(f'<line x1="{pad_l}" y1="{y(t):.1f}" x2="{width - pad_r}" y2="{y(t):.1f}"'
                   f' stroke="{TK.RULE_STRONG if t == 0 else TK.RULE}"'
                   f' stroke-width="{1 if t == 0 else 0.6}"/>')
        out.append(CH._text(pad_l - 6, y(t) + 3.2, fmt(t), 9, TK.MUTED, "end", CH.MONO))
    if split_at and 0 < split_at < n:
        sx = pad_l + slot * split_at
        # In the muted colour, not the hairline's: on the dark ground the hairline was
        # too faint to read as where the figures stop being filed and start being modelled.
        out.append(f'<line x1="{sx:.1f}" y1="{top - 12}" x2="{sx:.1f}" y2="{floor}"'
                   f' stroke="{TK.MUTED}" stroke-width="1.2" stroke-dasharray="4,3"/>')
        out.append(CH._text(sx - 5, top - 4, "reported", 8.5, TK.MUTED, "end", CH.MONO))
        out.append(CH._text(sx + 5, top - 4, "forecast", 8.5, TK.MUTED, "start", CH.MONO))
    if rule_at and 0 < rule_at[0] < n:
        rx = pad_l + slot * rule_at[0]
        out.append(f'<line x1="{rx:.1f}" y1="{top - 12}" x2="{rx:.1f}" y2="{floor}"'
                   f' stroke="{TK.RULE_STRONG}" stroke-width="1" stroke-dasharray="1,3"/>')
        out.append(CH._text(rx + 5, top - 4, rule_at[1], 8.5, TK.MUTED, "start", CH.MONO))
    widest = max(len(str(lab)) for lab in x_labels) * 5.6 + 4
    every = max(1, math.ceil(widest / slot))
    # the figure over a column needs more room than its year does
    figures = max(1, math.ceil(31 / slot))
    zero = y(0)
    cards = []
    for i, lab in enumerate(x_labels):
        cx = pad_l + slot * i + slot / 2
        up = down = 0.0
        drawn, read = [], []
        for e in entries:
            v = e["values"][i]
            if v is None or v == 0:
                continue
            if v > 0:
                y0, y1 = y(up), y(up + v)
                up += v
            else:
                y0, y1 = y(down), y(down + v)
                down += v
            fill = f"url(#{hid}{e['slot']})" if e.get("hatched") else e["colour"]
            drawn.append(f'<rect class="fb-bar b{e["slot"]}" x="{cx - col_w / 2:.1f}"'
                         f' y="{min(y0, y1):.1f}" width="{col_w:.1f}"'
                         f' height="{max(abs(y0 - y1), 0.6):.1f}" fill="{fill}"'
                         + (f' stroke="{e["colour"]}" stroke-width="0.8"'
                            if e.get("hatched") else "")
                         + f'><title>{_esc(lab)} {_esc(e["name"])} {_esc(fmt(v))}</title>'
                           '</rect>')
            read.append({"name": e["name"], "colour": e["colour"], "value": v,
                         "hatched": e.get("hatched")})
        if drawn:
            # one group a column, so the column rises from the axis as a whole
            out.append(f'<g class="fb-col" style="transform-origin:0 {zero:.1f}px">'
                       + "".join(drawn) + "</g>")
        net = up + down
        if down < 0 and up > 0 and not reference:
            out.append(f'<line x1="{cx - col_w / 2 - 2:.1f}" y1="{y(net):.1f}"'
                       f' x2="{cx + col_w / 2 + 2:.1f}" y2="{y(net):.1f}" stroke="{TK.TEXT}"'
                       f' stroke-width="1.6"/>')
        if (up or down) and i % figures == 0 and not reference:
            out.append(CH._text(cx, y(up) - 4 if up else y(0) - 4, fmt(net), 8.5, TK.TEXT,
                                "middle", CH.MONO))
        if i % every == 0:
            out.append(CH._text(cx, floor + 14, lab, 9.5, TK.MUTED, "middle", CH.MONO))
        ref = ref_vals[i] if i < len(ref_vals) else None
        if not read and ref is None:
            continue
        shares = down == 0 and up > 0 and len(read) > 1
        rows = [{"name": r["name"], "colour": r["colour"], "hatched": r["hatched"],
                 "figure": fmt(r["value"]),
                 "share": f"{r['value'] / up:.0%}" if shares else None}
                for r in reversed(read)]              # top of the stack first
        if len(read) > 1:
            rows.append({"name": "Net" if down < 0 else "Total", "figure": fmt(net),
                         "strong": True, "share": "" if shares else None})
        if ref is not None:
            rows.append({"name": reference["name"], "colour": reference["colour"],
                         "figure": fmt(ref), "share": "" if shares else None})
        ends = (notes or {}).get(i) or []
        foot = ("exclusivity ends: " + ", ".join(p["name"] for p in ends)) if ends else ""
        if not read:
            continue                   # a reference alone is a dot, not a column to rest on
        hy0, hy1 = y(up), y(down)      # the column itself, top of the stack to its foot
        cards.append(
            f'<g class="fb-hit"><rect x="{cx - col_w / 2:.1f}" y="{hy0:.1f}"'
            f' width="{col_w:.1f}" height="{max(hy1 - hy0, 4.0):.1f}" fill="transparent"/>'
            f'<g class="fb-tip">'
            + _readout(cx, top, floor, pad_l, width - pad_r,
                       f"{lab}" + (f"  {unit}" if unit else ""), rows, foot,
                       gap=col_w / 2 + 6)
            + "</g></g>")
    if reference:
        xs = lambda i: pad_l + slot * i + slot / 2          # noqa: E731
        CH._polyline_runs(out, ref_vals, xs, y, reference["colour"], 1.6)
        for i, v in enumerate(ref_vals):
            if v is not None:
                out.append(f'<circle cx="{xs(i):.1f}" cy="{y(v):.1f}" r="2.6"'
                           f' fill="{reference["colour"]}"/>')
    if notes:
        # The exclusivity strip: a track under the forecast years and a tick a product,
        # as tall as the product is large, in the year its exclusivity ends.
        ty = floor + 44
        first = min(notes)
        out.append(f'<line x1="{pad_l + slot * first:.1f}" y1="{ty}" x2="{width - pad_r}"'
                   f' y2="{ty}" stroke="{TK.RULE_STRONG}" stroke-width="1"/>')
        if slot * first >= len(notes_label) * 5.2 + 8:     # only where it has the room
            out.append(CH._text(pad_l + slot * first - 6, ty - 2, notes_label, 8.5,
                                TK.FLAG, "end", CH.MONO))
        biggest = max((p.get("share") or 0.0 for ps in notes.values() for p in ps),
                      default=0.0) or 1.0
        for i, products in notes.items():
            cx = pad_l + slot * i + slot / 2
            step = min(6.0, (slot - 4) / max(len(products), 1))
            x0 = cx - step * (len(products) - 1) / 2
            for k, p in enumerate(products):
                tall = 4.0 + 13.0 * math.sqrt(max(p.get("share") or 0.0, 0.0) / biggest)
                out.append(f'<rect class="fb-loe" x="{x0 + step * k - 1.6:.1f}"'
                           f' y="{ty - tall:.1f}" width="3.2" height="{tall:.1f}" rx="1"'
                           f' fill="{TK.FLAG}"><title>{_esc(p["name"])}: exclusivity ends '
                           f'{_esc(x_labels[i])}'
                           + (f", {p['share']:.0%} of the named value"
                              if p.get("share") is not None else "")
                           + "</title></rect>")
    out += cards                      # last, so a card is over every column it crosses
    out.append("</svg>")
    return "".join(out)


def lines(x_labels: list, series: list, *, width: int = 640, height: int = 330,
          fmt=None, split_at: int | None = None, label: str = "lines",
          unit: str = "") -> str:
    """One line a series, {name, colour, values, dots?}. ``values`` is the forecast and
    ``dots`` the reported years, drawn as rings and not joined to it: a product running
    ahead of or behind its model shows as a ring off the line's start. ``dash_from`` is
    the index of a series' last modelled year: the line is dashed after it. Each line is
    named at its end, the names pushed apart where two end together. The cursor over a
    year marks each line at that year and shows every line's figure for it, largest
    first; a line has no bar to rest on, so the year's own strip of the plot is the
    target."""
    fmt = fmt or (lambda v: f"{v:,.0f}")
    series = [s for s in series if any(v is not None for v in s["values"])
              or any(v is not None for v in s.get("dots") or [])]
    n = len(x_labels)
    if not series or n < 2:
        return ""
    name_w = max(len(str(s["name"])) for s in series) * 5.6 + 12
    pad_l, pad_r, top, bottom = 50, min(max(name_w, 60), 150), 22, 24
    floor = height - bottom
    values = [v for s in series for v in list(s["values"]) + list(s.get("dots") or [])
              if v is not None]
    ticks = _ticks(min(values + [0.0]), max(values + [0.0]) or 1.0)
    y = CH._scale((ticks[0], ticks[-1]), (floor, top))
    x = CH._scale((0, n - 1), (pad_l + 8, width - pad_r))
    out = [CH._svg_open(width, height, label), f"<style>{CHART_CSS}</style>"]
    if unit:
        out.append(CH._text(pad_l - 6, top - 9, unit, 8.5, TK.MUTED, "end", CH.MONO))
    for t in ticks:
        out.append(f'<line x1="{pad_l}" y1="{y(t):.1f}" x2="{width - pad_r}" y2="{y(t):.1f}"'
                   f' stroke="{TK.RULE_STRONG if t == 0 else TK.RULE}"'
                   f' stroke-width="{1 if t == 0 else 0.6}"/>')
        out.append(CH._text(pad_l - 6, y(t) + 3.2, fmt(t), 9, TK.MUTED, "end", CH.MONO))
    if split_at and 0 < split_at < n:
        sx = (x(split_at - 1) + x(split_at)) / 2
        out.append(f'<line x1="{sx:.1f}" y1="{top - 10}" x2="{sx:.1f}" y2="{floor}"'
                   f' stroke="{TK.RULE_STRONG}" stroke-width="1" stroke-dasharray="3,3"/>')
        out.append(CH._text(sx - 5, top - 3, "reported", 8.5, TK.MUTED, "end", CH.MONO))
        out.append(CH._text(sx + 5, top - 3, "forecast", 8.5, TK.MUTED, "start", CH.MONO))
    ends = []
    for s in series:
        cut = s.get("dash_from")
        if cut is None or cut >= n - 1:
            CH._polyline_runs(out, s["values"], x, y, s["colour"], 1.7)
        else:
            # Solid through the last modelled year, dashed where the terminal path runs.
            head = list(s["values"][:cut + 1]) + [None] * (n - cut - 1)
            CH._polyline_runs(out, head, x, y, s["colour"], 1.7)
            tail = [(x(i), y(v)) for i, v in enumerate(s["values"])
                    if i >= cut and v is not None]
            if len(tail) > 1:
                pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in tail)
                out.append(f'<polyline points="{pts}" fill="none" stroke="{s["colour"]}"'
                           ' stroke-width="1.5" stroke-dasharray="4,3" class="carried"/>')
        for i, v in enumerate(s.get("dots") or []):
            if v is not None:
                out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.8" fill="{TK.GROUND}"'
                           f' stroke="{s["colour"]}" stroke-width="1.4" class="reported"/>')
        last = next(((i, v) for i, v in reversed(list(enumerate(s["values"])))
                     if v is not None), None)
        if last:
            ends.append([y(last[1]), x(last[0]), s["name"], s["colour"]])
    ends.sort()
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < 11:
            ends[i][0] = ends[i - 1][0] + 11
    limit = floor                          # names pushed below the axis come back up
    for end in reversed(ends):
        end[0] = min(end[0], limit)
        limit = end[0] - 11
    for ly, lx, name, colour in ends:
        out.append(CH._text(lx + 6, ly + 3, name, 9.5, colour, family=CH.UI,
                            weight="600"))
    step = (width - pad_l - pad_r - 8) / max(n - 1, 1)
    every = max(1, math.ceil(30 / step))
    for i, lab in enumerate(x_labels):
        if i % every == 0:
            out.append(CH._text(x(i), height - 8, lab, 9.5, TK.MUTED, "middle", CH.MONO))
    for i, lab in enumerate(x_labels):
        read = []
        for s in series:
            v = s["values"][i]
            dot = (s.get("dots") or [None] * n)[i]
            if v is None and dot is None:
                continue
            read.append({"name": s["name"] + (", reported" if v is None else ""),
                         "colour": s["colour"], "value": v if v is not None else dot})
        if not read:
            continue
        read.sort(key=lambda r: -r["value"])
        marks = "".join(f'<circle cx="{x(i):.1f}" cy="{y(r["value"]):.1f}" r="3"'
                        f' fill="{r["colour"]}"/>' for r in read)
        out.append(
            f'<g class="fb-hit"><rect x="{x(i) - step / 2:.1f}" y="{top}"'
            f' width="{step:.1f}" height="{floor - top + 16}" fill="transparent"/>'
            '<g class="fb-tip">'
            + _readout(x(i), top, floor, pad_l, width - pad_r,
                       f"{lab}" + (f"  {unit}" if unit else ""),
                       [{"name": r["name"], "colour": r["colour"],
                         "figure": fmt(r["value"])} for r in read])
            + marks + "</g></g>")
    out.append("</svg>")
    return "".join(out)


def hbars(rows: list, *, width: int = 520, fmt=None, label_w: int = 190,
          reference: dict | None = None, row_h: int = 23, label: str = "bars",
          num_w: int = 118, connect: bool = False) -> str:
    """Horizontal bars, one a row: {label, value, start?, colour, hatched?, note?, tip?,
    strong?}. ``start`` floats a bar off the running total, which makes the rows a bridge
    read top to bottom. ``reference`` is {value, label}, a dashed rule down the plot (the
    price a value is read against). connect joins the end of each floated bar to the
    row under it with a hairline, so the eye carries the running total down the bridge.
    A None value prints "no free data" and draws nothing."""
    fmt = fmt or (lambda v: f"{v:,.2f}")
    if not rows:
        return ""
    top = 16 if reference else 6
    height = top + row_h * len(rows) + 6
    spans = [0.0]
    for r in rows:
        if r.get("value") is not None:
            spans += [r.get("start") or 0.0, (r.get("start") or 0.0) + r["value"]]
    if reference and reference.get("value") is not None:
        spans.append(reference["value"])
    lo, hi = min(spans), max(spans)
    if hi == lo:
        hi = lo + 1.0
    x = CH._scale((lo, hi), (label_w, width - num_w))
    hid = _key([r["label"] for r in rows], width, label)
    out = [CH._svg_open(width, height, label),
           "<defs>" + "".join(CH._hatch(f"{hid}{i}", r.get("colour") or TK.MUTED)
                              for i, r in enumerate(rows) if r.get("hatched")) + "</defs>"]
    out.append(f'<line x1="{x(0):.1f}" y1="{top - 2}" x2="{x(0):.1f}" y2="{height - 4}"'
               f' stroke="{TK.RULE_STRONG}"/>')
    if reference and reference.get("value") is not None:
        rx = x(reference["value"])
        out.append(f'<line x1="{rx:.1f}" y1="{top - 2}" x2="{rx:.1f}" y2="{height - 4}"'
                   f' stroke="{TK.FLAG}" stroke-dasharray="4,3" class="reference"/>')
        out.append(CH._text(rx, 9, reference.get("label") or "", 8.5, TK.FLAG, "middle",
                            CH.MONO))
    for i, r in enumerate(rows):
        cy = top + row_h * i + row_h / 2
        strong = bool(r.get("strong"))
        if strong:
            out.append(f'<line x1="0" y1="{cy - row_h / 2:.1f}" x2="{width}"'
                       f' y2="{cy - row_h / 2:.1f}" stroke="{TK.RULE_STRONG}"/>')
        out.append(CH._text(label_w - 8, cy + 3.5, r["label"], 10.5,
                            TK.TEXT if strong else r.get("label_colour") or TK.TEXT, "end",
                            CH.UI, "700" if strong else ""))
        value = r.get("value")
        if value is None:
            out.append(CH._text(label_w + 4, cy + 3.5, "no free data", 9.5, TK.MUTED,
                                family=CH.MONO))
            continue
        start = r.get("start") or 0.0
        x0, x1 = sorted((x(start), x(start + value)))
        colour = r.get("colour") or TK.UP
        fill = f"url(#{hid}{i})" if r.get("hatched") else colour
        out.append(f'<rect x="{x0:.1f}" y="{cy - 5:.1f}" width="{max(x1 - x0, 1.2):.1f}"'
                   f' height="10" fill="{fill}"'
                   + (f' stroke="{colour}" stroke-width="0.8"' if r.get("hatched") else "")
                   + f'><title>{_esc(r.get("tip") or r["label"])} {_esc(fmt(value))}'
                     '</title></rect>')
        out.append(CH._text(width - num_w + 8, cy + 3.5, r.get("text") or fmt(value),
                            10.5, TK.TEXT,
                            family=CH.MONO, weight="700" if strong else "600"))
        if r.get("note"):
            out.append(CH._text(width - 2, cy + 3.5, r["note"], 9, TK.MUTED, "end",
                                CH.MONO))
        if (connect and "start" in r and i + 1 < len(rows)
                and rows[i + 1].get("value") is not None):
            ex = x(start + value)
            out.append(f'<line class="fb-join" x1="{ex:.1f}" y1="{cy + 5:.1f}" x2="{ex:.1f}"'
                       f' y2="{cy + row_h - 5:.1f}" stroke="{TK.MUTED}" stroke-width="0.8"'
                       ' stroke-dasharray="2,2"/>')
    out.append("</svg>")
    return "".join(out)


def bubbles(points: list, *, width: int = 640, height: int = 360, x_label: str = "",
            y_label: str = "", x_fmt=None, y_fmt=None, named: int = 10) -> str:
    """Two measures against each other, one dot an asset: {label, x, y, size, colour,
    hatched?}. The dot's area is its value a share. The largest are named; every dot
    names itself on hover. An asset missing either measure has no place and is left out."""
    x_fmt = x_fmt or (lambda v: f"{v:,.1f}")
    y_fmt = y_fmt or (lambda v: f"{v:,.1f}")
    usable = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if not usable:
        return ""
    pad_l, pad_r, top, bottom = 56, 22, 16, 42
    tx = _ticks(min(p["x"] for p in usable + [{"x": 0.0}]), max(p["x"] for p in usable))
    ty = _ticks(min(p["y"] for p in usable + [{"y": 0.0}]), max(p["y"] for p in usable))
    x = CH._scale((tx[0], tx[-1]), (pad_l, width - pad_r))
    y = CH._scale((ty[0], ty[-1]), (height - bottom, top))
    biggest = max((p.get("size") or 0.0 for p in usable), default=0.0) or 1.0
    out = [CH._svg_open(width, height, "two measures")]
    for t in ty:
        out.append(f'<line x1="{pad_l}" y1="{y(t):.1f}" x2="{width - pad_r}" y2="{y(t):.1f}"'
                   f' stroke="{TK.RULE}" stroke-width="0.6"/>')
        out.append(CH._text(pad_l - 6, y(t) + 3.2, y_fmt(t), 9, TK.MUTED, "end", CH.MONO))
    for t in tx:
        out.append(CH._text(x(t), height - bottom + 14, x_fmt(t), 9, TK.MUTED, "middle",
                            CH.MONO))
    out.append(CH._text((pad_l + width - pad_r) / 2, height - 6, x_label, 10, TK.MUTED,
                        "middle", CH.UI))
    out.append(CH._text(pad_l, 10, y_label, 10, TK.MUTED, "start", CH.UI))
    ranked = sorted(usable, key=lambda p: -(p.get("size") or 0.0))
    for rank, p in enumerate(ranked):
        r = 3.0 + 13.0 * math.sqrt(max(p.get("size") or 0.0, 0.0) / biggest)
        px, py = x(p["x"]), y(p["y"])
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{r:.1f}" fill="{p["colour"]}"'
                   f' fill-opacity="{0.12 if p.get("hatched") else 0.55}"'
                   f' stroke="{p["colour"]}" stroke-width="1"'
                   + (' stroke-dasharray="2,2"' if p.get("hatched") else "")
                   + f'><title>{_esc(p["label"])}: {_esc(x_label)} {_esc(x_fmt(p["x"]))}, '
                     f'{_esc(y_label)} {_esc(y_fmt(p["y"]))}</title></circle>')
        if rank < named:
            anchor = "end" if px > width * 0.72 else "start"
            out.append(CH._text(px + (-(r + 3) if anchor == "end" else r + 3), py + 3,
                                p["label"][:22], 9, TK.TEXT, anchor, CH.UI))
    out.append("</svg>")
    return "".join(out)


# ------------------------------------------------------------------ 1 company over time
def _odds(asset: dict, basis: str) -> float:
    if basis != "weighted":
        return 1.0
    return asset.get("pos") if asset.get("pos") is not None else 1.0


def _asset_year(asset: dict, measure: str, year, basis: str):
    years = asset.get("years") or []
    if year not in years:
        return None
    v = (asset.get("series") or {}).get(measure, [])[years.index(year)]
    return None if v is None else v * _odds(asset, basis)


def exclusivity_notes(board: dict, years: list) -> dict:
    """{index: [{name, share}]} for the forecast years a counted product on sale loses
    exclusivity, the largest by value first, so the falls on the chart have their cause
    under them."""
    out: dict = {}
    for a in board.get("assets") or []:
        if (a.get("kind") != "marketed" or not a.get("counted")
                or a.get("loe_year") not in years or (a.get("share_of_value") or 0) < 0.01
                or a["loe_year"] not in ((board.get("years") or {}).get("forecast") or [])):
            continue
        out.setdefault(years.index(a["loe_year"]), []).append(
            {"name": a["name"], "share": a.get("share_of_value")})
    return out


def _plant(board: dict, company: dict, years: list) -> tuple:
    """(upkeep, new plant, working capital) by year, as the valuation charges them. New
    plant is the capex share of the growth charge and working capital the rest of it;
    upkeep is None where the filer's plant lines are not on file."""
    rule = board.get("capex_rule") or {}
    charge = {y: at(company.get("growth_investment"), y) or 0.0 for y in years}
    if company.get("capex") is None or rule.get("upkeep_rate") is None:
        return None, {y: 0.0 for y in years}, charge
    upkeep = {y: rule["upkeep_rate"] * (at(company.get("revenue"), y) or 0.0) for y in years}
    new = {y: max((at(company["capex"], y) or 0.0) - upkeep[y], 0.0) for y in years}
    return upkeep, new, {y: charge[y] - new[y] for y in years}


def company_figure(board: dict, measure: str = "revenue", split: str = "group",
                   view: str = "year", basis: str = "weighted") -> dict:
    """The company over time as {labels, bands, split_at, notes, unit, fmt, caption}.
    Reported years stand on the left as filed and the forecast on the right; cumulative
    adds the forecast years up from the first and leaves the reported ones off."""
    measure = measure if measure in MEASURES else "revenue"
    case = board.get(basis) or board.get("weighted") or {}
    company, groups = case.get("company") or {}, case.get("groups") or {}
    years_f = list((board.get("years") or {}).get("forecast") or [])
    if measure == "cash_uses":
        # The forecast says only what plant takes, so ten years of it is enough and the
        # width goes to the reported years, where the statement says where cash went.
        years_f = years_f[:USES_YEARS]
    years_r = [] if view == "cum" else list((board.get("years") or {}).get("reported") or [])
    years = years_r + years_f
    pad_r, pad_f = [None] * len(years_r), [None] * len(years_f)
    reported = board.get("reported") or {}
    why = ""

    def fc(series):
        return pad_r + [at(series, y) for y in years_f]

    def rp(key):
        return [at(reported.get(key), y) for y in years_r] + pad_f

    bands, reference = [], None
    upkeep, new_plant, working = _plant(board, company, years_f)
    if measure == "cash_uses":
        # Reported: the cash flow statement's own outlays. Forecast: the plant and the
        # working capital the valuation charges, and what is left, which the model does
        # not allot. The line over both is the cash the business made.
        missing = []
        for key in USE_NAME:
            filed = rp(key)
            if not any(v is not None for v in filed):
                missing.append(USE_NAME[key].lower())
            bands.append({"name": USE_NAME[key], "colour": USE_COLOUR[key], "values": filed})
        # What financing took or gave beyond dividends and buybacks: the statement's own
        # financing total less the two lines above. Above nil is cash paid out, mostly
        # debt repaid; below nil is cash raised, which is how a deal year is funded.
        other = []
        for y in years_r:
            total = at(reported.get("financing"), y)
            other.append(None if total is None else
                         -total - (at(reported.get("dividends"), y) or 0.0)
                         - (at(reported.get("buybacks"), y) or 0.0))
        bands.append({"name": "Debt and other financing, net", "colour": TK.FDA,
                      "values": other + pad_f})
        if upkeep is not None:
            bands.append({"name": "Plant upkeep", "colour": GREY, "values": fc(upkeep)})
            bands.append({"name": NEW_PLANT, "colour": _mix(TK.ORANGE_BOOK, TK.TEXT, 0.35),
                          "values": fc(new_plant)})
        bands.append({"name": WORKING, "colour": TK.DOWN, "values": fc(working)})
        left = {y: at(company.get("free_cash_flow"), y) for y in years_f}
        bands.append({"name": "Left over, use not forecast", "colour": TK.MUTED,
                      "hatched": True, "values": fc(left)})
        made = {y: (left[y] or 0.0) + (at(company.get("growth_investment"), y) or 0.0)
                + ((upkeep or {}).get(y) or 0.0) for y in years_f}
        reference = {"name": "Cash from operations", "colour": TK.TEXT,
                     "values": [at(reported.get("operating_cash_flow"), y)
                                for y in years_r] + [made[y] for y in years_f]}
        why = ((board.get("basis") or {}).get("cash_uses") or "") + (
            "; not on file: " + ", ".join(missing) if missing and years_r else "")
    elif measure == "costs":
        for key in ("cost_of_goods", "sga", "rd", "other_costs", "tax"):
            filed = rp(key) if key != "other_costs" else pad_r + pad_f
            modelled = fc(company.get(key))
            bands.append({"name": COST_NAME[key], "colour": COST_COLOUR[key],
                          "values": [f if f is not None else m
                                     for f, m in zip(filed, modelled)]})
        why = "reported other costs are not a line of their own and are not drawn"
    elif measure == "capex":
        bands.append({"name": "Reported", "colour": REPORTED_COLOUR, "values": rp("capex")})
        rule = board.get("capex_rule") or {}
        if company.get("capex") is None or rule.get("upkeep_rate") is None:
            why = ("no forecast: " + (rule.get("reason")
                                      or "the plant lines are not on file for this company"))
        else:
            bands.append({"name": "Plant upkeep", "colour": GREY, "values": fc(upkeep)})
            bands.append({"name": NEW_PLANT, "colour": TK.ORANGE_BOOK,
                          "values": fc(new_plant)})
            why = rule.get("basis") or ""
    else:
        key = measure
        plant = (key == "free_cash_flow")
        made, spent = rp("operating_cash_flow"), rp("capex")
        both = [m is not None and c is not None for m, c in zip(made, spent)]
        if plant and any(both):
            # Reported free cash flow as its two filed lines, so the plant is seen.
            bands.append({"name": "Operating cash flow", "colour": REPORTED_COLOUR,
                          "values": [m if ok else None for m, ok in zip(made, both)]})
            bands.append({"name": "Capex", "colour": USE_COLOUR["capex"],
                          "values": [-c if ok else None for c, ok in zip(spent, both)]})
        else:
            bands.append({"name": "Reported", "colour": REPORTED_COLOUR, "values": rp(key)})
        # Revenue is the one measure a filer reports by product, so its reported years
        # split as the forecast does: each product's own filed revenue, and the rest of
        # the reported total as one band, named for what it is. Profit, costs and cash
        # are filed for the company alone and stay one reported band.
        by_product = (key == "revenue" and split in ("product", "group") and years_r
                      and any(a.get("reported") for a in board.get("assets") or []))
        products_r = {}
        if by_product:
            for y in years_r:
                got = [at(a.get("reported"), y) for a in board.get("assets") or []]
                got = [v for v in got if v is not None]
                products_r[y] = sum(got) if got else None
            total_r = rp(key)
            rest_r = []
            for y, total in zip(years_r, total_r):
                sold = products_r.get(y)
                rest_r.append(total if sold is None or total is None
                              else max(total - sold, 0.0) or None)
            bands[0] = {"name": REPORTED_REST, "colour": REPORTED_COLOUR,
                        "values": rest_r + pad_f}
        if split == "none":
            bands.append({"name": "Forecast", "colour": TK.UP, "values": fc(company.get(key))})
            plant = False                      # the company's line is already net of it
        elif split == "product":
            ranked = [a for a in board.get("assets") or [] if a.get("counted")]
            head = ranked[:TOP_PRODUCTS]

            def filed(assets):
                """Their reported revenue in each reported year, or the pad."""
                if not by_product:
                    return pad_r
                out = []
                for y in years_r:
                    got = [at(a.get("reported"), y) for a in assets]
                    got = [v for v in got if v is not None]
                    out.append(sum(got) if got else None)
                return out
            for i, a in enumerate(head):
                bands.append({"name": a["name"][:20], "colour": _BASE[i % len(_BASE)],
                              "values": filed([a]) + [_asset_year(a, key, y, basis)
                                                      for y in years_f]})
            rest = {}
            for y in years_f:
                named = sum((at((groups.get(g) or {}).get(key), y) or 0.0)
                            for g in ("marketed", "pipeline"))
                shown = sum((_asset_year(a, key, y, basis) or 0.0) for a in head)
                rest[y] = named - shown
            others = [a for a in board.get("assets") or [] if a not in head]
            if len(ranked) > len(head) or (by_product and any(filed(others))):
                n_others = max(len(ranked) - len(head),
                               sum(1 for o in others if by_product and o.get("reported")))
                bands.append({"name": f"{n_others} smaller products",
                              "colour": TK.RULE_STRONG,
                              "values": filed(others) + [rest.get(y) for y in years_f]})
            for g in ("lines", "assumed"):
                bands.append({"name": GROUP_NAME[g], "colour": GROUP_COLOUR[g],
                              "hatched": g == "assumed",
                              "values": fc((groups.get(g) or {}).get(key))})
        else:
            for g in GROUP_ORDER:
                sold = ([products_r.get(y) for y in years_r] if by_product and g == "marketed"
                        else pad_r)
                bands.append({"name": GROUP_NAME[g], "colour": GROUP_COLOUR[g],
                              "hatched": g == "assumed",
                              "values": sold + [at((groups.get(g) or {}).get(key), y)
                                                for y in years_f]})
        if plant:
            bands.append({"name": NEW_PLANT, "colour": _mix(TK.ORANGE_BOOK, TK.TEXT, 0.35),
                          "values": fc({y: -v for y, v in new_plant.items()})})
            bands.append({"name": WORKING, "colour": TK.DOWN,
                          "values": fc({y: -v for y, v in working.items()})})
        why = (board.get("basis") or {}).get(key) or ""
    for band in bands:                         # a band of nothing but nils is not a band
        if all(v in (None, 0, 0.0) for v in band["values"]):
            band["values"] = [None] * len(years)
    if view == "cum":
        for band in bands + ([reference] if reference else []):
            run, out = 0.0, []
            for v in band["values"]:
                run += v or 0.0
                out.append(run if any(x is not None for x in band["values"]) else None)
            band["values"] = out
    divisor, unit, fmt = scale([v for b in bands for v in b["values"]])
    currency = board.get("currency") or "USD"
    head = (BASES.get(basis, basis).lower()
            + (" · added up from " + str(years_f[0]) if view == "cum" and years_f else ""))
    notes = exclusivity_notes(board, years) if view != "cum" else {}
    carried = (board.get("years") or {}).get("carried_from")
    rule_at = (years.index(carried), "terminal path") if carried in years else None
    return {"labels": [str(y) for y in years], "bands": bands,
            "split_at": len(years_r) or None, "fmt": fmt, "unit": f"{currency} {unit}",
            "notes": notes, "rule_at": rule_at, "reference": reference,
            "caption": head + (" · a tick under a year is a product losing exclusivity, "
                               "as tall as it is large" if notes else "")
            + (" · past the dotted rule a product runs on the path its terminal value "
               "takes" if rule_at else "") + (" · " + why if why else "")}


def company_chart(board: dict, measure: str = "revenue", split: str = "group",
                  view: str = "year", basis: str = "weighted", width: int = 820,
                  height: int = 340) -> tuple:
    """(svg, caption) for chart 1."""
    fig = company_figure(board, measure, split, view, basis)
    svg = columns(fig["labels"], fig["bands"], width=width, height=height, fmt=fig["fmt"],
                  split_at=fig["split_at"], notes=fig["notes"], rule_at=fig["rule_at"],
                  reference=fig["reference"], unit=fig["unit"],
                  notes_label="exclusivity ends", label="the company over time")
    return svg, fig["caption"]


# ------------------------------------------------------------- 2 what the value is made of
_SHORT_SOURCE = {"Launches the model assumes": "Launches the model assumes",
                 "Plant for growth": "Plant and working capital"}


def value_rows(board: dict, view: str = "source") -> list:
    """The equity value a share, split one way, as rows for ``hbars``."""
    value = board.get("value") or {}
    source = value.get("source") or []
    by = {s["label"]: s["per_share"] for s in source}
    assets = [a for a in board.get("assets") or []
              if a.get("counted") and a.get("per_share") is not None]
    named = sum(a["per_share"] for a in assets)
    rows = []
    if view == "source":
        run = 0.0
        for s in source:
            v = s["per_share"]
            colour = (TK.DOWN if v < 0 else TK.ORANGE_BOOK
                      if s["label"] == "Launches the model assumes"
                      else TK.PURPLE_BOOK if s["label"] == "Named pipeline"
                      else GREY if s["label"] in ("Other revenue lines",
                                                  "Rolled forward to today") else TK.UP)
            rows.append({"label": _SHORT_SOURCE.get(s["label"], s["label"]), "value": v,
                         "start": run, "colour": colour,
                         "hatched": s["label"] == "Launches the model assumes",
                         "note": (f"{v / value['equity_per_share']:.0%}"
                                  if value.get("equity_per_share") else "")})
            run += v
        if value.get("equity_per_share") is not None:
            rows.append({"label": "Value a share", "value": value["equity_per_share"],
                         "colour": TK.TEXT, "strong": True})
        return rows
    if view == "area":
        areas: dict = {}
        for a in assets:
            areas[a.get("area") or "No area on file"] = (
                areas.get(a.get("area") or "No area on file", 0.0) + a["per_share"])
        rows = [{"label": k, "value": v, "colour": TK.UP,
                 "note": f"{v / named:.0%}" if named else ""}
                for k, v in sorted(areas.items(), key=lambda kv: -kv[1])]
    else:
        split = {k: 0.0 for k in EVIDENCE_NAME}
        ungraded = 0.0
        for a in assets:
            grades = a.get("evidence") or {}
            n = sum(grades.values())
            if not n:
                ungraded += a["per_share"]
                continue
            for k in split:
                split[k] += a["per_share"] * (grades.get(k) or 0) / n
        rows = [{"label": EVIDENCE_NAME[k], "value": split[k], "colour": EVIDENCE_COLOUR[k],
                 "note": f"{split[k] / named:.0%}" if named else ""} for k in EVIDENCE_NAME]
        if ungraded:
            rows.append({"label": "Not graded", "value": ungraded, "colour": TK.MUTED})
    for label in ("Other revenue lines", "Launches the model assumes"):
        if by.get(label):
            rows.append({"label": _SHORT_SOURCE.get(label, label), "value": by[label],
                         "colour": GREY if label.startswith("Other") else TK.ORANGE_BOOK,
                         "hatched": label.startswith("Launches"),
                         "label_colour": TK.MUTED})
    return rows


def value_chart(board: dict, view: str = "source", width: int = 520) -> tuple:
    """(svg, caption) for chart 2."""
    rows = value_rows(board, view)
    price = (board.get("strip") or {}).get("price")
    ref = ({"value": price, "label": f"price {price:,.2f}"}
           if (view == "source" and price is not None) else None)
    svg = hbars(rows, width=width, reference=ref, label="what the value is made of",
                label_w=178, row_h=27, connect=view == "source")
    caption = {
        "source": "$ a share · each bar starts where the one above ends",
        "area": "$ a share · named assets by therapy area; lines and assumed launches "
                "have none",
        "evidence": "$ a share · each asset's value by the grade of the inputs behind it",
    }.get(view, "")
    return svg, caption


# ------------------------------------------------------------------ 3 what it depends on
def _room(lever: dict, this_year: int):
    """How far a lever can move before the value meets the price, as a share of where
    it stands: of the level for a rate, a scale or a count of years, and of the years
    still ahead for a calendar year."""
    model, brk = lever.get("model"), lever.get("break")
    if model is None or brk is None:
        return None
    if lever.get("kind") == "year":
        ahead = model - this_year
        return abs(model - brk) / ahead if ahead > 0 else None
    return abs(brk - model) / abs(model) if model else None


def depends_rows(breaks: dict, this_year: int, limit: int = 5) -> list:
    """The assumptions the answer is closest to breaking on, nearest first."""
    rows, seen = [], set()
    for lever in (breaks or {}).get("levers") or []:
        if not lever.get("reachable"):
            continue
        room = _room(lever, this_year)
        # The capped and uncapped fades break at one point where the cap does not bind:
        # one row says it.
        same = (lever.get("kind"), lever.get("model"), lever.get("break"))
        if room is None or same in seen:
            continue
        seen.add(same)
        where = lever.get("name") or ""
        company = (breaks.get("name") or "")
        label = (lever["lever"] if where == company else f"{where}: {lever['lever']}")
        rows.append({"label": label[0].upper() + label[1:], "room": room, "lever": lever,
                     "grade": lever.get("evidence_class") or "assumption"})
    rows.sort(key=lambda r: r["room"])
    return rows[:limit]


def depends_chart(breaks: dict, this_year: int, show, width: int = 520) -> tuple:
    """(svg, caption) for chart 3. ``show`` formats a lever's model and break values, the
    page's own formatter, so the figure and the table behind it read the same."""
    rows = depends_rows(breaks, this_year)
    if not rows:
        return "", ""
    bars = []
    for r in rows:
        lever = r["lever"]
        bars.append({"label": r["label"][:30], "value": min(r["room"], 1.0) * 100.0,
                     "text": "over 100%" if r["room"] > 1.0 else None,
                     "colour": EVIDENCE_COLOUR.get(r["grade"], TK.MUTED),
                     "note": show(lever),
                     "tip": f"{r['label']}: the model has {show(lever)}; "
                            f"{lever.get('evidence') or 'ungraded'}"})
    svg = hbars(bars, width=width, fmt=lambda v: f"{v:,.1f}%", label_w=178, num_w=196,
                label="what it depends on", row_h=27)
    word = "fall" if (breaks or {}).get("direction") != "up" else "rise"
    caption = (f"how far each can {word} before the value meets the price, alone, as a "
               "share of where it stands · green filed, amber analogue, red judgement")
    return svg, caption


# ---------------------------------------------------------------------- 4 assets compared
ASSET_CSS = """
.ab { display: grid;
      grid-template-columns: minmax(0, 1fr) 62px minmax(56px, 28%) 62px 78px;
      gap: 0.55rem; align-items: center; font-size: 11.5px; line-height: 1.25;
      padding: 3.5px 6px 3.5px 8px; border-bottom: 1px solid var(--rule);
      border-left: 2px solid transparent; }
.ab:hover { background: var(--panel-hi); border-left-color: var(--up); }
.ab-n { color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ab-s { display: block; color: var(--muted); overflow: visible; }
.ab:hover .ab-s, .ab.pipe .ab-s { color: var(--text); }
.ab.off .ab-s { opacity: 0.45; }
.ab-bar { height: 8px; background: var(--rule); position: relative; }
.ab-bar i { display: block; height: 100%; background: var(--up); }
.ab.pipe .ab-bar i { background: var(--purple-book); }
.ab.neg .ab-bar i { background: var(--down); }
.ab.off .ab-bar i { background: repeating-linear-gradient(135deg, var(--muted) 0 2px,
                    transparent 2px 5px); }
.ab-v { font-family: var(--font-mono); text-align: right; color: var(--text);
        font-weight: 600; white-space: nowrap; }
.ab.off .ab-v, .ab-v.none { color: var(--muted); font-weight: 400; }
.ab-m { font-family: var(--font-mono); font-size: 9.5px; color: var(--muted);
        text-align: right; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ab.pipe .ab-m { color: var(--purple-book); }
.ab-h { display: flex; justify-content: space-between; font-family: var(--font-mono);
        font-size: 9.5px; letter-spacing: 0.06em; text-transform: uppercase;
        color: var(--muted); padding: 7px 8px 3px; border-bottom: 1px solid var(--rule-strong); }
.ab-h span:last-child { color: var(--text); }
.ab-more { margin: 0; }
.ab-more > summary { list-style: none; cursor: pointer; font-family: var(--font-mono);
                     font-size: 10px; letter-spacing: 0.05em; text-transform: uppercase;
                     color: var(--muted); padding: 5px 8px; }
.ab-more > summary::-webkit-details-marker { display: none; }
.ab-more > summary:hover { color: var(--text); }
.ab-tail { font-size: 10.5px; color: var(--muted); padding: 6px 8px 2px; line-height: 1.45; }
.ab-tail b { color: var(--text); font-weight: 500; }
"""
ASSET_TOP = 12


def asset_value(asset: dict, measure: str, basis: str, year=None, this_year=None):
    """One asset's figure on one measure, or None where it has none."""
    odds = _odds(asset, basis)
    if measure == "value":
        if basis != "weighted" and asset.get("per_share_success") is not None:
            return asset["per_share_success"]
        return asset.get("per_share")
    if measure == "peak":
        return None if asset.get("peak_revenue") is None else asset["peak_revenue"] * odds
    if measure == "revenue_year":
        return _asset_year(asset, "revenue", year, basis)
    if measure == "fcf_year":
        return _asset_year(asset, "free_cash_flow", year, basis)
    if measure == "chance":
        return asset.get("pos") if asset.get("kind") == "pipeline" else None
    if measure == "exclusivity":
        if asset.get("loe_year") is None or this_year is None:
            return None
        return max(asset["loe_year"] - this_year, 0)
    return None


def asset_format(measure: str, values: list):
    """The formatter for a measure's figures across the assets shown."""
    if measure == "value":
        return lambda v: f"{CH.MINUS if v < 0 else ''}{abs(v):,.2f}"
    if measure == "chance":
        return lambda v: f"{v:.0%}"
    if measure == "exclusivity":
        return lambda v: f"{v:.0f}y"
    _, unit, fmt = scale(values)
    return lambda v: fmt(v) + unit


def _qualifier(asset: dict, measure: str) -> str:
    if not asset.get("counted"):
        return "placeholder"
    if measure != "value" and asset.get("per_share") is not None:
        return f"${asset['per_share']:,.2f} a share"
    if asset.get("kind") == "pipeline":
        return f"chance {asset['pos']:.0%}" if asset.get("pos") is not None else "pipeline"
    return f"to {asset['loe_year']}" if asset.get("loe_year") else "no date on file"


def spark(asset: dict, years: list, basis: str = "weighted", width: int = 62,
          height: int = 16) -> str:
    """One asset's revenue by year as a line with no axes, on its own scale: the shape,
    which is whether it is growing or running off, with a dot in the year its exclusivity
    ends. An asset with fewer than two years to draw gets an empty cell of the same size,
    so the columns of the list stay in line."""
    values = [_asset_year(asset, "revenue", y, basis) for y in years]
    known = [(i, v) for i, v in enumerate(values) if v is not None]
    box = (f'<svg class="ab-s" viewBox="0 0 {width} {height}" width="{width}"'
           f' height="{height}" aria-hidden="true">')
    top = max((v for _, v in known), default=0.0)
    if len(known) < 2 or top <= 0:
        return box + "</svg>"
    x = CH._scale((0, max(len(years) - 1, 1)), (1.5, width - 1.5))
    y = CH._scale((0.0, top), (height - 2.0, 2.0))
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in known)
    out = [box, f'<polyline points="{pts}" fill="none" stroke="currentColor"'
                ' stroke-width="1.2"/>']
    loe = asset.get("loe_year")
    if loe in years and values[years.index(loe)] is not None:
        i = years.index(loe)
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(values[i]):.1f}" r="2.1"'
                   ' fill="var(--flag)"/>')
    out.append(f"<title>revenue {years[known[0][0]]} to {years[known[-1][0]]}"
               + (f", exclusivity ends {loe}" if loe else "") + "</title></svg>")
    return "".join(out)


def asset_rows(board: dict, measure: str = "value", show: str = "all",
               basis: str = "weighted", year=None, this_year=None) -> list:
    """Every asset as a clickable row for the click list: name, a bar in proportion to
    the largest, the figure, and the fact that qualifies it. A hatched bar is an asset on
    a placeholder: drawn, and left out of the sum. An asset with no figure on the measure
    is listed under the ones that have one and says so."""
    assets = [a for a in board.get("assets") or [] if show == "all" or a.get("kind") == show]
    figures = {a["asset_id"]: asset_value(a, measure, basis, year, this_year) for a in assets}
    known = [v for v in figures.values() if v is not None]
    fmt = asset_format(measure, known)
    top = max((abs(v) for v in known), default=0.0) or 1.0
    years = list((board.get("years") or {}).get("forecast") or [])

    def row(a: dict) -> str:
        v = figures[a["asset_id"]]
        classes = ("ab" + (" pipe" if a.get("kind") == "pipeline" else "")
                   + ("" if a.get("counted") else " off")
                   + (" neg" if (v is not None and v < 0) else ""))
        width = abs(v) / top * 100.0 if v is not None else 0.0
        figure = (f'<span class="ab-v">{_esc(fmt(v))}</span>' if v is not None
                  else '<span class="ab-v none">none</span>')
        return (f'<div class="{classes}" data-id="{a["asset_id"]}">'
                f'<span class="ab-n">{_esc(a.get("name"))}</span>'
                f'{spark(a, years, basis)}'
                f'<span class="ab-bar"><i style="width:{width:.0f}%"></i></span>'
                f'{figure}<span class="ab-m">{_esc(_qualifier(a, measure))}</span></div>')

    def ranked(members: list) -> list:
        return sorted(members, key=lambda a: (figures[a["asset_id"]] is None,
                                              -(figures[a["asset_id"]] or 0.0)))

    rows = []
    groups = [("on sale", ranked([a for a in assets if a.get("kind") == "marketed"])),
              ("pipeline", ranked([a for a in assets if a.get("kind") == "pipeline"]))]
    for label, members in groups:
        if not members:
            continue
        total = sum(a.get("per_share") or 0.0 for a in members if a.get("counted"))
        rows.append({"id": None, "html": f'<div class="ab-h"><span>{_esc(label)} · '
                                         f'{len(members)}</span><span>${total:,.2f} a share'
                                         '</span></div>'})
        head, rest = members[:ASSET_TOP], members[ASSET_TOP:]
        rows += [{"id": a["asset_id"], "html": row(a)} for a in head]
        if rest:
            rest_ps = sum(a.get("per_share") or 0.0 for a in rest if a.get("counted"))
            rows.append({"id": None, "html":
                         f'<details class="ab-more"><summary>{len(rest)} more · '
                         f'${rest_ps:,.2f} a share</summary>'
                         f'{"".join(row(a) for a in rest)}</details>'})
    tail = []
    lines_ = [s for s in board.get("lines") or [] if s.get("per_share") is not None]
    if lines_ and show == "all":
        tail.append("revenue lines no asset carries: " + ", ".join(
            f'<b>{_esc(s["name"])}</b> ${s["per_share"]:,.2f}' for s in lines_))
    assumed = board.get("assumed") or {}
    if assumed.get("per_share") and show == "all":
        tail.append(f'launches the model assumes: <b>${assumed["per_share"]:,.2f}</b>')
    if board.get("not_valued") and show == "all":
        tail.append("not valued: " + ", ".join(_esc(n) for n in board["not_valued"]))
    if tail:
        rows.append({"id": None, "html": f'<div class="ab-tail">{" · ".join(tail)}</div>'})
    return rows


def asset_pair_chart(board: dict, x_measure: str, y_measure: str, show: str = "all",
                     basis: str = "weighted", year=None, this_year=None,
                     width: int = 640, height: int = 380) -> str:
    """Chart 4's second view: one measure across, another up, a dot an asset."""
    assets = [a for a in board.get("assets") or [] if show == "all" or a.get("kind") == show]
    xs = [asset_value(a, x_measure, basis, year, this_year) for a in assets]
    ys = [asset_value(a, y_measure, basis, year, this_year) for a in assets]
    points = [{"label": a["name"], "x": x, "y": y, "size": max(a.get("per_share") or 0.0, 0.0),
               "colour": TK.PURPLE_BOOK if a.get("kind") == "pipeline" else TK.UP,
               "hatched": not a.get("counted")}
              for a, x, y in zip(assets, xs, ys)]
    return bubbles(points, width=width, height=height,
                   x_label=ASSET_MEASURES[x_measure], y_label=ASSET_MEASURES[y_measure],
                   x_fmt=asset_format(x_measure, [v for v in xs if v is not None]),
                   y_fmt=asset_format(y_measure, [v for v in ys if v is not None]))


# ---------------------------------------------------------------------- 5 assets over time
def asset_lines(board: dict, measure: str = "revenue", show: str = "all",
                basis: str = "weighted", width: int = 640, height: int = 380) -> tuple:
    """(svg, caption): the largest assets by year. Reported revenue as rings, the forecast
    as a line; cash flow has no reported years by asset, so its lines start at the model."""
    assets = [a for a in board.get("assets") or []
              if a.get("counted") and (show == "all" or a.get("kind") == show)][:TOP_LINES]
    years_f = list((board.get("years") or {}).get("forecast") or [])
    years_r = (list((board.get("years") or {}).get("reported") or [])
               if measure == "revenue" else [])
    years = years_r + years_f
    key = "revenue" if measure == "revenue" else "free_cash_flow"
    series = []
    for i, a in enumerate(assets):
        values = [_asset_year(a, key, y, basis) for y in years_f]
        if measure == "cum_cash":
            run, out = 0.0, []
            for v in values:
                run += v or 0.0
                out.append(run if any(x is not None for x in values) else None)
            values = out
        to = a.get("modelled_to")
        series.append({"name": a["name"][:20], "colour": _BASE[i % len(_BASE)],
                       "dash_from": years.index(to) if to in years else None,
                       "values": [None] * len(years_r) + values,
                       "dots": [at(a.get("reported"), y) for y in years_r]
                               + [None] * len(years_f)})
    _, unit, fmt = scale([v for s in series for v in s["values"] + s["dots"]])
    currency = board.get("currency") or "USD"
    svg = lines([str(y) for y in years], series, width=width, height=height, fmt=fmt,
                split_at=len(years_r) or None, label="assets over time",
                unit=f"{currency} {unit}")
    caption = (f"the {len(series)} largest by value · "
               f"{BASES.get(basis, basis).lower()}"
               + (" · rings are reported years" if years_r else "")
               + (" · dashed past the modelled years, on the terminal path"
                  if any(s["dash_from"] is not None and s["dash_from"] < len(years) - 1
                         for s in series) else "")
               + (" · each asset charged the company's cost ratios"
                  if measure != "revenue" else ""))
    return svg, caption


def asset_table(board: dict, this_year: int) -> str:
    """Every asset one row, for the reader who wants the numbers in columns."""
    head = ("asset", "stage", "area", "value a share", "share of value", "chance",
            "peak revenue", "peak year", "exclusivity ends", "next event",
            "rests on judgement")
    peaks = [a["peak_revenue"] for a in board.get("assets") or []
             if a.get("peak_revenue") is not None]
    _, unit, fmt = scale(peaks)
    body = ""
    for a in board.get("assets") or []:
        def cell(text, num=False):
            return f'<td class="rs-{"v" if num else "k"}">{_esc(text)}</td>'
        body += "<tr>" + "".join([
            cell(a.get("name")),
            cell("on sale" if a.get("kind") == "marketed" else "pipeline"
                 + ("" if a.get("counted") else ", placeholder")),
            cell(a.get("area") or "·"),
            cell(f"{a['per_share']:,.2f}" if a.get("per_share") is not None else "·", True),
            cell(f"{a['share_of_value']:.1%}" if a.get("share_of_value") is not None
                 else "·", True),
            cell(f"{a['pos']:.0%}" if a.get("kind") == "pipeline" and a.get("pos") is not None
                 else "·", True),
            cell(fmt(a["peak_revenue"]) + unit if a.get("peak_revenue") is not None
                 else "·", True),
            cell(a.get("peak_year") or "·", True),
            cell(a.get("loe_year") or "·", True),
            cell(" ".join(str(x) for x in (a.get("next_date"), a.get("next_label")) if x)
                 or "·"),
            cell(f"{a['assumption_share']:.0%}" if a.get("assumption_share") is not None
                 else "·", True)]) + "</tr>"
    return ('<table class="rs"><thead><tr>' + "".join(f"<th>{h}</th>" for h in head)
            + f"</tr></thead><tbody>{body}</tbody></table>")


# ------------------------------------------------------------------------ the number strip
def strip_items(board: dict, rating: str | None = None) -> list:
    """The company's seven figures as metric tiles: (label, value, unit, change, tone,
    note). A figure not on file is None, which the tile prints as "no free data"."""
    s = board.get("strip") or {}
    gap = s.get("gap")
    tone = "" if gap is None else (" up" if gap >= 0 else " down")
    nxt = s.get("next_catalyst") or {}
    counted = sum(1 for a in board.get("assets") or [] if a.get("counted"))
    return [
        ("value a share", f"${s['value']:,.2f}" if s.get("value") is not None else None, "",
         None, "", "sum of the parts, today"),
        ("price", f"${s['price']:,.2f}" if s.get("price") is not None else None, "", None,
         "", "last close"),
        ("value over price", f"{gap:+.0%}" if gap is not None else None, "", rating, tone,
         ""),
        ("in 12 months", f"${s['twelve_month']:,.2f}" if s.get("twelve_month") is not None
         else None, "", None, "", "rolled at the cost of equity"),
        ("revenue covered", f"{s['coverage']:.0%}" if s.get("coverage") is not None else None,
         "", None, "", f"{counted} assets counted"),
        ("rests on judgement", f"{s['rests_on_assumption']:.0%}"
         if s.get("rests_on_assumption") is not None else None, "", None, "",
         "of the named assets' value"),
        ("next catalyst", nxt.get("expected_date"), "", None, "",
         (nxt.get("title") or nxt.get("catalyst_type") or "")[:40]),
    ]


def asset_strip_items(board: dict) -> list:
    """The asset view's figures: how many are valued and what each kind adds up to, the
    largest and its share of the named value, and the next dated event among them."""
    assets = [a for a in board.get("assets") or [] if a.get("counted")]
    off = len(board.get("assets") or []) - len(assets)

    def group(kind: str) -> tuple:
        members = [a for a in assets if a.get("kind") == kind]
        if not members:
            return None, "none in the book"
        return (f"${sum(a.get('per_share') or 0.0 for a in members):,.2f}",
                f"{len(members)} {'asset' if len(members) == 1 else 'assets'}, a share")

    sale, sale_note = group("marketed")
    pipe, pipe_note = group("pipeline")
    top = max(assets, key=lambda a: a.get("per_share") or 0.0, default=None)
    dated = sorted((a for a in assets if a.get("next_date")), key=lambda a: a["next_date"])
    nxt = dated[0] if dated else None
    return [
        ("assets valued", str(len(assets)), "", None, "",
         f"{off} more on a placeholder" if off else "each on its own evidence"),
        ("on sale", sale, "", None, "", sale_note),
        ("pipeline", pipe, "", None, "", pipe_note + (", after its chances" if pipe else "")),
        ("largest", top["name"][:22] if top else None, "", None, "",
         (f"{top['share_of_value']:.0%} of the named value"
          if top and top.get("share_of_value") is not None else "")),
        ("next gate", nxt["next_date"] if nxt else None, "", None, "",
         (f"{nxt['name'][:20]} · {nxt.get('next_label') or ''}"[:44] if nxt else "")),
    ]
