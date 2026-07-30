"""The distribution of one engine's own metric, as a bar per company.

Three engines, three questions, so three different strips: the share of revenue that is
new, the months of cash left, the furthest stage on file. Same shape each time, which is
the point. A reader learns the form once and then takes each engine's spread at a glance,
including how much of it is missing.

Two rules make the shape honest. Every strip falls from left to right, so the end that
matters is always the left one and no engine can look like it is improving because of the
sort order. And a company with no figure keeps its slot, drawn as a stub hanging below the
baseline: a zero and an unknown must never be the same mark, and one of them is a
measurement while the other is a gap in the data.

No axis and no labels. This is a shape, not a chart: the numbers behind it are on the card
beside it, and the engine it opens has the whole table.

Pure: it takes the strip rows the backend built and returns SVG. No Streamlit, no API, no
database.
"""

from __future__ import annotations

from components import tokens as TK

WIDTH, HEIGHT = 300, 50
BASELINE_Y = 44          # every bar stands on this, and the gaps hang under it
BAR_GAP = 1.6            # between bars, in viewBox units
MIN_BAR = 1.5            # a real but tiny value still has to be visible
GAP_DROP = 2.0           # clear air between the baseline and a missing stub
GAP_DEPTH = 3.5          # how far a missing stub hangs

# A tone is a role the backend names, resolved to a token here. The frontend owns colour;
# the backend owning it would put a hex value outside the two token files.
TONES = {"up": TK.UP, "down": TK.DOWN, "muted": TK.RULE_STRONG}


def _colour(row: dict) -> str:
    """The bar's colour. A phase tone reads its own label off the ramp, so the cell and
    gene strip is coloured by stage the way every other phase view in the app is."""
    if row.get("tone") == "phase":
        phase = row.get("phase") or ""
        if phase in TK.PHASE_RAMP:
            return TK.PHASE_RAMP[phase]
        # Marketed and Phase 4 both mean an approval happened, which is the top of the
        # ramp. A tone with no label at all is a gap, and takes the muted token.
        return TK.PHASE_RAMP["approved"] if phase else TK.RULE_STRONG
    return TONES.get(row.get("tone"), TK.UP)


def build(rows: list) -> str:
    """One bar per company, in the order the backend sorted them."""
    if not rows:
        return ""
    slot = WIDTH / len(rows)
    width = max(slot - BAR_GAP, 0.9)

    marks = []
    for index, row in enumerate(rows):
        height = row.get("height")
        x = index * slot
        if height:
            drawn = max(height * BASELINE_Y, MIN_BAR)
            y, fill, extra = BASELINE_Y - drawn, _colour(row), ""
        else:
            drawn, y = GAP_DEPTH, BASELINE_Y + GAP_DROP
            fill, extra = TK.RULE_STRONG, ' opacity="0.8"'
        # The title is the whole tooltip: an SVG title element is read by the browser and
        # by a screen reader, so the strip stays interrogable without a legend.
        marks.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{width:.2f}" height="{drawn:.2f}" '
            f'fill="{fill}"{extra}>'
            f'<title>{row["ticker"]}: {row.get("display", "")}</title></rect>')

    return (f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" width="100%" '
            f'preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" '
            f'role="img" aria-label="one bar per company, largest first">'
            f'{"".join(marks)}'
            f'<rect x="0" y="{BASELINE_Y}" width="{WIDTH}" height="1" '
            f'fill="{TK.RULE}"/></svg>')
