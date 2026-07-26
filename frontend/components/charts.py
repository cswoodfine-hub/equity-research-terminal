"""Chart primitives: pure functions from data to SVG strings.

Every builder takes its data plus an explicit width and height and returns a
complete ``<svg>`` element. Nothing here reads Streamlit, the network, or the
database, so each is unit-testable and reusable by the tearsheet export.

The absolute rule carried by every primitive: a null is never plotted as zero.
A line breaks, a bar renders a hatched null band, a heatmap cell stays ground,
a waterfall step hatches. Where a mark exists it is real data.

Colour comes only from tokens; colour is never the only signal, so every coloured
mark also carries a label, a position, or a glyph.
"""

from __future__ import annotations

import itertools
import math
from typing import Callable, Optional, Sequence

from components import tokens as TK

MONO = "IBM Plex Mono, ui-monospace, Menlo, monospace"
UI = "Archivo, system-ui, sans-serif"
NARROW = "Archivo Narrow, Archivo, sans-serif"

MINUS = "−"

_ids = itertools.count(1)


def _uid(prefix: str) -> str:
    """Unique id per SVG instance, so two charts on one page cannot share defs."""
    return f"{prefix}{next(_ids)}"


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _fmt(value: Optional[float], decimals: int = 1, dash: str = "—") -> str:
    """A figure at fixed precision; missing is a dash, never zero."""
    if value is None or value != value:
        return dash
    text = f"{abs(value):,.{decimals}f}"
    return f"{MINUS}{text}" if value < 0 else text


def _text(x: float, y: float, s, size: float = 10, fill: str = TK.MUTED,
          anchor: str = "start", family: str = UI, weight: str = "",
          extra: str = "") -> str:
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"'
            f' text-anchor="{anchor}" font-family="{family}"{w}{extra}>'
            f"{_esc(s)}</text>")


def _svg_open(width: int, height: int, label: str) -> str:
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}"'
            f' role="img" aria-label="{_esc(label)}"'
            f' xmlns="http://www.w3.org/2000/svg" style="max-width:100%">')


def _hatch(pattern_id: str, colour: str = TK.MUTED) -> str:
    """Diagonal hatch for a null band: visibly a texture, never a value."""
    return (f'<pattern id="{pattern_id}" patternUnits="userSpaceOnUse" width="6"'
            f' height="6"><path d="M0,6 l6,-6" stroke="{colour}" stroke-width="1"'
            f' opacity="0.55"/></pattern>')


def _polyline_runs(out: list, values: Sequence[Optional[float]],
                   x: Callable[[int], float], y: Callable[[float], float],
                   colour: str, stroke_width: float) -> None:
    """Draw a nullable series as line runs. A null breaks the line; a run of one
    point draws a dot, so a value islanded between nulls is still shown rather
    than silently dropped."""
    run: list[tuple[float, float]] = []

    def flush():
        if len(run) > 1:
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in run)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}"'
                       f' stroke-width="{stroke_width}"/>')
        elif len(run) == 1:
            px, py = run[0]
            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{stroke_width}"'
                       f' fill="{colour}" class="isolated"/>')
        run.clear()

    for i, v in enumerate(values):
        if v is None or v != v:
            flush()
            continue
        run.append((x(i), y(v)))
    flush()


def _domain(values: Sequence[float], zero: bool = False,
            pad: float = 0.08) -> tuple[float, float]:
    """Padded numeric domain; optionally forced through zero."""
    vals = [v for v in values if v is not None and v == v]
    if not vals:
        return (0.0, 1.0)
    lo, hi = min(vals), max(vals)
    if zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    if hi == lo:
        hi = lo + (abs(lo) * 0.1 or 1.0)
    span = hi - lo
    return (lo - (span * pad if not zero or lo < 0 else 0.0), hi + span * pad)


def _scale(domain: tuple[float, float],
           out: tuple[float, float]) -> Callable[[float], float]:
    (d0, d1), (r0, r1) = domain, out
    span = (d1 - d0) or 1.0
    return lambda v: r0 + (v - d0) / span * (r1 - r0)


# --- 1. sparkline ---------------------------------------------------------
def sparkline(values: Sequence[Optional[float]], width: int = 140,
              height: int = 30, label_last: bool = True,
              colour: Optional[str] = None,
              marks: Sequence[int] = ()) -> str:
    """Inline line, no axes; the last value labelled. A null breaks the line.

    ``marks`` are x indices drawn as faint vertical dashes, used for session
    opens on an intraday spark so overnight gaps stay visible without a time
    axis inventing hours that never traded.
    """
    if not values or all(v is None for v in values):
        return ""
    pad_r = 44 if label_last else 4
    lo, hi = _domain(values)
    y = _scale((lo, hi), (height - 3, 3))
    x = _scale((0, max(len(values) - 1, 1)), (2, width - pad_r))

    first = next((v for v in values if v is not None), None)
    last = next((v for v in reversed(values) if v is not None), None)
    stroke = colour or (TK.DOWN if (first is not None and last is not None
                                    and last < first) else TK.UP)

    out = [_svg_open(width, height, "sparkline")]
    for mark in marks:
        out.append(f'<line x1="{x(mark):.1f}" y1="2" x2="{x(mark):.1f}"'
                   f' y2="{height - 2}" stroke="{TK.RULE_STRONG}"'
                   f' stroke-width="1" stroke-dasharray="2,3" class="mark"/>')
    _polyline_runs(out, values, x, y, stroke, 1.4)
    if last is not None:
        lx = x(len(values) - 1)
        ly = y(last)
        out.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="2" fill="{stroke}"/>')
        if label_last:
            out.append(_text(lx + 5, ly + 3.5, _fmt(last, 1), 9, TK.TEXT,
                             family=MONO))
    out.append("</svg>")
    return "".join(out)


