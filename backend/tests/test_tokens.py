"""The token files: the CSS and the Python mirror must agree.

Every colour the SVG builders use comes from components/tokens.py and every colour
the page uses comes from assets/tokens.css. If the two drift, charts stop matching
the chrome around them, so the agreement is a test rather than a convention.
"""

import re
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
sys.path.insert(0, str(FRONTEND))

from components import tokens  # noqa: E402


def _css_vars() -> dict:
    text = (FRONTEND / "assets" / "tokens.css").read_text()
    return dict(re.findall(r"--([a-z0-9-]+):\s*([^;]+);", text))


CSS = _css_vars()

PAIRS = [
    ("ground", tokens.GROUND), ("panel", tokens.PANEL), ("rule", tokens.RULE),
    ("rule-strong", tokens.RULE_STRONG), ("text", tokens.TEXT),
    ("muted", tokens.MUTED), ("up", tokens.UP), ("down", tokens.DOWN),
    ("flag", tokens.FLAG),
    ("orange-book", tokens.ORANGE_BOOK), ("purple-book", tokens.PURPLE_BOOK),
    ("phase-preclinical", tokens.PHASE_RAMP["preclinical"]),
    ("phase-1", tokens.PHASE_RAMP["Phase 1"]),
    ("phase-2", tokens.PHASE_RAMP["Phase 2"]),
    ("phase-3", tokens.PHASE_RAMP["Phase 3"]),
    ("phase-filed", tokens.PHASE_RAMP["filed"]),
    ("phase-approved", tokens.PHASE_RAMP["approved"]),
]


def test_css_and_python_tokens_agree():
    for name, python_value in PAIRS:
        assert CSS.get(name, "").strip().upper() == python_value.upper(), name


def test_spacing_and_radius_agree():
    assert CSS["space"].strip() == f"{tokens.SPACE}px"
    assert CSS["radius"].strip() == f"{tokens.RADIUS}px"
    assert CSS["radius-small"].strip() == f"{tokens.RADIUS_SMALL}px"


def test_seamless_phases_take_the_phase_they_reach():
    assert tokens.PHASE_RAMP["Phase 1/2"] == tokens.PHASE_RAMP["Phase 2"]
    assert tokens.PHASE_RAMP["Phase 2/3"] == tokens.PHASE_RAMP["Phase 3"]


def test_theme_palette_is_pointed_at_the_tokens():
    """theme.P is the compatibility layer every SVG module reads; it must carry the
    token values, not a second palette."""
    import theme
    assert theme.P.ground == tokens.GROUND
    assert theme.P.ink == tokens.TEXT
    assert theme.P.data == tokens.UP
    assert theme.P.oxblood == tokens.DOWN
    assert theme.P.raised == tokens.PANEL
    assert theme.P.flag == tokens.FLAG


def test_bundled_fonts_exist():
    """The three type roles ship locally; a missing file would silently fall back."""
    fonts = FRONTEND / "assets" / "fonts"
    for stem in ("archivo-latin-400-normal", "archivo-narrow-latin-600-normal",
                 "ibm-plex-mono-latin-400-normal", "newsreader-latin-400-normal"):
        assert (fonts / f"{stem}.woff2").exists(), stem
