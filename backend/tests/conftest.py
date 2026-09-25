"""Fixtures shared across the suite."""

import os
import sqlite3

# Tests rewrite modules and databases between two reads in ways no stamp can see, so the
# API's response cache is off for the suite; its own tests switch it back on.
os.environ.setdefault("ER_TOOL_CACHE", "0")

import pytest

import db


@pytest.fixture
def book():
    """A connection to the built database, for the guards that check a curated file
    against the book itself: every disease name reaches an indication, no two assets
    disagree about a prevalence.

    Those facts live only in a database a refresh has built. A checkout that has never
    run one has no book, and opening the default path would create an empty file and
    fail on the first table, so the guard is skipped with the reason instead. The same
    convention as the UI tests that need the API up.
    """
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    conn = db.get_connection()
    try:
        built = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    except sqlite3.OperationalError:
        built = 0
    if not built:
        conn.close()
        pytest.skip(f"the database at {db.DB_PATH} has not been built")
    yield conn
    conn.close()