# --- 2. line chart --------------------------------------------------------
def line_chart(series: Sequence[dict], x_labels: Sequence[str], width: int = 900,
               height: int = 300, y_fmt: Callable[[float], str] = None,
               hover: bool = True) -> str:
    """Multi-series line. Each series: {name, values, colour, axis: left|right}.

    Series marked axis=right scale on their own zero-free domain; both ends are
    labelled in the series colour so the two scales cannot be confused. A null
    breaks its line rather than bridging. Hover is pure CSS: a slot band per x
    index reveals the values for that index.
    """
    y_fmt = y_fmt or (lambda v: _fmt(v, 1))
    pad_l, pad_r, top, bottom = 54, 54, 12, 24
    plot_w, floor = width - pad_l - pad_r, height - bottom
    n = max(len(x_labels), 2)
    x = _scale((0, n - 1), (pad_l, pad_l + plot_w))

    left = [s for s in series if s.get("axis") != "right"]
    right = [s for s in series if s.get("axis") == "right"]
    dom_l = _domain([v for s in left for v in s["values"]])
    dom_r = _domain([v for s in right for v in s["values"]])
    y_l = _scale(dom_l, (floor, top))
    y_r = _scale(dom_r, (floor, top))

    out = [_svg_open(width, height, "line chart"),
           # Self-contained hover: the rule ships inside the SVG, so the chart
           # behaves identically in the app, a gallery, or an exported tearsheet.
           "<style>.hoverband .tip{display:none}"
           ".hoverband:hover .tip{display:block}</style>"]
    # gridlines: three, quiet
    for frac in (0.0, 0.5, 1.0):
        gy = top + (floor - top) * frac
        out.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + plot_w}"'
                   f' y2="{gy:.1f}" stroke="{TK.RULE}" stroke-width="1"/>')
    # axis end labels
    out.append(_text(pad_l - 6, y_l(dom_l[1]) + 8, y_fmt(dom_l[1]), 9,
                     left[0]["colour"] if left else TK.MUTED, "end", MONO))
    out.append(_text(pad_l - 6, y_l(dom_l[0]) + 1, y_fmt(dom_l[0]), 9,
                     left[0]["colour"] if left else TK.MUTED, "end", MONO))
    if right:
        out.append(_text(pad_l + plot_w + 6, y_r(dom_r[1]) + 8, y_fmt(dom_r[1]), 9,
                         right[0]["colour"], "start", MONO))
        out.append(_text(pad_l + plot_w + 6, y_r(dom_r[0]) + 1, y_fmt(dom_r[0]), 9,
                         right[0]["colour"], "start", MONO))

    # Direct labels replace a legend; when two series end close together the labels
    # are pushed apart, which is exactly when the panel is most worth reading.
    ends = []
    for s in series:
        scale_y = y_r if s.get("axis") == "right" else y_l
        _polyline_runs(out, s["values"], x, scale_y, s["colour"], 1.6)
        last_i, last_v = next(((i, v) for i, v in reversed(list(enumerate(s["values"])))
                               if v is not None), (None, None))
        if last_v is not None:
            ends.append([scale_y(last_v), x(last_i), s["name"], s["colour"]])
    ends.sort()
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < 12:
            ends[i][0] = ends[i - 1][0] + 12
    for ly, lx, name, colour in ends:
        out.append(_text(min(lx + 6, width - 4), ly + 3, name, 9.5, colour,
                         family=UI, weight="600"))

    # x labels: first, middle, last
    for i in {0, (n - 1) // 2, n - 1}:
        if i < len(x_labels):
            out.append(_text(x(i), height - 8, x_labels[i], 9, TK.MUTED, "middle",
                             MONO))

    if hover:
        slot = plot_w / max(n - 1, 1)
        for i, lbl in enumerate(x_labels):
            vals = []
            for s in series:
                v = s["values"][i] if i < len(s["values"]) else None
                if v is not None:
                    vals.append(f"{s['name']} {y_fmt(v)}")
            tip = f"{lbl}  " + "  ".join(vals) if vals else f"{lbl}  no free data"
            band_x = x(i) - slot / 2
            out.append(
                f'<g class="hoverband"><rect x="{band_x:.1f}" y="{top}"'
                f' width="{slot:.1f}" height="{floor - top}" fill="transparent"/>'
                f'<g class="tip"><line x1="{x(i):.1f}" y1="{top}" x2="{x(i):.1f}"'
                f' y2="{floor}" stroke="{TK.MUTED}" stroke-width="1"'
                f' stroke-dasharray="2,2"/>'
                f'<rect x="{min(max(x(i) - 90, pad_l), pad_l + plot_w - 180):.1f}"'
                f' y="{top}" width="180" height="16" fill="{TK.PANEL}"'
                f' stroke="{TK.RULE_STRONG}"/>'
                + _text(min(max(x(i), pad_l + 90), pad_l + plot_w - 90), top + 11.5,
                        tip, 9, TK.TEXT, "middle", MONO)
                + "</g></g>")

    out.append("</svg>")
    return "".join(out)


# --- 3. bar chart ---------------------------------------------------------
def bar_chart(bars: Sequence[dict], width: int = 700, height: int = 220,
              horizontal: bool = False, value_fmt: Callable[[float], str] = None,
              zero: bool = True) -> str:
    """Bars with an explicit null state. Each bar: {label, value, colour?}.

    A null value draws a fixed hatched band with a "no free data" title rather
    than a zero-height bar, so absence can never read as nothing-at-stake.
    """
    value_fmt = value_fmt or (lambda v: _fmt(v, 1))
    values = [b.get("value") for b in bars]
    dom = _domain(values, zero=zero)
    n = max(len(bars), 1)
    hid = _uid("hatch")
    out = [_svg_open(width, height, "bar chart"), f"<defs>{_hatch(hid)}</defs>"]

    if horizontal:
        pad_l, pad_r, row_h = 130, 64, (height - 8) / n
        x = _scale(dom, (pad_l, width - pad_r))
        zero_x = x(max(dom[0], 0.0))
        bar_h = min(row_h * 0.62, 18)
        null_w = 34
        for i, b in enumerate(bars):
            cy = 4 + row_h * i + row_h / 2
            out.append(_text(pad_l - 8, cy + 3.5, b["label"], 10.5, TK.TEXT, "end"))
            v = b.get("value")
            if v is None:
                out.append(f'<rect x="{zero_x:.1f}" y="{cy - bar_h / 2:.1f}"'
                           f' width="{null_w}" height="{bar_h:.1f}"'
                           f' fill="url(#{hid})" stroke="{TK.RULE_STRONG}"'
                           f' stroke-width="0.5" class="nullband">'
                           f"<title>no free data</title></rect>")
                out.append(_text(zero_x + null_w + 6, cy + 3.5, "no free data", 9,
                                 TK.MUTED, family=UI))
                continue
            colour = b.get("colour") or (TK.DOWN if v < 0 else TK.UP)
            x0, x1 = sorted((zero_x, x(v)))
            out.append(f'<rect x="{x0:.1f}" y="{cy - bar_h / 2:.1f}"'
                       f' width="{max(x1 - x0, 1.2):.1f}" height="{bar_h:.1f}"'
                       f' fill="{colour}"/>')
            out.append(_text(x1 + 6 if v >= 0 else x0 - 6, cy + 3.5, value_fmt(v),
                             9.5, TK.TEXT, "start" if v >= 0 else "end", MONO))
    else:
        pad_l, top, bottom = 44, 10, 22
        floor = height - bottom
        y = _scale(dom, (floor, top))
        zero_y = y(max(dom[0], 0.0))
        slot = (width - pad_l - 8) / n
        bar_w = min(slot * 0.6, 34)
        null_h = 22
        out.append(f'<line x1="{pad_l - 4}" y1="{zero_y:.1f}" x2="{width - 6}"'
                   f' y2="{zero_y:.1f}" stroke="{TK.RULE_STRONG}"/>')
        out.append(_text(pad_l - 8, zero_y + 3, "0", 9, TK.MUTED, "end", MONO))
        top_val = dom[1] / (1 + 0.08)
        out.append(_text(pad_l - 8, y(top_val) + 3, value_fmt(top_val), 9, TK.MUTED,
                         "end", MONO))
        for i, b in enumerate(bars):
            cx = pad_l + slot * i + slot / 2
            v = b.get("value")
            if v is None:
                out.append(f'<rect x="{cx - bar_w / 2:.1f}"'
                           f' y="{zero_y - null_h:.1f}" width="{bar_w:.1f}"'
                           f' height="{null_h}" fill="url(#{hid})"'
                           f' stroke="{TK.RULE_STRONG}" stroke-width="0.5"'
                           f' class="nullband"><title>no free data</title></rect>')
            else:
                colour = b.get("colour") or (TK.DOWN if v < 0 else TK.UP)
                y0, y1 = sorted((y(v), zero_y))
                out.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y0:.1f}"'
                           f' width="{bar_w:.1f}" height="{max(y1 - y0, 1.2):.1f}"'
                           f' fill="{colour}"/>')
                if b.get("show_value"):
                    out.append(_text(cx, y0 - 4, value_fmt(v), 9, TK.TEXT, "middle",
                                     MONO))
            out.append(_text(cx, height - 8, b["label"], 9, TK.MUTED, "middle", MONO))
    out.append("</svg>")
    return "".join(out)


