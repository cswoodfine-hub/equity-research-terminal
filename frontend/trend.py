"""Growth against margin: one panel answering whether the growth reaches the bottom.

Two numbers standing alone say nothing. Revenue up 55.5% and a 37.4% net margin only
mean something against the quarters behind them, which is where you can see that both
are climbing together rather than one being bought with the other.

Each series has its own scale. Revenue growth is often a single-digit rate while net
margin runs to a third of sales, so one shared axis buried the bars for a low-growth
company. The two now scale independently and share only the zero baseline, so each fills
the panel and its trajectory is legible. The cost is that a bar's height and the line's
height are no longer comparable, so both scales are labelled at their extremes.

Hue is not free here: the palette reserves orange and purple for modality, so the two
series are told apart by form instead. Growth is a change and is drawn as bars from
zero; margin is a level and is drawn as a line. Direct labels at the right replace a
legend, which would otherwise cost a key lookup on every read.

Pure: builds SVG from a list of points and knows nothing about the API.
"""

from __future__ import annotations

import html

from theme import MINUS, P

# Matches the statement table's cap (52rem), so the panel and the grid below it share
# their left and right edges rather than being two different widths on the same tab.
W = 832
H = 176
PAD_L = 30          # room for the axis percentages
PAD_R = 96          # room for the direct labels at the end of each series
TOP = 16
BOTTOM = 26         # room for the period labels
BAR_FILL = 0.44     # share of a slot the bar occupies
MAX_BAR_W = 46      # a short series has wide slots; cap so four bars stay bars, not blocks
LABEL_GAP = 11      # least vertical space between the two direct labels


def _pct(value, decimals=1) -> str:
    """A percentage carrying the app's true minus rather than a hyphen, so a negative
    figure holds its digit width against the tabular numerals everywhere else."""
    return f"{MINUS if value < 0 else ''}{abs(value) * 100:.{decimals}f}%"


def _zero_domain(values):
    """Padded [lo, hi] spanning zero for one series. The active end gets breathing room;
    the zero end stays at zero, so a bar or the line grows from a true baseline."""
    lo, hi = min(list(values) + [0.0]), max(list(values) + [0.0])
    span = (hi - lo) or 0.01
    pad = span * 0.12
    return (lo - pad if lo < 0 else 0.0, hi + pad if hi > 0 else 0.0)


