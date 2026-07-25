"""Export and rebuild the app-produced history as newline-delimited JSON.

The differentiator is the accumulated snapshot history, which no source can hand
back once a day is missed. A binary SQLite file diffs badly and bloats a repo, so
the durable off-machine copy is NDJSON: one file per table, one JSON object per
line, ordered by id so a day's new rows append at the end and git stores the delta
cleanly. This is the git-scraping pattern, and it doubles as the backup.

Only the tables the app produces over time are exported. Prices, financials and
current trial state are re-fetchable and left out; the snapshot history that feeds
the diff engine, the detected changes, the catalysts, the notes, the run ledger,
the annotations and the FX rates are not, so those travel.

Rebuild is the inverse: recreate the schema, then load every row back with foreign
keys off, since the export is already internally consistent and the referenced
current-state tables are repopulated by the next refresh.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import db

# Foreign keys point from these toward companies/assets, which are not exported (a
# refresh rebuilds them), so load order does not matter with FK off. Kept as a list
# for a stable, readable export directory.
HISTORY_TABLES = [
    "refresh_runs", "snapshots", "changes", "catalysts", "insights",
    "annotations", "fx_rates",
]

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "history"


def _columns(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def _table_exists(conn, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone() is not None


def export(db_path=None, out_dir: Path | None = None,
           tables: list[str] = None) -> dict:
    """Write each history table to ``out_dir/{table}.ndjson``, rows by id ascending.

    Keys are sorted per line so the text is stable, which keeps the git diff to the
    rows that actually changed. Returns rows written per table.
    """
    out_dir = Path(out_dir) if out_dir else DEFAULT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    tables = tables or HISTORY_TABLES
    conn = db.get_connection(db_path)
    written = {}
    try:
        for table in tables:
            if not _table_exists(conn, table):
                continue
            order = "id" if "id" in _columns(conn, table) else "rowid"
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            path = out_dir / f"{table}.ndjson"
            with path.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps({k: row[k] for k in row.keys()},
                                            sort_keys=True, ensure_ascii=False))
                    handle.write("\n")
            written[table] = len(rows)
    finally:
        conn.close()
    return written


def rebuild(db_path=None, in_dir: Path | None = None,
            tables: list[str] = None) -> dict:
    """Recreate the schema and load every exported row back. Idempotent: a row
    replaces the one with its id, so rebuilding twice is a no-op.

    Foreign keys are off for the load because the export is already consistent and
    the current-state tables it points at are repopulated by the next refresh.
    """
    in_dir = Path(in_dir) if in_dir else DEFAULT_DIR
    tables = tables or HISTORY_TABLES
    path = db.init(db_path)                       # schema + migrations
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    loaded = {}
    try:
        for table in tables:
            source = in_dir / f"{table}.ndjson"
            if not source.exists() or not _table_exists(conn, table):
                continue
            columns = set(_columns(conn, table))
            count = 0
            with source.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    record = {k: v for k, v in json.loads(line).items()
                              if k in columns}
                    cols = ", ".join(record)
                    marks = ", ".join("?" for _ in record)
                    conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})",
                        list(record.values()))
                    count += 1
            loaded[table] = count
        conn.commit()
    finally:
        conn.close()
    return loaded


if __name__ == "__main__":
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "export"
    if action == "rebuild":
        print(json.dumps({"rebuilt": rebuild()}, indent=2))
    else:
        print(json.dumps({"exported": export()}, indent=2))
