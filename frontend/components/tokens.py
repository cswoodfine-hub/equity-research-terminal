"""Design tokens, the Python mirror of assets/tokens.css.

One palette, six core values plus the phase ramp, defined here for the SVG builders
and in tokens.css for the page. A unit test asserts the two files agree, so neither
can drift. No colour or spacing constant may be written anywhere else.
"""

from __future__ import annotations

# --- Palette --------------------------------------------------------------
GROUND = "#0C1417"        # deep petrol, page background
PANEL = "#131E22"         # raised surface
RULE = "#1F2E33"          # hairlines, gridlines, table borders
TEXT = "#E8EDEA"          # warm paper white
MUTED = "#7E9098"         # labels, axis text, secondary
UP = "#4C9A7A"            # positive delta, and the measured-series colour
DOWN = "#C4553B"          # negative delta
FLAG = "#D9B26B"          # material change, needs review, uncurated

# One step lighter than RULE, for hairlines that carry structure (section rules,
# axis domains). Derived, not a seventh palette value.
RULE_STRONG = "#2E4249"

# Phase ramp, ordinal, brightness rising toward market so proximity to approval
# reads instantly. Colour is never the only signal: every use carries a label too.
PHASE_RAMP = {
    "preclinical": "#2E4A52",
    "Phase 1": "#3E6B72",
    "Phase 2": "#5A9089",
    "Phase 3": "#93AE77",
    "filed": "#D9B26B",
    "approved": "#E8EDEA",
}
# Seamless phases sit at the phase they reach, matching the app-wide convention.
PHASE_RAMP["Phase 1/2"] = PHASE_RAMP["Phase 2"]
PHASE_RAMP["Phase 2/3"] = PHASE_RAMP["Phase 3"]

# Modality keeps the two FDA book colours, retuned to sit inside this palette.
# Always paired with a label; never gradients.
ORANGE_BOOK = "#C98A4B"
PURPLE_BOOK = "#8B7FC7"

# --- Spacing and radius ---------------------------------------------------
SPACE = 8                 # px base unit; every gap is a multiple
RADIUS = 0                # border radius is 0 or 2, nothing larger
RADIUS_SMALL = 2

# --- Type roles -----------------------------------------------------------
FONT_UI = "'Archivo', -apple-system, 'Segoe UI', system-ui, sans-serif"
FONT_UI_NARROW = "'Archivo Narrow', 'Archivo', 'Arial Narrow', sans-serif"
FONT_MONO = "'IBM Plex Mono', ui-monospace, 'SF Mono', Menlo, monospace"
FONT_PROSE = "'Newsreader', 'Iowan Old Style', Georgia, serif"