def render(points, basis: str = "quarterly") -> str:
    """SVG for the growth and margin panel, or "" when there is too little to plot.

    ``points`` are oldest first, each with label, revenue_growth, and net_margin. A
    period missing either figure is drawn as a gap rather than as a zero, and the margin
    line breaks across it instead of running straight through.

    Growth and margin scale independently and share only the zero baseline, so a bar and
    the line each fill the panel on their own range. Their heights are not comparable, so
    each scale is labelled at its extremes.
    """
    points = [p for p in points
              if p.get("revenue_growth") is not None or p.get("net_margin") is not None]
    if len(points) < 2:
        return ""

    growths = [p["revenue_growth"] for p in points if p.get("revenue_growth") is not None]
    margins = [p["net_margin"] for p in points if p.get("net_margin") is not None]
    g_lo, g_hi = _zero_domain(growths)
    m_lo, m_hi = _zero_domain(margins)

    floor, ceiling = H - BOTTOM, TOP
    height = floor - ceiling

    def _neg_frac(lo, hi):
        span = hi - lo
        return (-lo) / span if span > 0 and lo < 0 else 0.0

    # One zero baseline, shared, so a negative bar and a negative margin drop below the
    # same line. The below-zero band is sized for whichever series reaches furthest down.
    nf = max(_neg_frac(g_lo, g_hi), _neg_frac(m_lo, m_hi))
    above_h, below_h = height * (1 - nf), height * nf
    zero_y = ceiling + above_h

    def _scale(lo, hi):
        def y(value):
            if value >= 0:
                return zero_y - (value / hi) * above_h if hi > 0 else zero_y
            return zero_y + (value / lo) * below_h if lo < 0 else zero_y
        return y

    yg, ym = _scale(g_lo, g_hi), _scale(m_lo, m_hi)

    slot = (W - PAD_L - PAD_R) / len(points)
    bar_w = min(slot * BAR_FILL, MAX_BAR_W)

    def x(index):
        return PAD_L + slot * (index + 0.5)

    out = [
        f'<svg viewBox="0 0 {W} {H}" width="100%"'
        f' style="max-width:{W}px;font-family:Public Sans,sans-serif" role="img"'
        f' aria-label="Revenue growth and net margin over the last'
        f' {len(points)} {"quarters" if basis == "quarterly" else "years"},'
        f' each on its own scale">'
    ]

    # Zero baseline, shared by both scales.
    out.append(f'<line x1="{PAD_L - 6}" y1="{zero_y:.1f}" x2="{W - PAD_R + 6}"'
               f' y2="{zero_y:.1f}" stroke="{P.rule_strong}" stroke-width="1"/>')
    out.append(f'<text x="{PAD_L - 9}" y="{zero_y + 3:.1f}" font-size="9"'
               f' text-anchor="end" fill="{P.stale}">0</text>')

    # Two scales, so two axes: growth on the left in its colour, margin on the right in
    # its. The extreme of each is labelled where the series reaches it, which is the only
    # honest way to show that the two heights are not the same measure.
    def axis_tick(value, y_at, colour, side):
        x_at, anchor = (PAD_L - 9, "end") if side == "left" else (W - PAD_R - 4, "end")
        return (f'<text x="{x_at}" y="{y_at + 3:.1f}" font-size="9" '
                f'text-anchor="{anchor}" fill="{colour}" font-weight="600">'
                f'{_pct(value, 0)}</text>')

    out.append(axis_tick(max(growths), yg(max(growths)), P.data, "left"))
    out.append(axis_tick(max(margins), ym(max(margins)), P.ink, "right"))
    if min(growths) < 0:
        out.append(axis_tick(min(growths), yg(min(growths)), P.data, "left"))
    if min(margins) < 0:
        out.append(axis_tick(min(margins), ym(min(margins)), P.ink, "right"))

    # Growth: a change, so bars from zero. The most recent carries full weight; the
    # history behind it is context and is stepped back.
    last = len(points) - 1
    for index, point in enumerate(points):
        growth = point.get("revenue_growth")
        if growth is None:
            continue
        top = min(yg(growth), zero_y)
        bar_h = abs(yg(growth) - zero_y)
        colour = P.oxblood if growth < 0 else P.data
        out.append(
            f'<rect x="{x(index) - bar_w / 2:.1f}" y="{top:.1f}"'
            f' width="{bar_w:.1f}" height="{max(bar_h, 0.8):.1f}" fill="{colour}"'
            f' opacity="{1.0 if index == last else 0.5}"/>')

    # Margin: a level, so a line. It breaks where a period has no margin rather than
    # running through the gap, which would draw a value that was never reported.
    run: list[str] = []
    for index, point in enumerate(points):
        margin = point.get("net_margin")
        if margin is None:
            if len(run) > 1:
                out.append(f'<polyline points="{" ".join(run)}" fill="none"'
                           f' stroke="{P.ink}" stroke-width="1.5"/>')
            run = []
            continue
        run.append(f"{x(index):.1f},{ym(margin):.1f}")
    if len(run) > 1:
        out.append(f'<polyline points="{" ".join(run)}" fill="none"'
                   f' stroke="{P.ink}" stroke-width="1.5"/>')
    for index, point in enumerate(points):
        margin = point.get("net_margin")
        if margin is None:
            continue
        radius = 3.2 if index == last else 2
        out.append(f'<circle cx="{x(index):.1f}" cy="{ym(margin):.1f}" r="{radius}"'
                   f' fill="{P.ground}" stroke="{P.ink}" stroke-width="1.5"/>')

    # Period labels. Every other one on a long quarterly run, so they never collide.
    step = 2 if len(points) > 7 else 1
    for index, point in enumerate(points):
        if (last - index) % step:
            continue
        weight = ' font-weight="600"' if index == last else ""
        out.append(
            f'<text x="{x(index):.1f}" y="{H - 8}" font-size="9" text-anchor="middle"'
            f' fill="{P.ink if index == last else P.stale}"{weight}>'
            f'{html.escape(point["label"])}</text>')

    # Direct labels beat a legend: the name of the series sits at the end of it, so
    # neither has to be looked up. They are pushed apart when the two series finish
    # close together, which is exactly when the panel is most worth reading.
    latest = points[last]
    ends = []
    if latest.get("revenue_growth") is not None:
        ends.append((yg(latest["revenue_growth"]), "growth",
                     _pct(latest["revenue_growth"]), P.data))
    if latest.get("net_margin") is not None:
        ends.append((ym(latest["net_margin"]), "margin",
                     _pct(latest["net_margin"]), P.ink))
    ends.sort()
    if len(ends) == 2 and ends[1][0] - ends[0][0] < LABEL_GAP:
        middle = (ends[0][0] + ends[1][0]) / 2
        ends = [(middle - LABEL_GAP / 2, *ends[0][1:]),
                (middle + LABEL_GAP / 2, *ends[1][1:])]
    for label_y, name, value, colour in ends:
        anchor = W - PAD_R + 14
        out.append(
            f'<text x="{anchor}" y="{label_y + 3:.1f}" font-size="10">'
            f'<tspan fill="{colour}" font-weight="700">{value}</tspan>'
            f'<tspan fill="{P.stale}" dx="4">{html.escape(name)}</tspan></text>')

    out.append("</svg>")
    return "".join(out)


def caption(points, basis: str = "quarterly") -> str:
    """One sentence stating where each series started and finished. Facts, no reading."""
    usable = [p for p in points if p.get("revenue_growth") is not None
              and p.get("net_margin") is not None]
    if len(usable) < 2:
        return ""
    first, last = usable[0], usable[-1]
    unit = "quarters" if basis == "quarterly" else "fiscal years"
    return (f"Over {len(usable)} {unit} to {last['label']}, growth ran "
            f"{_pct(first['revenue_growth'])} to {_pct(last['revenue_growth'])} and "
            f"net margin {_pct(first['net_margin'])} to {_pct(last['net_margin'])}. "
            "Each sits on its own scale, so read the height of each against its own axis.")
