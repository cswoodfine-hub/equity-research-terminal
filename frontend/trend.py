"""Growth against margin: a trajectory in the plane of the two numbers over time.

Two numbers standing alone say nothing. Revenue up 55.5% and a 37.4% net margin only mean
something against the quarters behind them. Plotting one over time and the other over time
on the same panel forced two scales that could not be compared; plotting growth against
margin directly does not.

Each period is a point at (revenue growth, net margin), and the periods are joined oldest
to newest, so the panel shows where the company is heading rather than only where it is.
Up and to the right is growth and margin improving together, the quadrant a reader wants;
down and to the left is both giving way. The latest period carries full weight and its
figures; the first is labelled so the direction of travel is unambiguous. A dashed line
marks zero growth, the crossing from shrinking to growing.

Pure: builds SVG from a list of points and knows nothing about the API.
"""

from __future__ import annotations

import html
import math

from theme import MINUS, P

W = 832              # matches the statement table's cap, so both share their edges
H = 244
PAD_L = 48           # room for the margin axis figures
PAD_R = 108          # room for the latest point's label
TOP = 22
BOTTOM = 36          # room for the growth axis figure and title


def _pct(value, decimals=1) -> str:
    """A percentage carrying the app's true minus rather than a hyphen."""
    return f"{MINUS if value < 0 else ''}{abs(value) * 100:.{decimals}f}%"


def _domain(values, include_zero=False, pad=0.16):
    """Padded [lo, hi] for one axis, optionally forced to span zero so the zero line and
    a sign change are always on the plane."""
    lo, hi = min(values), max(values)
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    span = (hi - lo) or 0.02
    return lo - span * pad, hi + span * pad


