"""Growth against margin as two lines on one percentage axis: the tests read the
markup ``trend.render`` returns.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures synthetic.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import trend  # noqa: E402


def _points(*rows):
    """Oldest first, each (label, growth, margin); None where a figure is absent."""
    return [{"label": label, "revenue_growth": growth, "net_margin": margin}
            for label, growth, margin in rows]


YEAR = _points(("Q2 25", 0.38, 0.36), ("Q3 25", 0.54, 0.32),
               ("Q4 25", 0.43, 0.34), ("Q1 26", 0.56, 0.37))


def test_two_lines_one_per_series():
    svg = trend.render(YEAR, "quarterly")
    assert svg.count("<polyline") == 2   # growth and margin, each an unbroken line


def test_a_legend_names_both_series_with_their_latest_value():
    svg = trend.render(YEAR, "quarterly")
    assert "Revenue growth" in svg and "Net margin" in svg
    assert "56.0%" in svg and "37.0%" in svg   # the latest of each, in the legend


def test_each_series_takes_its_own_colour():
    from theme import P
    svg = trend.render(YEAR, "quarterly")
    assert P.data in svg          # revenue growth
    assert P.orange_book in svg   # net margin, a distinct hue


def test_a_zero_line_appears_only_when_a_series_turns_negative():
    positive = trend.render(YEAR, "quarterly")
    assert "stroke-dasharray" not in positive   # nothing dashed while all-positive
    crosses = trend.render(_points(("Q3 25", 0.10, 0.2), ("Q4 25", -0.06, 0.21),
                                   ("Q1 26", 0.05, 0.19)), "quarterly")
    assert "stroke-dasharray" in crosses        # the zero line, dashed
    assert "0%" in crosses


def test_a_missing_figure_breaks_that_line_not_plotted_as_zero():
    svg = trend.render(_points(("Q1 26", 0.5, None), ("Q2 26", 0.4, 0.30),
                               ("Q3 26", 0.45, 0.31)), "quarterly")
    # growth keeps all three dots; margin drops the first period it has no figure for.
    assert svg.count("<circle") == 5


def test_too_few_points_render_nothing():
    assert trend.render(_points(("Q1 26", 0.5, 0.3)), "quarterly") == ""


def test_the_caption_states_the_window_and_both_endpoints():
    caption = trend.caption(YEAR, "quarterly")
    assert "Over 4 quarters to Q1 26" in caption
    assert "38.0%" in caption and "56.0%" in caption   # growth start and end
    assert "percentage axis" in caption                # the reading of the panel