# --- 4. stacked bar -------------------------------------------------------
def stacked_bar(rows: Sequence[dict], width: int = 760, height: int = 260,
                value_fmt: Callable[[float], str] = None,
                legend: Sequence[tuple] = ()) -> str:
    """Horizontal stacked bars. Each row: {label, segments: [{name, value, colour}]}.

    Segment values must be real; a row with nothing to show renders its label and
    an em-dash rather than an empty bar pretending to be zero.
    """
    value_fmt = value_fmt or (lambda v: _fmt(v, 1))
    n = max(len(rows), 1)
    legend_h = 18 if legend else 0
    pad_l, pad_r = 120, 70
    row_h = (height - 8 - legend_h) / n
    total_max = max((sum(s["value"] for s in r["segments"]) for r in rows
                     if r["segments"]), default=1.0)
    x = _scale((0, total_max), (pad_l, width - pad_r))
    bar_h = min(row_h * 0.64, 20)

    out = [_svg_open(width, height, "stacked bars")]
    ly = 12
    lx = pad_l
    for name, colour in legend:
        out.append(f'<rect x="{lx}" y="{ly - 8}" width="8" height="8"'
                   f' fill="{colour}"/>')
        out.append(_text(lx + 12, ly, name, 9.5, TK.MUTED, family=UI))
        lx += 12 + 7 * len(str(name)) + 18
    for i, r in enumerate(rows):
        cy = legend_h + 4 + row_h * i + row_h / 2
        out.append(_text(pad_l - 8, cy + 3.5, r["label"], 10.5, TK.TEXT, "end"))
        segs = r.get("segments") or []
        if not segs:
            out.append(_text(pad_l + 4, cy + 3.5, "—", 10, TK.MUTED, family=MONO))
            continue
        run = 0.0
        for s in segs:
            x0, x1 = x(run), x(run + s["value"])
            out.append(f'<rect x="{x0:.1f}" y="{cy - bar_h / 2:.1f}"'
                       f' width="{max(x1 - x0, 0.8):.1f}" height="{bar_h:.1f}"'
                       f' fill="{s["colour"]}"><title>{_esc(s["name"])} '
                       f"{_esc(value_fmt(s['value']))}</title></rect>")
            run += s["value"]
        out.append(_text(x(run) + 6, cy + 3.5, value_fmt(run), 9.5, TK.TEXT,
                         family=MONO))
    out.append("</svg>")
    return "".join(out)


