"""Snapshot diff engine.

Turns consecutive snapshots into rows in the changes table. Runs after the fetchers on
every refresh: it compares each trial's current state to its last per-trial snapshot
(status, primary completion date, phase) and treats a first-seen filing or approval as a
new-item signal. Baselines are per company, not global, so a single-company refresh never
baselines the rest of the universe. A company's first run emits nothing; later runs emit
each change once, since the compared snapshot is advanced when a change is recorded.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import db
import edgar_items

# A first-seen filing or approval only counts as news if it is also recent. Wide enough to
# survive a refresh gap of several months, narrow enough to exclude back catalogue.
# Public because cleanup.py retires old poisoned rows by the same rule; one definition.
RECENCY_DAYS = 180

_HIGH_STATUS = {"Terminated", "Suspended", "Withdrawn"}
_PHASE_RANK = {
    "Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3, "Phase 2/3": 4, "Phase 3": 5, "Phase 4": 6,
}


def _last_snapshot(conn, source, entity_type, entity_key):
    row = conn.execute(
        """
        SELECT payload FROM snapshots
         WHERE source = ? AND entity_type = ? AND entity_key = ?
         ORDER BY captured_at DESC, id DESC LIMIT 1
        """,
        (source, entity_type, entity_key),
    ).fetchone()
    return json.loads(row["payload"]) if row else None


def _write_snapshot(conn, source, entity_type, entity_key, payload, run_id):
    conn.execute(
        """
        INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (source, entity_type, entity_key, json.dumps(payload), run_id),
    )


