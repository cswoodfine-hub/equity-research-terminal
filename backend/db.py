"""SQLite connection and schema initialisation.

The database is built from the canonical ``schema.sql``. ``init()`` is idempotent:
running it twice does not error and does not drop data. Paths resolve from this
file's location so the module works regardless of the current directory.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BACKEND_DIR / "schema.sql"
DB_PATH = Path(os.getenv("ER_TOOL_DB", str(BACKEND_DIR / "er_tool.db")))


def _make_idempotent(sql: str) -> str:
    """Rewrite ``CREATE TABLE``/``CREATE INDEX`` to ``... IF NOT EXISTS ...``.

    The committed schema uses bare ``CREATE`` statements so it stays clean and
    portable. Rewriting at load time lets ``init()`` run repeatedly without error
    while leaving ``schema.sql`` untouched.
    """
    sql = re.sub(
        r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE TABLE IF NOT EXISTS ",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"CREATE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE INDEX IF NOT EXISTS ",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open a connection with foreign keys on and row access by column name."""
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(db_path: str | Path | None = None) -> Path:
    """Create the database and all tables from ``schema.sql``. Safe to re-run.

    Returns the path to the database file.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    schema_sql = _make_idempotent(SCHEMA_PATH.read_text())
    conn = get_connection(path)
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()
    return path


if __name__ == "__main__":
    created = init()
    print(f"Initialised database at {created}")