# --- 5. heatmap grid ------------------------------------------------------
def _blend(low: str, high: str, t: float) -> str:
    """Linear sRGB blend; adequate for a two-stop density ramp."""
    lo = tuple(int(low.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    hi = tuple(int(high.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{round(a + (b - a) * t):02X}" for a, b in zip(lo, hi))


def heatmap_grid(row_labels: Sequence[str], col_labels: Sequence[str],
                 cells: dict, width: int = 980, height: int = 460,
                 flag_note: str = "uncurated") -> str:
    """Universe grid. cells[(row, col)] = {count, weight 0..1, flagged bool}.

    A missing cell stays ground with no figure: absence of data is not a zero.
    Weight drives the fill from panel toward the data colour; the count is printed
    in the cell, so colour is never the only signal. A flagged cell carries an
    amber corner tick.
    """
    pad_l, pad_t = 64, 30
    cw = (width - pad_l - 6) / max(len(col_labels), 1)
    ch = (height - pad_t - 6) / max(len(row_labels), 1)
    out = [_svg_open(width, height, "catalyst grid")]
    for j, col in enumerate(col_labels):
        out.append(_text(pad_l + cw * j + cw / 2, pad_t - 10, col, 9, TK.MUTED,
                         "middle", MONO))
    for i, row in enumerate(row_labels):
        cy = pad_t + ch * i
        out.append(_text(pad_l - 8, cy + ch / 2 + 3.5, row, 10, TK.TEXT, "end", MONO,
                         "600"))
        for j, col in enumerate(col_labels):
            cx = pad_l + cw * j
            cell = cells.get((row, col))
            if not cell or not cell.get("count"):
                out.append(f'<rect x="{cx + 1:.1f}" y="{cy + 1:.1f}"'
                           f' width="{cw - 2:.1f}" height="{ch - 2:.1f}"'
                           f' fill="{TK.GROUND}" stroke="{TK.RULE}"'
                           f' stroke-width="0.5"/>')
                continue
            weight = max(0.0, min(1.0, cell.get("weight", 0.5)))
            fill = _blend(TK.PANEL, TK.UP, 0.15 + 0.85 * weight)
            out.append(f'<rect x="{cx + 1:.1f}" y="{cy + 1:.1f}"'
                       f' width="{cw - 2:.1f}" height="{ch - 2:.1f}" fill="{fill}"'
                       f'><title>{_esc(row)} {_esc(col)}: {cell["count"]}</title>'
                       "</rect>")
            ink = TK.GROUND if weight > 0.55 else TK.TEXT
            out.append(_text(cx + cw / 2, cy + ch / 2 + 3.5, cell["count"], 9.5,
                             ink, "middle", MONO, "600"))
            if cell.get("flagged"):
                out.append(f'<path d="M{cx + cw - 9:.1f},{cy + 1:.1f}'
                           f' h8 v8 z" fill="{TK.FLAG}">'
                           f"<title>{_esc(flag_note)}</title></path>")
    out.append("</svg>")
    return "".join(out)


# --- 6. dumbbell ----------------------------------------------------------
def dumbbell(rows: Sequence[dict], width: int = 900, height: int = 400,
             domain: tuple[float, float] = None,
             tick_fmt: Callable[[float], str] = None) -> str:
    """Original-to-current pairs. Each row: {label, start, end, note?}.

    Start is an open circle, end a filled one, the connector carries direction:
    later (a slip) in the down colour, earlier in the up colour. The signed move
    is printed at the right, so the geometry is never the only signal.
    """
    tick_fmt = tick_fmt or (lambda v: _fmt(v, 0))
    pad_l, pad_r, pad_t = 190, 96, 24
    usable = [r for r in rows if r.get("start") is not None
              and r.get("end") is not None]
    if not usable:
        return ""
    values = [r["start"] for r in usable] + [r["end"] for r in usable]
    dom = domain or _domain(values, pad=0.05)
    x = _scale(dom, (pad_l, width - pad_r))
    n = len(usable)
    row_h = (height - pad_t - 8) / n

    out = [_svg_open(width, height, "date slippage")]
    for frac in (0.0, 0.5, 1.0):
        gx = dom[0] + (dom[1] - dom[0]) * frac
        out.append(f'<line x1="{x(gx):.1f}" y1="{pad_t - 6}" x2="{x(gx):.1f}"'
                   f' y2="{height - 6}" stroke="{TK.RULE}"/>')
        out.append(_text(x(gx), pad_t - 12, tick_fmt(gx), 9, TK.MUTED, "middle",
                         MONO))
    for i, r in enumerate(usable):
        cy = pad_t + row_h * i + row_h / 2
        moved = r["end"] - r["start"]
        colour = TK.DOWN if moved > 0 else TK.UP if moved < 0 else TK.MUTED
        out.append(_text(pad_l - 10, cy + 3.5, r["label"], 10, TK.TEXT, "end"))
        x0, x1 = x(r["start"]), x(r["end"])
        out.append(f'<line x1="{x0:.1f}" y1="{cy:.1f}" x2="{x1:.1f}" y2="{cy:.1f}"'
                   f' stroke="{colour}" stroke-width="2"/>')
        out.append(f'<circle cx="{x0:.1f}" cy="{cy:.1f}" r="3.4" fill="{TK.GROUND}"'
                   f' stroke="{TK.MUTED}" stroke-width="1.4"/>')
        out.append(f'<circle cx="{x1:.1f}" cy="{cy:.1f}" r="3.6" fill="{colour}"/>')
        sign = "+" if moved > 0 else MINUS if moved < 0 else ""
        out.append(_text(width - pad_r + 12, cy + 3.5,
                         f"{sign}{abs(moved):.0f}d", 9.5, colour, "start", MONO,
                         "600"))
    out.append("</svg>")
    return "".join(out)


# --- 7. waterfall ---------------------------------------------------------
def waterfall(steps: Sequence[dict], width: int = 760, height: int = 280,
              value_fmt: Callable[[float], str] = None) -> str:
    """Running decomposition. Each step: {label, value, kind: start|step|end|null}.

    A null step hatches at the running level with no height, saying "something
    belongs here whose size is unknown" without inventing the size.
    """
    value_fmt = value_fmt or (lambda v: _fmt(v, 1))
    pad_l, top, bottom = 52, 16, 34
    floor = height - bottom
    running = 0.0
    peaks = [0.0]
    for s in steps:
        if s.get("kind") == "start":
            running = s.get("value") or 0.0
        elif s.get("kind") == "step" and s.get("value") is not None:
            running += s["value"]
        peaks.append(running)
    dom = _domain(peaks, zero=True)
    y = _scale(dom, (floor, top))
    n = max(len(steps), 1)
    slot = (width - pad_l - 10) / n
    bar_w = min(slot * 0.62, 46)
    hid = _uid("hatch")

    out = [_svg_open(width, height, "waterfall"), f"<defs>{_hatch(hid)}</defs>"]
    zero_y = y(0)
    out.append(f'<line x1="{pad_l - 4}" y1="{zero_y:.1f}" x2="{width - 8}"'
               f' y2="{zero_y:.1f}" stroke="{TK.RULE_STRONG}"/>')
    running = 0.0
    prev_edge = None
    for i, s in enumerate(steps):
        cx = pad_l + slot * i + slot / 2
        kind = s.get("kind", "step")
        v = s.get("value")
        if kind == "start" or kind == "end":
            level = v if kind == "start" else running
            if kind == "start":
                running = v or 0.0
            y0, y1 = sorted((y(level or 0.0), zero_y))
            out.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y0:.1f}"'
                       f' width="{bar_w:.1f}" height="{max(y1 - y0, 1):.1f}"'
                       f' fill="{TK.PANEL}" stroke="{TK.RULE_STRONG}"/>')
            out.append(_text(cx, y0 - 5, value_fmt(level or 0.0), 9, TK.TEXT,
                             "middle", MONO, "600"))
            edge = y(level or 0.0)
        elif v is None:
            out.append(f'<rect x="{cx - bar_w / 2:.1f}"'
                       f' y="{y(running) - 9:.1f}" width="{bar_w:.1f}" height="18"'
                       f' fill="url(#{hid})" stroke="{TK.RULE_STRONG}"'
                       f' stroke-width="0.5" class="nullband">'
                       f"<title>no free data</title></rect>")
            edge = y(running)
        else:
            start_level = running
            running += v
            y0, y1 = sorted((y(start_level), y(running)))
            colour = TK.DOWN if v < 0 else TK.UP
            out.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y0:.1f}"'
                       f' width="{bar_w:.1f}" height="{max(y1 - y0, 1.2):.1f}"'
                       f' fill="{colour}"/>')
            out.append(_text(cx, y0 - 5, value_fmt(v), 9, colour, "middle", MONO))
            edge = y(running)
        if prev_edge is not None:
            out.append(f'<line x1="{cx - slot / 2 + bar_w * 0.19:.1f}"'
                       f' y1="{prev_edge:.1f}" x2="{cx - bar_w / 2:.1f}"'
                       f' y2="{prev_edge:.1f}" stroke="{TK.MUTED}"'
                       f' stroke-width="0.8" stroke-dasharray="2,2"/>')
        prev_edge = edge
        out.append(_text(cx, height - 10, s["label"], 9, TK.MUTED, "middle", UI))
    out.append("</svg>")
    return "".join(out)


