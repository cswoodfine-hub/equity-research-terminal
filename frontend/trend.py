"""Growth against margin: two lines on one percentage axis.

Revenue growth and net margin are both percentages, so they belong on the same
axis and can be read against each other directly. Each is a line over the last
few periods, in its own colour, named in a legend that also carries its latest
value. Where a period is missing a figure the line breaks rather than dropping
to zero, so absence never reads as a collapse. A dashed line marks zero, drawn
only when a series actually turns negative.

Pure: builds SVG from a list of points and knows nothing about the API.
"""

from __future__ import annotations

import html

from theme import MINUS, P

W = 1100             # fills most of the column; the SVG scales to fit narrower ones
H = 340
PAD_L = 52           # room for the percentage axis figures
PAD_R = 20
TOP = 46             # room for the legend row
BOTTOM = 30          # room for the period labels

# How many period labels the axis can carry before they touch. The series itself is not
# thinned: every quarter is still plotted, and only the naming of them is rationed.
MAX_LABELS = 13

# How much of each tail the axis ignores when scaling, and the shortest series it is
# applied to. A short series has no outliers, only points.
TRIM = 0.05
MIN_FOR_TRIM = 12

GROWTH_COLOUR = P.data          # revenue growth, the plotted-series colour
MARGIN_COLOUR = P.orange_book   # net margin, a distinct second hue

MONO = "IBM Plex Mono, ui-monospace, Menlo, monospace"
UI = "Public Sans, system-ui, sans-serif"


def _pct(value, decimals=1) -> str:
    """A percentage carrying the app's true minus rather than a hyphen."""
    return f"{MINUS if value < 0 else ''}{abs(value) * 100:.{decimals}f}%"


def _domain(values, include_zero=False, pad=0.1):
    """Padded [lo, hi] for the shared axis, optionally forced to span zero so a
    sign change and the zero line always sit on the plane.

    Scaled to the body of the series rather than to its extremes. Over four quarters the
    two are the same; over forty they are not, and one quarter carrying a tax charge or
    a derived fourth quarter built on a mismatched full year flattens the other
    thirty-nine into a straight line. Johnson & Johnson has a quarter at minus fifty-three
    per cent and another at a hundred and twenty-two, and against those the eight years
    of margin either side read as no movement at all.

    Nothing is dropped. A point outside the frame is still drawn, clamped to the edge and
    marked, so the reader sees that it went off the top rather than that it went missing.
    """
    ordered = sorted(values)
    if len(ordered) >= MIN_FOR_TRIM:
        cut = max(1, int(len(ordered) * TRIM))
        body = ordered[cut:len(ordered) - cut] or ordered
    else:
        body = ordered
    lo, hi = min(body), max(body)
    if include_zero:
        lo, hi = min(lo, 0.0), max(hi, 0.0)
    span = (hi - lo) or 0.02
    return lo - span * pad, hi + span * pad


def _last_real(values):
    """The most recent figure a series actually has, or None."""
    return next((v for v in reversed(values) if v is not None), None)


def _runs(values):
    """Contiguous runs of real points as lists of (index, value); a null ends a run,
    so a gap breaks the line instead of bridging across missing data."""
    runs, run = [], []
    for i, v in enumerate(values):
        if v is None:
            if run:
                runs.append(run)
                run = []
            continue
        run.append((i, v))
    if run:
        runs.append(run)
    return runs


