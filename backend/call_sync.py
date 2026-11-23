"""Bring this book's call log up to the committed record, and never past it.

The calls are recorded in one place. ``scheduled_refresh`` values every company once a
day on the scheduled run and writes what it found to ``model_calls`` and ``gate_calls``;
the workflow commits both to data/history, and that commit is the dated record the calls
are later scored against. A refresh started from the terminal does not record calls, on
purpose: two books valuing the same day from different data would be two records of one
day, and a record that is scored has to have one writer.

The cost of that rule was a quiet one. A book on an analyst's machine holds the calls it
was restored with and none since, so every view built on them, the gate odds above all,
went on showing the day of the restore. On 2026-11-23 the terminal was reading odds from
8 November: Dyne's Phase 3 at 94% implied, on a price fifteen per cent above the one on
the screen beside it. The days in between were already on disk, in the history files a
``git pull`` had brought down, and nothing read them.

This reads them. It appends to each table the rows the history file holds beyond the
last one the book has, and that is all it does: no row already in the book is changed
and none is removed.

It refuses rather than guesses. The history file is only a continuation of the book if
the book's last row is in it, at the same place and about the same thing, so the last
row's id is looked up in the file and its key compared (the day and the company, and for
a gate the catalyst). Where the book is ahead of the file, or the two disagree about that
row, the book and the record have parted company, which is a thing for a person to look
at and not for a loader to paper over. Nothing is appended to that table and the reason
is returned.

Only the two call tables. ``valuation_snapshots`` and ``catalyst_resolutions`` travel in
data/history too, and a local refresh writes to both, so the same ids hold different
rows in the two books (204 of 245 resolutions differed on the day this was written).
Appending to those would interleave two histories.

Run at API start (``main.lifespan``), so a pull followed by a restart is enough, and by
hand with ``python backend/call_sync.py``. Off where the call log is off
(``ER_TOOL_CALL_LOG=0``, which the test suite sets).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import call_log
import db
import history

# The table, and what makes a row the same call in two books.
TABLES = (
    ("model_calls", ("as_of", "ticker")),
    ("gate_calls", ("as_of", "ticker", "catalyst_id")),
)


def _file_rows(path: Path) -> list:
    """The file's rows in id order. A line that does not parse or carries no id is left
    out: it could not be placed, and the alignment check decides whether what remains
    still continues the book."""
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row.get("id"), int):
                rows.append(row)
    rows.sort(key=lambda r: r["id"])
    return rows


def _catch_up(conn, table: str, key: tuple, path: Path) -> dict:
    if not path.exists():
        return {"appended": 0, "reason": f"no {path.name} to read"}
    try:
        columns = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        last = conn.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError as exc:
        return {"appended": 0, "refused": f"{table} could not be read: {exc}"}
    if not columns:
        return {"appended": 0, "refused": f"this book has no {table} table"}
    rows = _file_rows(path)
    if not rows:
        return {"appended": 0, "reason": f"{path.name} holds no rows"}

    top = last["id"] if last is not None else 0
    if last is not None:
        match = next((r for r in rows if r["id"] == top), None)
        if match is None:
            return {"appended": 0, "refused": (
                f"this book's last {table} row (id {top}, {last['as_of']}) is not in "
                f"{path.name}, whose last is id {rows[-1]['id']}: the book has calls the "
                "committed record does not")}
        mine = tuple(last[k] for k in key)
        theirs = tuple(match.get(k) for k in key)
        if mine != theirs:
            return {"appended": 0, "refused": (
                f"this book and {path.name} disagree about {table} row {top}: "
                f"{dict(zip(key, mine))} here, {dict(zip(key, theirs))} in the file")}

    new = [r for r in rows if r["id"] > top]
    if not new:
        return {"appended": 0, "through": last["as_of"] if last is not None else None}
    try:
        for row in new:
            record = {k: v for k, v in row.items() if k in columns}
            conn.execute(
                f"INSERT INTO {table} ({', '.join(record)})"
                f" VALUES ({', '.join('?' for _ in record)})", list(record.values()))
    except sqlite3.IntegrityError as exc:
        # A row the file adds collides with one the book already holds under another
        # id. The whole table's append is undone: half a day's calls is worse than none.
        conn.rollback()
        return {"appended": 0, "refused": f"{table}: a row in {path.name} collides with "
                                           f"one already in the book ({exc})"}
    conn.commit()
    return {"appended": len(new), "from": new[0].get("as_of"),
            "through": new[-1].get("as_of")}


def catch_up(db_path=None, in_dir: Path | None = None) -> dict:
    """{table: what happened} for the two call tables. Never raises on a table it cannot
    bring up to date; the reason is in the result."""
    if not call_log.enabled():
        return {"off": "the call log is switched off (ER_TOOL_CALL_LOG=0)"}
    in_dir = Path(in_dir) if in_dir else history.DEFAULT_DIR
    out = {}
    conn = db.get_connection(db_path)
    try:
        for table, key in TABLES:
            out[table] = _catch_up(conn, table, key, in_dir / f"{table}.ndjson")
    finally:
        conn.close()
    return out


def sentence(result: dict) -> str:
    """The result in a line, for the API's start-up log."""
    if "off" in result:
        return result["off"]
    parts = []
    for table, got in result.items():
        if got.get("refused"):
            parts.append(f"{table} not synced: {got['refused']}")
        elif got.get("appended"):
            parts.append(f"{table} +{got['appended']} rows, {got['from']} to {got['through']}")
        else:
            parts.append(f"{table} already current"
                         + (f" ({got['through']})" if got.get("through") else ""))
    return "; ".join(parts)


if __name__ == "__main__":
    print(sentence(catch_up()))
