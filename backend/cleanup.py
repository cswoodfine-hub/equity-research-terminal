"""Retire change rows poisoned by the global-baseline defect in the diff engine.

Before the per-company baseline fix, a single-company refresh flipped a global flag and
the next full run reported every other company's back catalogue as new_approval and
new_filing. Those rows are still in the database, and any note built over them cites
them as evidence. This retires them.

The test is the recency rule from ``diff``, asked as of the day the change was detected
rather than today: a first-seen approval or filing dated more than ``RECENCY_DAYS``
before its own detection was never news. Judging by detected_at, not now, is what keeps
legitimately-recorded history intact. The run against the development database found 9
of the 625 rows to be genuine recent approvals, so a blanket delete of the change type
would have destroyed real signal.

Rows whose underlying date cannot be established are reported and kept. Never delete
what you cannot show to be wrong.

    python -m cleanup                # dry run, prints what would go
    python -m cleanup --apply        # back up the file, then delete
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import db
import diff

# change_type -> (snapshot source, snapshot entity_type, date field, current-state SQL)
_AFFECTED = {
    "new_approval": (
        "approvals", "approval", "approval_date",
        "SELECT approval_date AS d FROM approvals WHERE application_number = ?",
    ),
    "new_filing": (
        "filings", "filing", "filed_date",
        "SELECT filed_date AS d FROM filings WHERE accession = ?",
    ),
}


def _item_date(conn, change) -> str | None:
    """The approval or filing date behind a change row, or None if unestablished.

    Prefers the snapshot written by the run that emitted the change: snapshots are
    append-only, so they hold the date as it was seen, where the current-state table may
    have been rewritten by a later upsert.
    """
    source, entity_type, date_field, fallback_sql = _AFFECTED[change["change_type"]]
    snap = conn.execute(
        """
        SELECT payload FROM snapshots
         WHERE source = ? AND entity_type = ? AND entity_key = ?
         ORDER BY captured_at ASC, id ASC LIMIT 1
        """,
        (source, entity_type, change["entity_key"]),
    ).fetchone()
    if snap:
        value = json.loads(snap["payload"]).get(date_field)
        if value:
            return value
    row = conn.execute(fallback_sql, (change["entity_key"],)).fetchone()
    return row["d"] if row else None


def find_poisoned(conn) -> tuple[list[dict], list[dict]]:
    """Split the affected change rows into (poisoned, undeterminable).

    Anything not returned in either list is judged legitimate and left alone.
    """
    poisoned, undeterminable = [], []
    rows = conn.execute(
        "SELECT id, entity_key, change_type, new_value, detected_at FROM changes"
        "  WHERE change_type IN (?, ?) ORDER BY id",
        tuple(_AFFECTED),
    ).fetchall()
    for row in rows:
        item_date = _item_date(conn, row)
        record = {**dict(row), "item_date": item_date}
        if not item_date:
            undeterminable.append(record)
        elif not diff.is_recent(item_date, today=date.fromisoformat(row["detected_at"][:10])):
            poisoned.append(record)
    return poisoned, undeterminable


def _affected_insights(conn, poisoned_ids: set) -> list[dict]:
    """Notes citing at least one poisoned change.

    A note is prose generated over its evidence, so it cannot be corrected by editing the
    id list. The whole note goes and the next refresh writes a clean one.
    """
    out = []
    for row in conn.execute(
        "SELECT i.id, i.source_change_ids, c.ticker FROM insights i"
        "  LEFT JOIN companies c ON i.company_id = c.id ORDER BY i.id"
    ).fetchall():
        cited = set(json.loads(row["source_change_ids"] or "[]"))
        hit = cited & poisoned_ids
        if hit:
            out.append({"id": row["id"], "ticker": row["ticker"],
                        "cited": len(cited), "poisoned": len(hit)})
    return out


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_suffix(path.suffix + f".backup-{stamp}")
    shutil.copy2(path, dest)
    return dest


def clean(db_path=None, apply: bool = False) -> dict:
    """Report poisoned rows, and delete them when ``apply`` is set."""
    path = Path(db_path) if db_path is not None else db.DB_PATH
    conn = db.get_connection(path)
    try:
        poisoned, undeterminable = find_poisoned(conn)
        poisoned_ids = {r["id"] for r in poisoned}
        insights = _affected_insights(conn, poisoned_ids)

        report = {
            "database": str(path),
            "poisoned_changes": poisoned,
            "undeterminable_changes": undeterminable,
            "affected_insights": insights,
            "applied": False,
            "backup": None,
        }
        if not apply or not poisoned_ids:
            return report

        report["backup"] = str(_backup(path))
        marks = ",".join("?" * len(poisoned_ids))
        ids = tuple(poisoned_ids)
        conn.execute(f"DELETE FROM changes WHERE id IN ({marks})", ids)
        if insights:
            note_marks = ",".join("?" * len(insights))
            conn.execute(f"DELETE FROM insights WHERE id IN ({note_marks})",
                         tuple(n["id"] for n in insights))
        conn.commit()
        report["applied"] = True
        return report
    finally:
        conn.close()


def _print(report: dict) -> None:
    poisoned = report["poisoned_changes"]
    print(f"database: {report['database']}")
    if not poisoned:
        print("no poisoned rows found.")
    else:
        by_type: dict[str, int] = {}
        for row in poisoned:
            by_type[row["change_type"]] = by_type.get(row["change_type"], 0) + 1
        print(f"poisoned changes: {len(poisoned)}")
        for change_type, count in sorted(by_type.items()):
            print(f"  {change_type}: {count}")
        for row in poisoned[:5]:
            print(f"    e.g. [{row['id']}] {row['item_date']} {row['new_value']}")
        if len(poisoned) > 5:
            print(f"    ... and {len(poisoned) - 5} more")
    if report["undeterminable_changes"]:
        print(f"undeterminable, kept: {len(report['undeterminable_changes'])}")
    for note in report["affected_insights"]:
        print(f"note {note['id']} ({note['ticker']}): "
              f"{note['poisoned']} of {note['cited']} cited changes poisoned, will be deleted")
    if report["applied"]:
        print(f"deleted. backup at {report['backup']}")
    elif poisoned:
        print("dry run, nothing written. re-run with --apply to delete.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="delete the rows. without this the run only reports.")
    parser.add_argument("--db", default=None, help="database path, defaults to ER_TOOL_DB")
    args = parser.parse_args(argv)
    _print(clean(args.db, apply=args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