def render(points, basis: str = "quarterly") -> str:
    """SVG for growth and margin as two lines on one axis, or "" when too little to plot.

    ``points`` are oldest first, each with label, revenue_growth and net_margin. A
    period missing a figure breaks that one line at that point; it is never plotted
    as zero.
    """
    if len(points) < 2:
        return ""
    g_vals = [p.get("revenue_growth") for p in points]
    m_vals = [p.get("net_margin") for p in points]
    reals = [v for v in g_vals + m_vals if v is not None]
    if len(reals) < 2:
        return ""

    n = len(points)
    lo, hi = _domain(reals, include_zero=min(reals) < 0)
    plot_w, plot_h = W - PAD_L - PAD_R, H - TOP - BOTTOM

    def x_at(index):
        return PAD_L + (index / (n - 1)) * plot_w

    def off_scale(value):
        return value is not None and not (lo <= value <= hi)

    def y_at(value):
        clamped = min(max(value, lo), hi)
        return TOP + (hi - clamped) / (hi - lo) * plot_h

    out = [
        f'<svg viewBox="0 0 {W} {H}" width="100%"'
        f' style="max-width:{W}px;font-family:{UI}" role="img"'
        f' aria-label="Revenue growth and net margin over the last {n}'
        f' {"quarters" if basis == "quarterly" else "years"}, two lines on one axis">'
    ]

    # The axes: left and bottom hairlines.
    out.append(f'<line x1="{PAD_L}" y1="{TOP}" x2="{PAD_L}" y2="{TOP + plot_h}"'
               f' stroke="{P.rule}"/>')
    out.append(f'<line x1="{PAD_L}" y1="{TOP + plot_h}" x2="{PAD_L + plot_w}"'
               f' y2="{TOP + plot_h}" stroke="{P.rule}"/>')

    # Three quiet gridlines, each labelled with its percentage on the left.
    for frac in (0.0, 0.5, 1.0):
        value = hi - (hi - lo) * frac
        gy = TOP + plot_h * frac
        out.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{PAD_L + plot_w}"'
                   f' y2="{gy:.1f}" stroke="{P.rule}"/>')
        out.append(f'<text x="{PAD_L - 6}" y="{gy + 3:.1f}" font-size="9"'
                   f' text-anchor="end" fill="{P.stale}" font-family="{MONO}">'
                   f'{_pct(value, 0)}</text>')

    # Zero: the line a company crosses from shrinking to growing. Drawn only when a
    # series actually turns negative, so it is never noise on an all-positive panel.
    if lo < 0 < hi:
        zy = y_at(0)
        out.append(f'<line x1="{PAD_L}" y1="{zy:.1f}" x2="{PAD_L + plot_w}"'
                   f' y2="{zy:.1f}" stroke="{P.rule_strong}" stroke-dasharray="3,3"/>')
        out.append(f'<text x="{PAD_L + plot_w:.1f}" y="{zy - 3:.1f}" font-size="8.5"'
                   f' text-anchor="end" fill="{P.stale}">0%</text>')

    # The two lines, each broken at its own gaps, with a dot at every real point.
    for values, colour in ((g_vals, GROWTH_COLOUR), (m_vals, MARGIN_COLOUR)):
        for run in _runs(values):
            if len(run) > 1:
                pts = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in run)
                out.append(f'<polyline points="{pts}" fill="none" stroke="{colour}"'
                           f' stroke-width="1.8"/>')
        # A dot per point reads as a marked series at nine points and as a thick smear
        # at forty, so the radius comes down as the series lengthens and the dots stop
        # once they would be closer together than they are wide.
        radius = 2.4 if n <= 16 else (1.6 if n <= 28 else 0)
        if radius:
            for i, v in [(i, v) for i, v in enumerate(values) if v is not None]:
                out.append(f'<circle cx="{x_at(i):.1f}" cy="{y_at(v):.1f}"'
                           f' r="{radius}" fill="{colour}"/>')
        # A point outside the frame gets a caret at the edge it left through, pointing
        # the way it went, with its real figure on hover. Drawn at every length, since
        # this is the one mark that must not be thinned away.
        for i, v in enumerate(values):
            if not off_scale(v):
                continue
            up = v > hi
            edge = TOP + (2 if up else plot_h - 2)
            tip = -5 if up else 5
            out.append(
                f'<polygon points="{x_at(i) - 3.4:.1f},{edge:.1f} '
                f'{x_at(i) + 3.4:.1f},{edge:.1f} {x_at(i):.1f},{edge + tip:.1f}"'
                f' fill="{colour}"><title>{_pct(v)}, beyond the axis</title></polygon>')

    # Period labels along the bottom, thinned to what fits. Forty quarters at the width
    # of "Q2 26" would overprint into a grey band, so every nth is drawn and the rest are
    # left to the dots. The last point always keeps its label, because the period a
    # reader is standing on is the one they need named.
    every = max(1, -(-n // MAX_LABELS))
    for i, p in enumerate(points):
        if i % every and i != n - 1:
            continue
        out.append(f'<text x="{x_at(i):.1f}" y="{TOP + plot_h + 16:.1f}" font-size="8.5"'
                   f' text-anchor="middle" fill="{P.stale}" font-family="{MONO}">'
                   f'{html.escape(str(p.get("label") or ""))}</text>')

    # The legend: a stroke swatch, the series name, and its latest value in the colour.
    lx = PAD_L
    for name, colour, latest in (
        ("Revenue growth", GROWTH_COLOUR, _last_real(g_vals)),
        ("Net margin", MARGIN_COLOUR, _last_real(m_vals)),
    ):
        out.append(f'<line x1="{lx:.1f}" y1="16" x2="{lx + 15:.1f}" y2="16"'
                   f' stroke="{colour}" stroke-width="2.4"/>')
        out.append(f'<text x="{lx + 21:.1f}" y="19" font-size="10" fill="{P.ink}">'
                   f'{name}</text>')
        value_x = lx + 27 + len(name) * 5.6
        if latest is not None:
            out.append(f'<text x="{value_x:.1f}" y="19" font-size="10"'
                       f' font-family="{MONO}" font-weight="600" fill="{colour}">'
                       f'{_pct(latest)}</text>')
        lx = value_x + 52

    out.append("</svg>")
    return "".join(out)


def caption(points, basis: str = "quarterly") -> str:
    """One sentence stating where each line started and finished. Facts, no reading."""
    if len(points) < 2:
        return ""
    g_real = [p.get("revenue_growth") for p in points if p.get("revenue_growth") is not None]
    m_real = [p.get("net_margin") for p in points if p.get("net_margin") is not None]
    if len(g_real) < 2 and len(m_real) < 2:
        return ""
    unit = "quarters" if basis == "quarterly" else "fiscal years"
    parts = [f"Over {len(points)} {unit} to {points[-1].get('label')},"]
    if len(g_real) >= 2:
        parts.append(f" revenue growth ran {_pct(g_real[0])} to {_pct(g_real[-1])}")
    if len(m_real) >= 2:
        joiner = " and net margin" if len(g_real) >= 2 else " net margin"
        parts.append(f"{joiner} {_pct(m_real[0])} to {_pct(m_real[-1])}")
    return ("".join(parts).rstrip() + ". Both lines share one percentage axis, so their "
            "levels read against each other directly.")
