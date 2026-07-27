"""Contrast guarantees for the ordinal chart ramp.

Lives here rather than beside the frontend so that ``cd backend && pytest -q`` stays the
one test command; theme.py is pure colour maths at this level and imports cleanly.

The bug these lock down shipped silently: the phase scale declared six phases against a
fixed tuple of five tints, so Phase 4 had no colour of its own, and the two darkest
tints sat at 1.15:1 and 1.57:1 against the ground, which is invisible.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import theme  # noqa: E402

PALETTES = [theme.LIGHT, theme.DARK]
PHASES = 6      # Phase 1, 1/2, 2, 2/3, 3, 4

# Spelled out rather than read from theme.GRAPHIC_CONTRAST on purpose. Asserting
# against the module's own constant moves the goalposts with it: lowering the constant
# to 1.2 left the whole file passing, which is no test at all. 3:1 is WCAG 1.4.11 and
# comes from outside this codebase, so it is what the test is entitled to assume.
WCAG_GRAPHIC = 3.0


@pytest.mark.parametrize("palette", PALETTES, ids=lambda p: p.name)
def test_ramp_is_as_long_as_asked_for(palette):
    """The scale takes its range from the length of its domain, so this is the
    invariant that stops a seventh phase silently losing its colour."""
    for steps in (2, 3, PHASES, 9):
        assert len(theme.ordinal_ramp(steps, palette)) == steps


@pytest.mark.parametrize("palette", PALETTES, ids=lambda p: p.name)
def test_every_step_clears_the_graphic_contrast_floor(palette):
    """WCAG 1.4.11: a graphical object carrying meaning needs 3:1 against its ground."""
    for colour in theme.ordinal_ramp(PHASES, palette):
        ratio = theme.contrast(colour, palette.ground)
        assert ratio >= WCAG_GRAPHIC - 0.01, f"{colour} at {ratio:.2f}:1"


@pytest.mark.parametrize("palette", PALETTES, ids=lambda p: p.name)
def test_steps_are_ordered_and_distinct(palette):
    """An ordinal ramp has to climb, and no two steps may land on the same colour."""
    ramp = theme.ordinal_ramp(PHASES, palette)
    assert len(set(ramp)) == PHASES
    ratios = [theme.contrast(colour, palette.ground) for colour in ramp]
    assert ratios == sorted(ratios)


@pytest.mark.parametrize("palette", PALETTES, ids=lambda p: p.name)
def test_ramp_ends_on_the_data_colour(palette):
    """Phase is ordinal, so it climbs to the data colour rather than taking its own
    hue. Modality stays the only categorical use of hue in the app."""
    assert theme.ordinal_ramp(PHASES, palette)[-1].upper() == palette.data.upper()


def test_contrast_is_symmetric_and_matches_known_pairs():
    assert theme.contrast("#FFFFFF", "#000000") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast("#000000", "#FFFFFF") == pytest.approx(21.0, abs=0.01)
    assert theme.contrast("#777777", "#777777") == pytest.approx(1.0, abs=0.01)


def test_the_old_fixed_tints_would_fail_the_floor():
    """Kept as the record of what was wrong, so the floor cannot quietly be lowered."""
    worst = min(theme.contrast(tint, theme.DARK.ground)
                for tint in theme.DARK.phase_tints)
    assert worst < WCAG_GRAPHIC                # 1.15:1, the invisible Phase 1
    assert len(theme.DARK.phase_tints) < PHASES  # five tints against six phases


def test_categorical_gives_every_area_a_visible_colour():
    """Categories carry meaning, so each has to clear the graphic contrast floor."""
    colours = theme.categorical(12)
    assert len(colours) == 12
    for colour in colours:
        assert theme.contrast(colour, theme.P.ground) >= theme.GRAPHIC_CONTRAST


def test_categorical_colours_are_distinct():
    """A palette that repeats a colour puts two areas in one slice of the eye."""
    colours = theme.categorical(12)
    assert len(set(colours)) == 12


def test_categorical_is_stable_for_a_given_count():
    # Areas keep their colour across companies only if the palette is deterministic.
    assert theme.categorical(12) == theme.categorical(12)


def test_categorical_handles_a_single_category():
    assert theme.categorical(1) == [theme.P.data]
