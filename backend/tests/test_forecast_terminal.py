"""The terminal value reads the growth rate the seeds actually carry.

Every seed writes ``terminal_growth_pct``, the same key the revenue fade reads, and the
terminal block read ``terminal_growth``. Only one row in the whole book used the shorter
name, so a line seeded to grow past the horizon was capitalised at nil instead. J&J's
Abiomed and SURGICAL are the two seeded at 2.32%, on the reasoning that a device business
renews itself, and they were the only lines in the book that lost anything by it.
"""

from __future__ import annotations

from tests.test_forecast import casgevy_inputs

import forecast as F


def _value(**scalars):
    inputs = casgevy_inputs(scalars=scalars)
    return F.build(inputs)["rnpv"]


def test_terminal_growth_pct_reaches_the_terminal_value():
    """The key the seeds write moves the value; before the fix it was ignored."""
    flat = _value(terminal_growth_pct=0.0)
    growing = _value(terminal_growth_pct=0.0232)
    assert growing > flat, "a growing perpetuity must be worth more than a flat one"


def test_the_older_key_still_works_where_a_row_uses_it():
    """One row in the book carries the short name, so it stays a fallback."""
    assert _value(terminal_growth=0.0232) > _value(terminal_growth=0.0)


def test_the_seeded_key_wins_over_the_older_one():
    """Where both are present the seeds' own key decides, so a row that was restated
    is not overridden by a stale short-name value sitting beside it."""
    both = _value(terminal_growth=0.0, terminal_growth_pct=0.0232)
    assert both == _value(terminal_growth_pct=0.0232)
    assert both > _value(terminal_growth_pct=0.0, terminal_growth=0.0232)
