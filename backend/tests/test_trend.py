"""The growth-against-margin panel: the recent-quarter view and its geometry.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures are
synthetic. The render is pure SVG, so the tests read the markup it returns.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import trend  # noqa: E402


def _points(*rows):
    """Oldest first, each (label, growth, margin); None where a figure is absent."""
    return [{"label": label, "revenue_growth": growth, "net_margin": margin}
            for label, growth, margin in rows]


def _bar_widths(svg: str) -> list[float]:
    return [float(w) for w in re.findall(r'<rect [^>]*width="([\d.]+)"', svg)]


YEAR = _points(("Q2 25", 0.38, 0.36), ("Q3 25", 0.54, 0.32),
               ("Q4 25", 0.43, 0.34), ("Q1 26", 0.56, 0.37))


def test_a_four_quarter_panel_draws_a_bar_for_each_quarter():
    svg = trend.render(YEAR, "quarterly")
    assert len(_bar_widths(svg)) == 4
    # Every quarter is named on the axis, not every other, since the window is short.
    for label in ("Q2 25", "Q3 25", "Q4 25", "Q1 26"):
        assert label in svg


def test_a_short_series_does_not_balloon_its_bars():
    """Four quarters means wide slots; without the cap the bars would draw as blocks."""
    wide_slot = trend.render(YEAR, "quarterly")
    assert max(_bar_widths(wide_slot)) == trend.MAX_BAR_W
    # A long series sits below the cap, so it is left alone.
    nine = _points(*[(f"P{i}", 0.2, 0.2) for i in range(9)])
    assert max(_bar_widths(trend.render(nine, "quarterly"))) < trend.MAX_BAR_W


def test_a_falling_quarter_draws_below_the_zero_rule():
    """A negative growth quarter must render, in the loss colour, not vanish."""
    from theme import P
    svg = trend.render(_points(("Q3 25", 0.10, 0.2), ("Q4 25", -0.06, 0.21),
                               ("Q1 26", 0.05, 0.19)), "quarterly")
    assert P.oxblood in svg          # the down bar is drawn in the loss colour
    assert len(_bar_widths(svg)) == 3


def test_too_few_points_render_nothing():
    assert trend.render(_points(("Q1 26", 0.5, 0.3)), "quarterly") == ""


def test_the_caption_states_the_window_and_both_endpoints():
    caption = trend.caption(YEAR, "quarterly")
    assert "Over 4 quarters to Q1 26" in caption
    assert "38.0%" in caption and "56.0%" in caption   # growth start and end