def _write_change(conn, entity_type, entity_key, field, old, new, change_type, sig, run_id):
    conn.execute(
        """
        INSERT INTO changes
            (entity_type, entity_key, field, old_value, new_value, change_type,
             significance, refresh_run_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (entity_type, entity_key, field, old, new, change_type, sig, run_id),
    )


def _status_significance(status) -> str:
    if status in _HIGH_STATUS:
        return "high"
    if status == "Completed":
        return "medium"
    return "low"


def _diff_trials(conn, run_id) -> int:
    changed = 0
    rows = conn.execute(
        """
        SELECT t.nct_id, t.overall_status, t.primary_completion_date, t.phase, t.title,
               c.ticker
          FROM trials t LEFT JOIN companies c ON t.sponsor_company_id = c.id
        """
    ).fetchall()
    for row in rows:
        key = row["nct_id"]
        current = {
            "overall_status": row["overall_status"],
            "primary_completion_date": row["primary_completion_date"],
            "phase": row["phase"],
        }
        prior = _last_snapshot(conn, "trials", "trial", key)
        payload = {**current, "ticker": row["ticker"], "title": row["title"]}
        if prior is None:  # baseline: newly tracked trial, no signal
            _write_snapshot(conn, "trials", "trial", key, payload, run_id)
            continue

        emitted = False
        if prior.get("overall_status") != current["overall_status"]:
            _write_change(conn, "trial", key, "overall_status",
                          prior.get("overall_status"), current["overall_status"],
                          "status_change", _status_significance(current["overall_status"]),
                          run_id)
            emitted = True
        old_date, new_date = prior.get("primary_completion_date"), current["primary_completion_date"]
        if old_date != new_date and old_date and new_date:
            if new_date > old_date:
                _write_change(conn, "trial", key, "primary_completion_date", old_date,
                              new_date, "date_slip", "medium", run_id)
            else:
                _write_change(conn, "trial", key, "primary_completion_date", old_date,
                              new_date, "date_change", "low", run_id)
            emitted = True
        if prior.get("phase") != current["phase"]:
            old_rank = _PHASE_RANK.get(prior.get("phase"), 0)
            new_rank = _PHASE_RANK.get(current["phase"], 0)
            change_type = "phase_advance" if new_rank > old_rank else "phase_regress"
            sig = "high" if new_rank > old_rank else "medium"
            _write_change(conn, "trial", key, "phase", prior.get("phase"),
                          current["phase"], change_type, sig, run_id)
            emitted = True

        if emitted:
            changed += 1
            _write_snapshot(conn, "trials", "trial", key, payload, run_id)
    return changed


def _baselined_tickers(conn, entity_type) -> set:
    """Tickers this entity type has already been snapshotted for.

    Scoped per company because refreshes are: a single-company refresh must not baseline
    the rest of the universe and turn their back catalogue into news on the next run.
    """
    rows = conn.execute(
        "SELECT DISTINCT json_extract(payload, '$.ticker') AS ticker"
        "  FROM snapshots WHERE entity_type = ?",
        (entity_type,),
    ).fetchall()
    return {r["ticker"] for r in rows}


def is_recent(value, today=None) -> bool:
    """True for an ISO date within the recency window. Missing or unparseable is False.

    ``today`` is injectable so cleanup can ask the question as of when a change was
    detected, rather than as of now.
    """
    if not value:
        return False
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    return parsed >= (today or date.today()) - timedelta(days=RECENCY_DAYS)


def _detect_new(conn, run_id, source, entity_type, rows, change_type, date_field) -> int:
    """First-seen entities (filings, approvals) are the signal, once past the baseline.

    Two gates, both required. A company's first sighting is its baseline and emits
    nothing, so adding a company mid-life does not replay its history. Past that, only
    an item dated inside the recency window is news; an approval from 2008 first seen
    today is a gap in our coverage, not an event.
    """
    baselined = _baselined_tickers(conn, entity_type)
    emitted = 0
    for key, payload, label, significance in rows:
        if _last_snapshot(conn, source, entity_type, key) is not None:
            continue
        if payload.get("ticker") in baselined and is_recent(payload.get(date_field)):
            _write_change(conn, entity_type, key, entity_type, None, label,
                          change_type, significance, run_id)
            emitted += 1
        _write_snapshot(conn, source, entity_type, key, payload, run_id)
    return emitted


def _diff_filings(conn, run_id) -> int:
    rows = conn.execute(
        """
        SELECT f.accession, f.form_type, f.filed_date, f.title, c.ticker
          FROM filings f LEFT JOIN companies c ON f.company_id = c.id
         ORDER BY f.filed_date DESC
        """
    ).fetchall()
    # An 8-K reporting a completed acquisition or a signed material agreement is not
    # the same event as one reporting a shareholder vote, and the item codes say which
    # is which. Material ones rank high so they lead the feed and the note.
    items = [
        (r["accession"],
         {"form_type": r["form_type"], "filed_date": r["filed_date"], "ticker": r["ticker"]},
         f"{r['ticker']} {r['form_type']}: {r['title']}",
         "high" if edgar_items.is_material_title(r["title"])
         else "medium" if r["form_type"] in ("8-K", "6-K") else "low")
        for r in rows
    ]
    return _detect_new(conn, run_id, "filings", "filing", items, "new_filing", "filed_date")


def _diff_approvals(conn, run_id) -> int:
    rows = conn.execute(
        """
        SELECT ap.application_number, ap.approval_date, a.brand_name, c.ticker
          FROM approvals ap JOIN assets a ON ap.asset_id = a.id
          LEFT JOIN companies c ON a.owner_company_id = c.id
        """
    ).fetchall()
    items = [
        (r["application_number"],
         {"approval_date": r["approval_date"], "ticker": r["ticker"]},
         f"{r['ticker']} FDA approval: {r['brand_name']} ({r['application_number']})",
         "high")
        for r in rows
    ]
    return _detect_new(conn, run_id, "approvals", "approval", items, "new_approval",
                       "approval_date")


def detect_changes(db_path=None, run_id=None) -> dict:
    conn = db.get_connection(db_path)
    try:
        summary = {
            "trial_changes": _diff_trials(conn, run_id),
            "new_filings": _diff_filings(conn, run_id),
            "new_approvals": _diff_approvals(conn, run_id),
        }
        conn.commit()
    finally:
        conn.close()
    return summary