def render(points, basis: str = "quarterly") -> str:
    """SVG for the growth-against-margin trajectory, or "" when too little to plot.

    ``points`` are oldest first, each with label, revenue_growth and net_margin. A period
    missing either figure has no place in the plane and is dropped from the path, not
    drawn at zero.
    """
    usable = [p for p in points if p.get("revenue_growth") is not None
              and p.get("net_margin") is not None]
    if len(usable) < 2:
        return ""

    xs = [p["revenue_growth"] for p in usable]
    ys = [p["net_margin"] for p in usable]
    x_lo, x_hi = _domain(xs, include_zero=True)
    y_lo, y_hi = _domain(ys, include_zero=True)
    plot_w, plot_h = W - PAD_L - PAD_R, H - TOP - BOTTOM

    def x_at(value):
        return PAD_L + (value - x_lo) / (x_hi - x_lo) * plot_w

    def y_at(value):
        return TOP + (y_hi - value) / (y_hi - y_lo) * plot_h

    out = [
        f'<svg viewBox="0 0 {W} {H}" width="100%"'
        f' style="max-width:{W}px;font-family:Public Sans,sans-serif" role="img"'
        f' aria-label="Revenue growth against net margin over the last'
        f' {len(usable)} {"quarters" if basis == "quarterly" else "years"}, as a path">'
    ]

    # The axes: left and bottom hairlines.
    out.append(f'<line x1="{PAD_L}" y1="{TOP}" x2="{PAD_L}" y2="{TOP + plot_h}"'
               f' stroke="{P.rule}"/>')
    out.append(f'<line x1="{PAD_L}" y1="{TOP + plot_h}" x2="{PAD_L + plot_w}"'
               f' y2="{TOP + plot_h}" stroke="{P.rule}"/>')

    # Zero growth: the line a company crosses from shrinking to growing.
    if x_lo < 0 < x_hi:
        zx = x_at(0)
        out.append(f'<line x1="{zx:.1f}" y1="{TOP}" x2="{zx:.1f}" y2="{TOP + plot_h}"'
                   f' stroke="{P.rule_strong}" stroke-dasharray="3,3"/>')
        out.append(f'<text x="{zx + 4:.1f}" y="{TOP + 10}" font-size="8.5"'
                   f' fill="{P.stale}">0% growth</text>')

    # Each axis names its extremes where the data reaches them.
    for value in (min(ys), max(ys)):
        out.append(f'<text x="{PAD_L - 6}" y="{y_at(value) + 3:.1f}" font-size="9"'
                   f' text-anchor="end" fill="{P.stale}">{_pct(value, 0)}</text>')
    for value in (min(xs), max(xs)):
        out.append(f'<text x="{x_at(value):.1f}" y="{TOP + plot_h + 14:.1f}" font-size="9"'
                   f' text-anchor="middle" fill="{P.stale}">{_pct(value, 0)}</text>')

    # The path, oldest to newest.
    pts = [(x_at(p["revenue_growth"]), y_at(p["net_margin"])) for p in usable]
    out.append('<polyline points="'
               + " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
               + f'" fill="none" stroke="{P.stale}" stroke-width="1.5"/>')

    # Arrowhead short of the latest point, so the direction of travel is explicit.
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    angle = math.atan2(y2 - y1, x2 - x1)
    back_x, back_y = x2 - 9 * math.cos(angle), y2 - 9 * math.sin(angle)
    wing = 3.6
    out.append(
        f'<polygon points="{back_x + 8 * math.cos(angle):.1f},'
        f'{back_y + 8 * math.sin(angle):.1f} '
        f'{back_x - wing * math.sin(angle):.1f},{back_y + wing * math.cos(angle):.1f} '
        f'{back_x + wing * math.sin(angle):.1f},{back_y - wing * math.cos(angle):.1f}"'
        f' fill="{P.ink}"/>')

    # Dots: history light, the latest heavy and in the data colour.
    for index, (px, py) in enumerate(pts):
        last = index == len(pts) - 1
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{4.5 if last else 2.6}"'
                   f' fill="{P.data if last else P.ground}"'
                   f' stroke="{P.data if last else P.stale}" stroke-width="1.4"/>')

    # Label the first period above its dot, so the path reads start to now.
    first, latest = usable[0], usable[-1]
    fx, fy = pts[0]
    out.append(f'<text x="{fx:.1f}" y="{fy - 7:.1f}" font-size="8.5" text-anchor="middle"'
               f' fill="{P.stale}">{html.escape(first["label"])}</text>')

    # The latest period carries its label and figures, flipped to the inside near an edge.
    lx, ly = pts[-1]
    right_side = lx > PAD_L + plot_w * 0.62
    label_x = lx - 9 if right_side else lx + 9
    anchor = "end" if right_side else "start"
    out.append(f'<text x="{label_x:.1f}" y="{ly - 4:.1f}" font-size="10"'
               f' text-anchor="{anchor}" fill="{P.ink}" font-weight="700">'
               f'{html.escape(latest["label"])}</text>')
    out.append(f'<text x="{label_x:.1f}" y="{ly + 9:.1f}" font-size="9"'
               f' text-anchor="{anchor}">'
               f'<tspan fill="{P.data}" font-weight="600">'
               f'{_pct(latest["revenue_growth"])}</tspan>'
               f'<tspan fill="{P.stale}"> growth, </tspan>'
               f'<tspan fill="{P.ink}" font-weight="600">'
               f'{_pct(latest["net_margin"])}</tspan>'
               f'<tspan fill="{P.stale}"> margin</tspan></text>')

    # Axis titles: the metric each direction measures.
    out.append(f'<text x="{PAD_L + plot_w / 2:.1f}" y="{H - 5}" font-size="9.5"'
               f' text-anchor="middle" fill="{P.stale}">Revenue growth &#8594;</text>')
    out.append(f'<text x="{PAD_L - 6}" y="{TOP - 8}" font-size="9.5"'
               f' fill="{P.stale}">Net margin &#8593;</text>')

    out.append("</svg>")
    return "".join(out)


def caption(points, basis: str = "quarterly") -> str:
    """One sentence stating where the path started and finished. Facts, no reading."""
    usable = [p for p in points if p.get("revenue_growth") is not None
              and p.get("net_margin") is not None]
    if len(usable) < 2:
        return ""
    first, last = usable[0], usable[-1]
    unit = "quarters" if basis == "quarterly" else "fiscal years"
    return (f"Over {len(usable)} {unit} to {last['label']}, growth ran "
            f"{_pct(first['revenue_growth'])} to {_pct(last['revenue_growth'])} and "
            f"net margin {_pct(first['net_margin'])} to {_pct(last['net_margin'])}. "
            "Each period is plotted as growth against margin and joined in time; up and to "
            "the right is both improving together.")
