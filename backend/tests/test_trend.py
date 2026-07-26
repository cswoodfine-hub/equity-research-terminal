"""The growth-against-margin trajectory: one point per period in the growth/margin plane,
joined in time, latest emphasised. Pure SVG, so the tests read the markup it returns.

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


def test_a_point_per_period_joined_by_one_path():
    svg = trend.render(YEAR, "quarterly")
    assert svg.count("<circle") == 4        # one dot per quarter
    assert svg.count("<polyline") == 1      # a single path through them in time
    assert "Q2 25" in svg and "Q1 26" in svg   # the first and the latest are labelled


def test_the_latest_period_is_emphasised_and_carries_its_figures():
    from theme import P
    svg = trend.render(YEAR, "quarterly")
    assert f'fill="{P.data}"' in svg          # the latest dot and its growth figure
    assert "56.0%" in svg and "37.0%" in svg  # the latest growth and margin, spelt out


def test_each_axis_names_its_extremes():
    svg = trend.render(YEAR, "quarterly")
    assert "38%" in svg and "56%" in svg      # growth floor and top, on the x axis
    assert "32%" in svg and "37%" in svg      # margin floor and top, on the y axis


def test_a_zero_growth_line_appears_when_growth_crosses_zero():
    svg = trend.render(_points(("Q3 25", 0.10, 0.2), ("Q4 25", -0.06, 0.21),
                               ("Q1 26", 0.05, 0.19)), "quarterly")
    assert "0% growth" in svg
    assert "stroke-dasharray" in svg
    assert svg.count("<circle") == 3


def test_a_period_missing_a_figure_has_no_place_in_the_plane():
    svg = trend.render(_points(("Q1 26", 0.5, None), ("Q2 26", 0.4, 0.30),
                               ("Q3 26", 0.45, 0.31)), "quarterly")
    assert svg.count("<circle") == 2          # the period with no margin is dropped


def test_too_few_points_render_nothing():
    assert trend.render(_points(("Q1 26", 0.5, 0.3)), "quarterly") == ""


def test_the_caption_states_the_window_and_both_endpoints():
    caption = trend.caption(YEAR, "quarterly")
    assert "Over 4 quarters to Q1 26" in caption
    assert "38.0%" in caption and "56.0%" in caption   # growth start and end
    assert "up and to the right" in caption            # the reading of the plane
