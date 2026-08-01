"""The engine as a treemap: area is size, colour is the move.

Squarified rather than sliced. A slice-and-dice treemap gives the smallest companies
slivers a label cannot sit in, and the point of the view is that every company is legible
at once. The squarified rule lays each row so its boxes stay as near square as it can,
which is what keeps a ticker readable in the small ones.

Colour diverges around zero on the two direction tokens, so a box's shade is its move and
its area is its size, and the two are read independently: a large box that is deep red is
the thing the view exists to show. A company whose price series is too short to measure
keeps its area and takes the panel colour, since an unknown move is not a flat one.

Pure: it takes rows and returns SVG. No Streamlit, no API, no database.
"""

from __future__ import annotations

from components import tokens as TK

# Drawn into half the page width, beside the forward view, so the canvas is close to
# square. A wide, shallow one at that width gives the small companies letterbox slivers,
# which is the shape a treemap is chosen to avoid.
WIDTH, HEIGHT = 700, 215
PAD = 1.0                # the hairline between boxes
LABEL_MIN = 34           # a box narrower or shorter than this gets no ticker
VALUE_MIN = 54           # and none smaller than this gets its percentage too

# The move at which a box reaches full colour. A display decision rather than a fact about
# the data: one company up 700% otherwise makes every other box the same shade.
COLOUR_CLIP = 0.40


def _colour(change) -> str:
    """A box's fill: the move, diverging around zero, clipped at the extremes."""
    if change is None:
        return TK.PANEL
    weight = min(abs(change) / COLOUR_CLIP, 1.0)
    end = TK.UP if change >= 0 else TK.DOWN
    return _mix(TK.PANEL, end, 0.18 + 0.82 * weight)


def _mix(start: str, end: str, position: float) -> str:
    """Blend two hex colours. Kept here rather than imported so this module stays pure of
    the palette machinery; the two tokens are the only colours it ever mixes."""
    a = [int(start[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(end[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * position):02x}" for x, y in zip(a, b))


def _squarify(values, x, y, width, height) -> list:
    """(x, y, w, h) per value, laid out so each box is as near square as it can be.

    The standard algorithm: fill a row along the shorter side, adding boxes while the
    worst aspect ratio in the row improves, then lay the row and recurse on what is left.
    """
    if not values:
        return []
    total = sum(values)
    if total <= 0 or width <= 0 or height <= 0:
        return []
    scale = (width * height) / total
    areas = [v * scale for v in values]

    def worst(row, side):
        if not row or side <= 0:
            return float("inf")
        total_row = sum(row)
        if total_row <= 0:
            return float("inf")
        side_sq = side * side
        row_sq = total_row * total_row
        return max(side_sq * max(row) / row_sq, row_sq / (side_sq * min(row)))

    out = []
    left, top, w, h = x, y, width, height
    index = 0
    while index < len(areas):
        side = min(w, h)
        row = [areas[index]]
        nxt = index + 1
        while nxt < len(areas) and worst(row + [areas[nxt]], side) <= worst(row, side):
            row.append(areas[nxt])
            nxt += 1
        total_row = sum(row)
        if w <= h:                                  # the row runs across the top
            depth = total_row / w if w else 0
            offset = left
            for area in row:
                box_w = area / depth if depth else 0
                out.append((offset, top, box_w, depth))
                offset += box_w
            top += depth
            h -= depth
        else:                                       # the row runs down the left
            depth = total_row / h if h else 0
            offset = top
            for area in row:
                box_h = area / depth if depth else 0
                out.append((left, offset, depth, box_h))
                offset += box_h
            left += depth
            w -= depth
        index = nxt
    return out


def build(rows: list, width: int = WIDTH, height: int = HEIGHT) -> str:
    """One box per company, largest first."""
    rows = [r for r in rows if (r.get("size") or 0) > 0]
    if not rows:
        return ""
    boxes = _squarify([r["size"] for r in rows], 0, 0, width, height)

    marks = []
    for row, (x, y, w, h) in zip(rows, boxes):
        if w <= 0 or h <= 0:
            continue
        inner_w, inner_h = max(w - PAD, 0.6), max(h - PAD, 0.6)
        change = row.get("change")
        pct = "" if change is None else f"{change * 100:+.0f}%"
        title = (f"{row['ticker']}: {row.get('name') or ''}"
                 f"{' · ' + pct if pct else ' · no price history'}")
        marks.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{inner_w:.2f}" height="{inner_h:.2f}" '
            f'fill="{_colour(change)}" stroke="{TK.GROUND}" stroke-width="0.5">'
            f'<title>{title}</title></rect>')
        # The label only where it fits. A ticker clipped by its own box is worse than a
        # box a reader hovers.
        if inner_w >= LABEL_MIN and inner_h >= LABEL_MIN:
            size = 8 + min(inner_w, inner_h) / 26
            size = min(size, 15)
            marks.append(
                f'<text x="{x + inner_w / 2:.2f}" y="{y + inner_h / 2:.2f}" '
                f'text-anchor="middle" font-family="{TK.FONT_MONO}" '
                f'font-size="{size:.1f}" font-weight="600" fill="{TK.TEXT}" '
                f'dy="{0 if inner_h < VALUE_MIN else -3}">{row["ticker"]}</text>')
            if inner_h >= VALUE_MIN and pct:
                marks.append(
                    f'<text x="{x + inner_w / 2:.2f}" y="{y + inner_h / 2:.2f}" '
                    f'text-anchor="middle" font-family="{TK.FONT_MONO}" '
                    f'font-size="{size - 2:.1f}" fill="{TK.TEXT}" opacity="0.75" '
                    f'dy="12">{pct}</text>')

    return (f'<svg viewBox="0 0 {width} {height}" width="100%" '
            f'xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="one box per company, area is size and colour is the move">'
            f'{"".join(marks)}</svg>')
