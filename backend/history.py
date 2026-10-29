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
    # The model's calls as made each day (call_log.py): exported so each day's commit is
    # the dated record they are scored against.
    "model_calls", "gate_calls",
    # Every change to an analyst assumption (assumption_log.py). The assumptions table
    # itself reseeds from data/assumptions/*.csv, so the seeds and this ledger together
    # carry the model through a rebuild; the ledger alone carries what the seeds cannot,
    # which is every number edited in the terminal after it was first written.
    "assumption_edits",
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


def _history_last_run(in_dir: Path) -> int | None:
    source = in_dir / "refresh_runs.ndjson"
    if not source.exists():
        return None
    last = None
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                run_id = json.loads(line).get("id")
                if isinstance(run_id, int) and (last is None or run_id > last):
                    last = run_id
    return last


def restore_check(db_path=None, in_dir: Path | None = None) -> dict:
    """Whether a database restored from yesterday's published release can be refreshed
    as it is, rather than rebuilt from the exported history.

    A rebuilt database holds the history tables and nothing else, so every source has to
    fetch in full, and the sources slower than daily (the pharmacology lookups, the drug
    codes, the Part D readers) took the daily run from 20 minutes to over an hour from
    2026-10-08. A restored one holds their data, so their TTLs can hold.

    Accepted only when it is the release the last committed run produced, or a later one:
    it opens, passes SQLite's quick check, and its latest refresh run is at least the
    latest in the committed history. A later one is the 2026-10-26 case, a release that
    went out when the history push failed, and the rebuild that follows merges the
    committed rows into it without losing its own. Anything else is removed, so the
    rebuild starts clean and the run fetches every source, as it did before.
    """
    path = Path(db_path if db_path is not None else db.DB_PATH)
    in_dir = Path(in_dir) if in_dir else DEFAULT_DIR
    expected = _history_last_run(in_dir)

    def refuse(why: str) -> dict:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
        return {"restored": False, "why": why, "history_last_run": expected}

    if not path.exists():
        return {"restored": False, "why": "no database was restored",
                "history_last_run": expected}
    try:
        conn = sqlite3.connect(path)
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()[0]
            last = conn.execute("SELECT MAX(id) FROM refresh_runs").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return refuse(f"the restored file does not open as a database: {exc}")
    if check != "ok":
        return refuse(f"the restored database fails its integrity check: {check}")
    if last is None:
        return refuse("the restored database records no refresh run")
    if expected is not None and last < expected:
        return refuse(f"the restored database stops at run {last}, before the committed "
                      f"history's run {expected}")
    return {"restored": True, "why": f"restored at run {last}",
            "history_last_run": expected}


if __name__ == "__main__":
    import sys

    action = sys.argv[1] if len(sys.argv) > 1 else "export"
    if action == "rebuild":
        print(json.dumps({"rebuilt": rebuild()}, indent=2))
    elif action == "restore-check":
        # Exit 0 when the restored database stands, 3 when it was refused or absent, so
        # the workflow can choose the fetch mode on the exit code alone.
        verdict = restore_check()
        print(json.dumps(verdict, indent=2))
        sys.exit(0 if verdict["restored"] else 3)
    else:
        print(json.dumps({"exported": export()}, indent=2))
