"""R&D against commercial performance, as a quadrant scatter.

Two composite scores, each a weighted z-score against the companies on the chart, so the
axes cross at the group average rather than at any absolute standard. That is what makes
the quadrants readable and also what they are limited to: the chart says who is ahead of
these peers this year, not whether any of them is doing well.

Labels are the hard part of a small scatter. Thirteen companies in a square inevitably
collide, so each label is placed to the right of its dot and then pushed vertically until
it clears the ones already placed, working outward from the origin so the extremes keep
their natural position. A label that cannot be cleared moves to the left of its dot
instead.

Pure: it takes rows and returns SVG. No Streamlit, no API, no database.
"""

from __future__ import annotations

from components import tokens as TK

WIDTH, HEIGHT = 760, 520
PAD_LEFT, PAD_RIGHT = 64, 64
PAD_TOP, PAD_BOTTOM = 40, 56

DOT = 4.5
LABEL_GAP = 8            # dot centre to the start of its text
LINE_HEIGHT = 13         # the vertical room one label needs
CHAR_WIDTH = 6.4         # enough to reserve space without measuring text

# The plot is padded past the extreme points so a dot never sits on the frame and its
# label always has room to sit beside it.
MARGIN_FRACTION = 0.18


def _bounds(values, fallback=1.0):
    low, high = min(values), max(values)
    if high - low < 1e-9:
        low, high = low - fallback, high + fallback
    span = (high - low) * MARGIN_FRACTION
    return low - span, high + span


def _place_labels(points: list) -> list:
    """Give each point a label position that does not overlap the ones already set.

    Ordered by distance from the origin so the outliers, which are the ones a reader
    looks for, keep the position closest to their dot.
    """
    placed: list = []
    order = sorted(points, key=lambda p: -(p["x"] ** 2 + p["y"] ** 2))
    for point in order:
        width = len(point["ticker"]) * CHAR_WIDTH
        for anchor in ("start", "end"):
            offset = LABEL_GAP if anchor == "start" else -LABEL_GAP
            left = point["px"] + offset if anchor == "start" else \
                point["px"] + offset - width
            for nudge in (0, -LINE_HEIGHT, LINE_HEIGHT, -2 * LINE_HEIGHT,
                          2 * LINE_HEIGHT, -3 * LINE_HEIGHT, 3 * LINE_HEIGHT):
                top = point["py"] + nudge
                box = (left, top - LINE_HEIGHT / 2, left + width, top + LINE_HEIGHT / 2)
                if all(box[2] < o[0] or box[0] > o[2] or box[3] < o[1] or box[1] > o[3]
                       for o in placed):
                    placed.append(box)
                    point["lx"] = point["px"] + offset
                    point["ly"] = top + 3.5      # optical centring on the cap height
                    point["anchor"] = anchor
                    break
            else:
                continue
            break
        else:
            # Nothing cleared, so it sits on its dot rather than being dropped.
            point["lx"] = point["px"] + LABEL_GAP
            point["ly"] = point["py"] + 3.5
            point["anchor"] = "start"
    return points


def build(rows: list) -> str:
    """The scatter as an SVG string. Empty string when there is nothing to plot."""
    if not rows:
        return ""

    xs = [r["rd_score"] for r in rows]
    ys = [r["commercial_score"] for r in rows]
    x_low, x_high = _bounds(xs)
    y_low, y_high = _bounds(ys)
    plot_w = WIDTH - PAD_LEFT - PAD_RIGHT
    plot_h = HEIGHT - PAD_TOP - PAD_BOTTOM

    def px(value):
        return PAD_LEFT + (value - x_low) / (x_high - x_low) * plot_w

    def py(value):
        return PAD_TOP + (y_high - value) / (y_high - y_low) * plot_h

    points = _place_labels([
        {"ticker": r["ticker"], "x": r["rd_score"], "y": r["commercial_score"],
         "px": px(r["rd_score"]), "py": py(r["commercial_score"]),
         "quadrant": r["quadrant"]}
        for r in rows])

    zero_x, zero_y = px(0), py(0)
    parts = [
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="R&amp;D score against commercial score">',
        f'<rect x="0" y="0" width="{WIDTH}" height="{HEIGHT}" fill="{TK.GROUND}"/>',
    ]

    # The quadrant lines are the chart. Drawn dashed and in the hairline colour so they
    # read as a reference rather than as plotted data.
    parts.append(
        f'<line x1="{zero_x:.1f}" y1="{PAD_TOP}" x2="{zero_x:.1f}" '
        f'y2="{PAD_TOP + plot_h}" stroke="{TK.RULE_STRONG}" stroke-width="1" '
        f'stroke-dasharray="3 3"/>')
    parts.append(
        f'<line x1="{PAD_LEFT}" y1="{zero_y:.1f}" x2="{PAD_LEFT + plot_w}" '
        f'y2="{zero_y:.1f}" stroke="{TK.RULE_STRONG}" stroke-width="1" '
        f'stroke-dasharray="3 3"/>')

    label_style = (f'font-family="{TK.FONT_UI}" font-size="10" '
                   f'letter-spacing="0.08em" fill="{TK.MUTED}"')
    parts.append(
        f'<text x="{PAD_LEFT + plot_w}" y="{zero_y - 8:.1f}" text-anchor="end" '
        f'{label_style}>R&amp;D OUTPERFORMERS</text>')
    parts.append(
        f'<text x="{zero_x + 8:.1f}" y="{PAD_TOP + 12}" text-anchor="start" '
        f'{label_style}>COMMERCIAL OUTPERFORMERS</text>')

    parts.append(
        f'<text x="{PAD_LEFT + plot_w / 2:.1f}" y="{HEIGHT - 16}" '
        f'text-anchor="middle" {label_style}>COMPOSITE R&amp;D SCORE</text>')
    parts.append(
        f'<text x="16" y="{PAD_TOP + plot_h / 2:.1f}" text-anchor="middle" '
        f'{label_style} transform="rotate(-90 16 {PAD_TOP + plot_h / 2:.1f})">'
        f'COMPOSITE COMMERCIAL SCORE</text>')

    for point in points:
        # A company ahead on both axes is the one worth finding, so it alone carries the
        # data colour. Everything else is ink: the position is the message and a colour
        # per quadrant would say the same thing twice.
        fill = TK.UP if point["quadrant"] == "Both" else TK.TEXT
        parts.append(
            f'<circle cx="{point["px"]:.1f}" cy="{point["py"]:.1f}" r="{DOT}" '
            f'fill="{fill}"/>')
        parts.append(
            f'<text x="{point["lx"]:.1f}" y="{point["ly"]:.1f}" '
            f'text-anchor="{point["anchor"]}" font-family="{TK.FONT_MONO}" '
            f'font-size="11" fill="{fill}">{point["ticker"]}</text>')

    parts.append("</svg>")
    return "".join(parts)
