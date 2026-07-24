"""Time machine: the tracked state of the universe as of a past date.

Read-only reconstruction from the snapshots table, which is append-only and
therefore already a full history. Trials are the entity snapshotted at item
grain (one payload per NCT id per capture), so their state reconstructs field
by field; filings and approvals reconstruct as what-was-known-by-then counts.

Nothing here writes. The one honesty rule: a date before the first snapshot has
no state to show, and says so rather than showing an empty universe as though
nothing existed.
"""

from __future__ import annotations

import datetime as dt
import json

import db


def state_at(db_path=None, as_of: str = "") -> dict | None:
    """The reconstructed state at end of ``as_of`` (ISO date), or None when the
    date does not parse."""
    try:
        when = dt.date.fromisoformat(str(as_of)[:10])
    except (ValueError, TypeError):
        return None
    cutoff = when.isoformat() + " 23:59:59"

    conn = db.get_connection(db_path)
    try:
        first = conn.execute("SELECT MIN(captured_at) FROM snapshots").fetchone()[0]
        # Latest snapshot per trial at or before the cutoff. The self-join takes
        # the max capture time per key; ties collapse in the dict below.
        rows = conn.execute(
            """
            SELECT s.entity_key, s.payload, s.captured_at
              FROM snapshots s
              JOIN (SELECT entity_key, MAX(captured_at) AS latest
                      FROM snapshots
                     WHERE entity_type = 'trial' AND captured_at <= ?
                     GROUP BY entity_key) last
                ON last.entity_key = s.entity_key AND last.latest = s.captured_at
             WHERE s.entity_type = 'trial'
            """,
            (cutoff,),
        ).fetchall()
        known = {
            entity_type: dict(conn.execute(
                """
                SELECT json_extract(payload, '$.ticker') AS ticker, COUNT(DISTINCT entity_key)
                  FROM snapshots
                 WHERE entity_type = ? AND captured_at <= ?
                 GROUP BY 1
                """,
                (entity_type, cutoff),
            ).fetchall())
            for entity_type in ("filing", "approval")
        }
    finally:
        conn.close()

    trials: dict[str, dict] = {}
    for row in rows:
        payload = json.loads(row["payload"])
        trials[row["entity_key"]] = {
            "nct_id": row["entity_key"],
            "ticker": payload.get("ticker"),
            "title": payload.get("title"),
            "phase": payload.get("phase"),
            "overall_status": payload.get("overall_status"),
            "primary_completion_date": payload.get("primary_completion_date"),
            "captured_at": row["captured_at"],
        }

    by_ticker: dict[str, dict] = {}
    for trial in trials.values():
        ticker = trial["ticker"] or "unmapped"
        entry = by_ticker.setdefault(ticker, {"trials": 0, "statuses": {}})
        entry["trials"] += 1
        status = trial["overall_status"] or "unknown"
        entry["statuses"][status] = entry["statuses"].get(status, 0) + 1
    for entity_type, counts in known.items():
        for ticker, count in counts.items():
            if ticker:
                by_ticker.setdefault(ticker, {"trials": 0, "statuses": {}})[
                    f"{entity_type}s_known"] = count

    return {
        "as_of": when.isoformat(),
        "history_begins": first,
        "before_history": bool(first) and when.isoformat() < first[:10],
        "trials": sorted(trials.values(), key=lambda t: t["nct_id"]),
        "by_ticker": by_ticker,
    }