# --- 8. small multiples ---------------------------------------------------
def small_multiples(panels: Sequence[dict], width: int = 1080, height: int = 420,
                    cols: int = 6, shared_scale: bool = True) -> str:
    """A grid of mini line panels, one per company, on one shared y-scale.

    Shared scale is the point: a flat line means flat, not autoscaled noise. Each
    panel: {label, values, sub}. Panels with no data say so instead of drawing.
    """
    if not panels:
        return ""
    rows = math.ceil(len(panels) / cols)
    pw, ph = width / cols, height / rows
    all_values = [v for p in panels for v in (p.get("values") or [])
                  if v is not None]
    dom = _domain(all_values) if (shared_scale and all_values) else None

    out = [_svg_open(width, height, "small multiples")]
    for idx, p in enumerate(panels):
        gx, gy = (idx % cols) * pw, (idx // cols) * ph
        out.append(f'<rect x="{gx + 1:.1f}" y="{gy + 1:.1f}" width="{pw - 2:.1f}"'
                   f' height="{ph - 2:.1f}" fill="{TK.PANEL}"/>')
        out.append(_text(gx + 8, gy + 16, p["label"], 10.5, TK.TEXT, family=MONO,
                         weight="700"))
        if p.get("sub") is not None:
            sub_colour = (TK.DOWN if str(p["sub"]).startswith(MINUS)
                          else TK.UP if str(p["sub"]).strip() else TK.MUTED)
            out.append(_text(gx + pw - 8, gy + 16, p["sub"], 9.5, sub_colour, "end",
                             MONO, "600"))
        values = p.get("values") or []
        real = [v for v in values if v is not None]
        if len(real) < 2:
            out.append(_text(gx + 8, gy + ph / 2 + 6, "no free data", 9, TK.MUTED))
            continue
        local_dom = dom or _domain(values)
        y = _scale(local_dom, (gy + ph - 8, gy + 24))
        x = _scale((0, max(len(values) - 1, 1)), (gx + 8, gx + pw - 8))
        first = real[0]
        last = real[-1]
        stroke = TK.DOWN if last < first else TK.UP
        _polyline_runs(out, values, x, y, stroke, 1.2)
    out.append("</svg>")
    return "".join(out)


# --- 9. timeline spine ----------------------------------------------------
def timeline_spine(items: Sequence[dict], today, width: int = 200,
                   height: int = 720, cliff_years: dict = None,
                   selected_key: str = None, link_base: str = None) -> str:
    """The signature element: one continuous vertical time axis at three
    compressed scales, stacked without a break.

    0 to 90 days at day resolution, 3 to 24 months at month resolution, then the
    cliff beyond 24 months at year resolution as count bars. Ticks sit at real
    item dates. Items: {key, date (ISO), label, kind, colour, flagged}. The
    selected item, when given, carries a hairline from the panel edge to its
    tick and renders emphasised.

    When ``link_base`` is set each item becomes an SVG anchor to
    ``link_base + key``, so a click pins that item and draws its hairline with no
    script: the navigation carries the selection back through the URL.
    """
    import datetime as _dt
    from itertools import groupby as _groupby
    from urllib.parse import quote as _quote

    spine_x = 46
    seg_top = 26
    near_end = today + _dt.timedelta(days=90)
    mid_end = _dt.date(today.year + 2, today.month, 1)
    cliff_years = cliff_years or {}

    def _parse(value):
        """ISO date, or a month-only date placed at its first day for grouping.
        The label keeps month precision; only the position needs a day."""
        s = str(value or "").strip()[:10]
        for candidate in (s, s[:7] + "-01"):
            try:
                return _dt.date.fromisoformat(candidate)
            except ValueError:
                continue
        return None

    # Forward-dated items inside 24 months, grouped by calendar month. Each month is its
    # own block: a green dash marks it on the spine, its items stack below at a fixed row
    # height, and a gap separates it from the next, so months in the busy mid-range never
    # crowd into one another.
    dated = []
    for item in items:
        when = _parse(item.get("date"))
        if when is None or when < today or when > mid_end:
            continue
        dated.append((when, item))
    dated.sort(key=lambda p: (p[0], str(p[1].get("label") or "")))

    top_y = seg_top + 14
    body, y = [], top_y + 6
    row_h, month_gap = 12.5, 9.0
    for (year, month), group in _groupby(dated, key=lambda p: (p[0].year, p[0].month)):
        body.append(f'<line x1="{spine_x - 6}" y1="{y:.1f}" x2="{spine_x + 6}"'
                    f' y2="{y:.1f}" stroke="{TK.UP}" stroke-width="2"/>')
        body.append(_text(spine_x + 13, y + 3,
                          _dt.date(year, month, 1).strftime("%b %Y"), 8.5, TK.UP,
                          family=UI, weight="700"))
        y += 15
        for when, item in group:
            colour = item.get("colour") or TK.UP
            selected = selected_key is not None and item.get("key") == selected_key
            # A trial tick is a small mark; the green month dash above it is the wider
            # marker, so the two read as group and member rather than competing.
            tick_w = 4 if selected else 3
            # A hover previews the item through the rect's title; a click opens the study
            # page when the item carries a URL, and otherwise pins it (exclusivity) when a
            # link base is given. The full-width transparent rect is the hover and click
            # target across the whole row.
            url = item.get("url")
            href = (url if url
                    else (link_base + _quote(str(item["key"]))
                          if link_base and item.get("key") else None))
            tooltip = item.get("full") or item.get("label") or ""
            if href:
                target = ' target="_blank" rel="noopener"' if url else ""
                body.append(f'<a href="{_esc(href)}"{target}>')
            body.append(f'<rect x="0" y="{y - 6:.1f}" width="{width}" height="13"'
                        f' fill="transparent"><title>{_esc(tooltip)}</title></rect>')
            body.append(f'<line x1="{spine_x - tick_w}" y1="{y:.1f}"'
                        f' x2="{spine_x + tick_w}" y2="{y:.1f}" stroke="{colour}"'
                        f' stroke-width="{2.4 if selected else 1.6}"/>')
            if selected:
                body.append(f'<line x1="0" y1="{y:.1f}" x2="{spine_x - tick_w:.1f}"'
                            f' y2="{y:.1f}" stroke="{colour}" stroke-width="1"'
                            f' stroke-dasharray="3,2"/>')
            if item.get("flagged"):
                body.append(f'<circle cx="{spine_x - 13}" cy="{y:.1f}" r="2.4"'
                            f' fill="{TK.FLAG}"><title>uncurated, review</title>'
                            "</circle>")
            # A month-only source date never grows a day it does not have.
            raw = str(item.get("date") or "").strip()
            if len(raw) == 7:
                date_s = when.strftime("%Y-%m")
            elif when <= near_end:
                date_s = when.strftime("%m-%d")
            else:
                date_s = when.strftime("%Y-%m")
            weight = "700" if selected else "600"
            body.append(_text(spine_x + 16, y + 3, date_s, 8.5,
                              TK.TEXT if selected else TK.MUTED, family=MONO,
                              weight=weight))
            body.append(_text(spine_x + 58, y + 3, str(item.get("label") or "")[:20],
                              8.5, TK.TEXT if selected else TK.MUTED, family=UI))
            if href:
                body.append("</a>")
            y += row_h
        y += month_gap

    if not dated:
        body.append(_text(spine_x + 13, top_y + 20, "nothing inside 24 months", 8.5,
                          TK.MUTED, family=UI))
        y = top_y + 34

    cliff_y0 = y + 6
    # the SVG grows to fit the flowed months and the cliff, since a busy pipeline runs
    # longer than a fixed height.
    svg_height = max(height, int(cliff_y0 + (24 if cliff_years else 34)
                                 + 16 * min(len(cliff_years), 8)))

    out = [_svg_open(width, svg_height, "time spine")]
    out.append(_text(8, 14, "HORIZON", 10, TK.TEXT, family=UI, weight="700",
                     extra=' letter-spacing="0.09em"'))
    # the spine: one line from today down to the cliff
    out.append(f'<line x1="{spine_x}" y1="{top_y - 8}" x2="{spine_x}"'
               f' y2="{cliff_y0 - 6:.1f}" stroke="{TK.RULE_STRONG}"'
               f' stroke-width="1.5"/>')
    out.append(f'<line x1="{spine_x - 5}" y1="{top_y - 8}" x2="{spine_x + 5}"'
               f' y2="{top_y - 8}" stroke="{TK.TEXT}" stroke-width="1.5"/>')
    out.append(_text(spine_x + 9, top_y - 5, f"today {today.isoformat()}", 8.5,
                     TK.MUTED, family=MONO))
    out += body

    # the cliff: per-year counts beyond 24 months
    out.append(_text(8, cliff_y0 + 10, "CLIFF 24M+", 8.5, TK.MUTED, family=UI,
                     weight="700", extra=' letter-spacing="0.08em"'))
    if cliff_years:
        peak = max(cliff_years.values())
        bar_x = spine_x + 16
        bar_max = width - bar_x - 26
        for i, year in enumerate(sorted(cliff_years)[:8]):
            by = cliff_y0 + 20 + i * 16
            w = max(2, cliff_years[year] / peak * bar_max)
            out.append(_text(spine_x + 12, by + 7, year, 8.5, TK.MUTED, "end", MONO))
            out.append(f'<rect x="{bar_x}" y="{by}" width="{w:.1f}" height="8"'
                       f' fill="{TK.RULE_STRONG}"/>')
            out.append(_text(bar_x + w + 5, by + 7, cliff_years[year], 8.5,
                             TK.MUTED, family=MONO))
    else:
        out.append(_text(8, cliff_y0 + 26, "nothing on file", 8.5, TK.MUTED))
    out.append("</svg>")
    return "".join(out)


# --- 11. scatter ----------------------------------------------------------
def scatter(points: Sequence[dict], width: int = 760, height: int = 280,
            x_label: str = "", y_label: str = "",
            fmt: Callable[[float], str] = None) -> str:
    """Labelled scatter. Each point: {label, x, y, selected?}.

    Every point carries its own label, so nothing depends on hover; the selected
    point takes the down colour and a heavier dot, the rest stay muted. A point
    missing either coordinate is left out; it has no honest place on the plane.
    """
    fmt = fmt or (lambda v: _fmt(v, 1))
    usable = [p for p in points if p.get("x") is not None and p.get("y") is not None]
    if not usable:
        return ""
    pad_l, pad_r, top, bottom = 56, 24, 14, 40
    dom_x = _domain([p["x"] for p in usable], pad=0.1)
    dom_y = _domain([p["y"] for p in usable], pad=0.12)
    x = _scale(dom_x, (pad_l, width - pad_r))
    y = _scale(dom_y, (height - bottom, top))

    out = [_svg_open(width, height, "scatter")]
    for frac in (0.0, 0.5, 1.0):
        gy = top + (height - bottom - top) * frac
        out.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{width - pad_r}"'
                   f' y2="{gy:.1f}" stroke="{TK.RULE}"/>')
        vy = dom_y[1] + (dom_y[0] - dom_y[1]) * frac
        out.append(_text(pad_l - 6, gy + 3, fmt(vy), 9, TK.MUTED, "end", MONO))
    for frac in (0.0, 0.5, 1.0):
        vx = dom_x[0] + (dom_x[1] - dom_x[0]) * frac
        out.append(_text(x(vx), height - 24, fmt(vx), 9, TK.MUTED, "middle", MONO))
    if x_label:
        out.append(_text((pad_l + width - pad_r) / 2, height - 8, x_label, 9.5,
                         TK.MUTED, "middle", UI))
    if y_label:
        out.append(_text(12, top + 2, y_label, 9.5, TK.MUTED, "start", UI))
    for p in usable:
        selected = bool(p.get("selected"))
        colour = TK.DOWN if selected else TK.MUTED
        out.append(f'<circle cx="{x(p["x"]):.1f}" cy="{y(p["y"]):.1f}"'
                   f' r="{4.2 if selected else 3}" fill="{colour}"/>')
        out.append(_text(x(p["x"]) + 6, y(p["y"]) + 3, p["label"], 8.5,
                         TK.TEXT if selected else TK.MUTED, family=MONO,
                         weight="700" if selected else ""))
    out.append("</svg>")
    return "".join(out)


