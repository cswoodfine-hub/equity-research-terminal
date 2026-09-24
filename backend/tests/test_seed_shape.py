"""Where a seed puts a key decides whether the engine reads it.

The pool identity reads its inputs from an indication's own scalars. A key that belongs to
an indication but is written at asset level is loaded, displayed, and never used. That is
worse than missing, because it looks as though it is doing something.
"""

import csv
import pathlib

import pool_crowding

_SEEDS = pathlib.Path(__file__).resolve().parents[2] / "data" / "assumptions"


def _rows():
    for path in sorted(_SEEDS.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            yield path.name, row


def test_no_seed_writes_a_pool_input_where_the_engine_does_not_read_it():
    """Seven obesity seeds carried their ex-US multiple at asset level. forecast.py and
    pool_crowding.py both read it from the indication, so the working row existed only in
    the database, and a database rebuilt from these files would have dropped the ex-US
    revenue of seven assets without a word."""
    per_indication = set(pool_crowding._PER_INDICATION)
    misplaced = [(name, row["key"]) for name, row in _rows()
                 if row.get("key") in per_indication
                 and not (row.get("indication") or "").strip()]
    assert misplaced == [], misplaced


def test_the_check_covers_the_key_that_was_misplaced():
    """If exus_multiple ever leaves the per-indication list, the guard above goes quiet."""
    assert "exus_multiple" in pool_crowding._PER_INDICATION
