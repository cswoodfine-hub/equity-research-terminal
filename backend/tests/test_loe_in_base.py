"""Whether a loss of exclusivity is already in the reported revenue, and what a moved
LOE does on either side of the base date."""

from __future__ import annotations

import pytest

import forecast as F


def test_a_cliff_before_the_window_takes_its_drop_and_every_year_of_decay():
    """A 2023 cliff on a window opening in 2026 is three years into its curve by then:
    the year-one drop and two years of decay. Stepping from the first year skipped both,
    so the earlier date was worth more than a 2025 one."""
    years = list(range(2026, 2031))
    flat = [100.0] * len(years)
    got = F.erode(flat, years, 2023, 0.6, 0.35)
    assert got[0] == pytest.approx(100.0 * 0.4 * 0.65 ** 2)
    assert got[1] == pytest.approx(100.0 * 0.4 * 0.65 ** 3)
    # The late rate takes over on its own year counted from the cliff, not the window.
    slowed = F.erode(flat, years, 2023, 0.6, 0.35, 0.10, 4)
    assert slowed[0] == pytest.approx(100.0 * 0.4 * 0.65 ** 2)
    assert slowed[1] == pytest.approx(100.0 * 0.4 * 0.65 ** 2 * 0.9)
    # Each year is the same curve whatever year the window opens in.
    longer = F.erode([100.0] * 10, list(range(2021, 2031)), 2023, 0.6, 0.35, 0.10, 4)
    assert longer[5:] == pytest.approx(slowed)


def test_an_earlier_cliff_is_never_worth_more_in_any_year():
    years = list(range(2026, 2046))
    flat = [100.0] * len(years)
    for late, late_from in ((None, None), (0.10, 4)):
        previous = None
        for loe in range(2050, 2005, -1):
            got = F.erode(flat, years, loe, 0.6, 0.35, late, late_from)
            if previous is not None:
                assert all(a <= b + 1e-12 for a, b in zip(got, previous)), loe
            previous = got