# --- 10. donut ------------------------------------------------------------
def donut(slices: Sequence[dict], width: int = 760, height: int = 300,
          centre_label: str = "", centre_sub: str = "",
          value_fmt: Callable[[float], str] = None) -> str:
    """Share-of-total ring with labels outside on leader lines.

    Each slice: {label, value, colour, muted?}. Labels alternate sides by
    mid-angle, each with a leader from arc to text, so nothing is printed inside
    a thin segment.
    """
    value_fmt = value_fmt or (lambda v: _fmt(v, 1))
    total = sum(s["value"] for s in slices if s.get("value"))
    if total <= 0:
        return ""
    cx, cy = width / 2, height / 2
    r_out, r_in = min(height / 2 - 34, 108), min(height / 2 - 34, 108) * 0.62

    def _pt(radius, angle):
        return (cx + radius * math.cos(angle), cy + radius * math.sin(angle))

    out = [_svg_open(width, height, "revenue mix")]
    angle = -math.pi / 2
    for s in slices:
        frac = (s.get("value") or 0) / total
        if frac <= 0:
            continue
        sweep = frac * math.tau
        a0, a1 = angle, angle + sweep
        large = 1 if sweep > math.pi else 0
        x0o, y0o = _pt(r_out, a0)
        x1o, y1o = _pt(r_out, a1)
        x0i, y0i = _pt(r_in, a1)
        x1i, y1i = _pt(r_in, a0)
        out.append(
            f'<path d="M{x0o:.1f},{y0o:.1f} A{r_out:.1f},{r_out:.1f} 0 {large} 1 '
            f"{x1o:.1f},{y1o:.1f} L{x0i:.1f},{y0i:.1f} "
            f"A{r_in:.1f},{r_in:.1f} 0 {large} 0 {x1i:.1f},{y1i:.1f} Z\" "
            f'fill="{s["colour"]}" stroke="{TK.GROUND}" stroke-width="1">'
            f"<title>{_esc(s['label'])} {_esc(value_fmt(s['value']))}</title></path>")
        # leader line and outside label at the mid angle
        mid = (a0 + a1) / 2
        ex, ey = _pt(r_out + 6, mid)
        kx, ky = _pt(r_out + 16, mid)
        right = math.cos(mid) >= 0
        tx = kx + (10 if right else -10)
        out.append(f'<polyline points="{ex:.1f},{ey:.1f} {kx:.1f},{ky:.1f}'
                   f' {tx:.1f},{ky:.1f}" fill="none" stroke="{TK.MUTED}"'
                   f' stroke-width="0.8"/>')
        colour = TK.MUTED if s.get("muted") else TK.TEXT
        out.append(_text(tx + (4 if right else -4), ky + 3, s["label"], 9.5, colour,
                         "start" if right else "end", UI))
        out.append(_text(tx + (4 if right else -4), ky + 13,
                         f"{value_fmt(s['value'])}  {frac * 100:.1f}%", 8.5,
                         TK.MUTED, "start" if right else "end", MONO))
        angle = a1
    if centre_label:
        out.append(_text(cx, cy - 1, centre_label, 15, TK.TEXT, "middle", MONO,
                         "700"))
    if centre_sub:
        out.append(_text(cx, cy + 13, centre_sub, 9, TK.MUTED, "middle", UI))
    out.append("</svg>")
    return "".join(out)
