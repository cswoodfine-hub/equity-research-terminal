"""The catalyst calendar grid. Lives here so one pytest run covers the whole app.

The thing this has to get right is precision. A third of the dates carry a month and no
day, and a calendar that placed those on the first would draw a date the registry never
gave.
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import calendar_view  # noqa: E402

TODAY = dt.date(2026, 7, 19)


def _catalyst(date, title="A study of something", kind="data readout",
              confidence=None):
    return {"expected_date": date, "title": title, "catalyst_type": kind,
            "date_confidence": confidence or ("month" if len(date) == 7
                                              else "estimated")}


def test_months_run_forward_across_a_year_boundary():
    assert calendar_view.months_from(dt.date(2026, 11, 5), 4) == [
        "2026-11", "2026-12", "2027-01", "2027-02"]


def test_a_dated_catalyst_shows_its_day():
    html = calendar_view.render([_catalyst("2026-08-14")], months=3, today=TODAY)
    assert ">14<" in html


def test_a_month_only_catalyst_shows_no_day():
    """The registry gives 2026-08 and nothing finer, so no day is drawn."""
    html = calendar_view.render([_catalyst("2026-08")], months=3, today=TODAY)
    assert "month only" in html          # the dash is marked, not left ambiguous
    # And never placed on the first: the day slot holds a dash, not a 1.
    assert '<span class="cal-day none" title="month only">—</span>' in html


def test_empty_months_stay_in_the_grid():
    """A quiet run is the shape of a calendar; dropping it would put August next to
    November and lose the gap."""
    html = calendar_view.render([_catalyst("2026-10-02")], months=4, today=TODAY)
    assert html.count("cal-month") == 4
    # Three are empty; the current month carries "now" alongside it.
    assert html.count("empty") == 3
    for month in ("Jul 26", "Aug 26", "Sep 26", "Oct 26"):
        assert month in html


def test_the_current_month_is_marked():
    html = calendar_view.render([_catalyst("2026-08")], months=2, today=TODAY)
    assert "cal-month now" in html


def test_a_catalyst_past_the_grid_is_not_silently_dropped():
    """The fetch window is days and the grid is months, so they do not end together.
    Filtering to the grid keeps the count and the drawing in agreement."""
    items = [_catalyst("2026-08"), _catalyst("2027-11")]
    assert len(calendar_view.within(items, months=12, today=TODAY)) == 1
    assert "11 ahead" not in calendar_view.caption(items, 12, TODAY)
    assert calendar_view.caption(items, 12, TODAY).startswith("1 ahead")


def test_dated_entries_sort_before_month_only_ones_in_a_month():
    html = calendar_view.render(
        [_catalyst("2026-08", title="Month only one"),
         _catalyst("2026-08-03", title="Dated one")], months=2, today=TODAY)
    assert html.index("Dated one") < html.index("Month only one")


def test_the_phase_prefix_is_dropped_from_a_title():
    """The registry prefixes nearly every readout with its phase, which the badge
    already carries, so it is spent twice in a narrow cell."""
    html = calendar_view.render(
        [_catalyst("2026-08-01", title="Phase 3, A Study of Retatrutide")],
        months=2, today=TODAY)
    assert "A Study of Retatrutide" in html
    assert "Phase 3, A Study" not in html


def test_a_long_title_is_truncated_not_wrapped_forever():
    html = calendar_view.render(
        [_catalyst("2026-08-01", title="x" * 200)], months=2, today=TODAY)
    assert "…" in html


def test_nothing_ahead_renders_nothing():
    assert calendar_view.render([], months=6, today=TODAY) == ""
    assert calendar_view.caption([], 6, TODAY) == ""
    assert calendar_view.render([_catalyst("2030-01")], months=6, today=TODAY) == ""


def test_the_caption_counts_the_month_only_dates():
    items = [_catalyst("2026-08"), _catalyst("2026-09-04")]
    caption = calendar_view.caption(items, 6, TODAY)
    assert caption.startswith("2 ahead")
    assert "1 carry a month and no day" in caption


def test_titles_are_escaped():
    html = calendar_view.render(
        [_catalyst("2026-08-01", title="<script>alert(1)</script>")],
        months=2, today=TODAY)
    assert "<script>" not in html
