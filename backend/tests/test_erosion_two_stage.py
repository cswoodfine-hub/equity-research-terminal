"""The post-LOE decay runs in two stages where the modality has a late rate on file."""

from __future__ import annotations

import assumptions
import forecast as F


def test_no_late_rate_reproduces_the_single_rate_exactly():
    """Every seeded shape must be untouched: the second stage only starts where a late
    rate is on file."""
    years = list(range(2026, 2041))
    revenue = [100.0] * len(years)
    assert F.erode(revenue, years, 2030, 0.6, 0.35) == \
        F.erode(revenue, years, 2030, 0.6, 0.35, None, None)
    for rate in (0.05, 0.07, 0.09):
        for decay in (0.0, 0.1, 0.2, 0.35, 0.5):
            for last, loe in ((2035, 2028), (2035, 2035), (2030, 2036)):
                one = F.terminal_multiple(0.0, rate, last, loe, False, 0.25, decay)
                two = F.terminal_multiple(0.0, rate, last, loe, False, 0.25, decay,
                                          late_decay_pct=decay, late_from_year=4)
                assert abs(one - two) < 1e-12, (rate, decay, last, loe)


def test_the_late_rate_takes_over_from_its_year():
    """Years two and three keep the cliff rate, year four onwards slows."""
    years = list(range(2031, 2039))
    got = F.erode([100.0] * len(years), years, 2030, 0.6, 0.35, 0.10, 4)
    assert round(got[0], 6) == 40.0                      # the year-one drop
    assert round(got[1], 6) == round(40.0 * 0.65, 6)     # year two, still steep
    assert round(got[2], 6) == round(40.0 * 0.65 ** 2, 6)  # year three, still steep
    assert round(got[3], 6) == round(40.0 * 0.65 ** 2 * 0.90, 6)   # year four, slowed
    assert round(got[4], 6) == round(40.0 * 0.65 ** 2 * 0.90 ** 2, 6)


def test_a_line_already_gentler_than_the_late_rate_is_never_made_worse():
    """A biologic seeded at 5% does not start falling 10% because a default says so."""
    years = list(range(2031, 2037))
    gentle = F.erode([100.0] * len(years), years, 2030, 0.25, 0.05, 0.10, 4)
    alone = F.erode([100.0] * len(years), years, 2030, 0.25, 0.05)
    assert gentle == alone
    assert F.late_rate(0.05, 0.10) == 0.05


def test_the_terminal_multiple_follows_the_same_two_stages():
    """A product seven years past its cliff is worth more than a perpetual 35% decay
    says, because the fall slows once the generics have taken what they take."""
    steep = F.terminal_multiple(0.0, 0.07, 2035, 2028, False, 0.6, 0.35)
    slowed = F.terminal_multiple(0.0, 0.07, 2035, 2028, False, 0.6, 0.35, 0.10, 4)
    assert round(steep, 4) == 1.5476                       # (1-0.35)/(0.07+0.35)
    assert round(slowed, 4) == round(0.90 / 0.17, 4)       # the late perpetuity alone
    # A cliff that falls after the horizon carries the early years before slowing.
    ahead = F.terminal_multiple(0.0, 0.07, 2030, 2033, False, 0.6, 0.35, 0.10, 4)
    assert ahead > F.terminal_multiple(0.0, 0.07, 2030, 2033, False, 0.6, 0.35)


def test_only_the_small_molecule_default_carries_a_late_rate():
    """The biologic and unknown rows are held deliberately: one observation, and it
    rises. This test is the guard on that decision."""
    rows = assumptions.erosion_defaults()
    assert rows["small molecule"]["late_decay_pct"] == 0.10
    assert rows["small molecule"]["late_from_year"] == 4
    for modality in ("biologic", "unknown", "gene therapy"):
        assert rows[modality].get("late_decay_pct") in (None, ""), modality
