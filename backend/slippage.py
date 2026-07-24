"""Slippage tracker: how far each trial's primary completion has moved.

Derived entirely from our own snapshot history: the diff engine writes a changes
row every time a registry completion date moves, and this module folds those rows
into per-trial totals and per-company summaries. That series accumulates from
refreshes and cannot be bought after the fact, which is why it gets a view.

A positive move is a slip (later), a negative one a pull-in (earlier). Days are
summed from the first observed date to the current one, so two 30-day slips read
as 60 days moved, and a slip that later reverts reads as zero net.
"""

from __future__ import annotations

import datetime as dt
import statistics

import db

_DATE_MOVE_TYPES = ("date_slip", "date_change")


def _parse(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def build(db_path=None, ticker: str | None = None) -> dict:
    """Per-trial net day moves plus per-company medians.

    Trials are joined for their current phase, status, and title; a company filter
    narrows the rows but the summary always reports the filtered set, so the two
    cannot disagree.
    """
    conn = db.get_connection(db_path)
    try:
        marks = ",".join("?" * len(_DATE_MOVE_TYPES))
        rows = conn.execute(
            f"""
            SELECT ch.entity_key AS nct_id, ch.old_value, ch.new_value,
                   ch.detected_at,
                   t.title, t.phase, t.overall_status, c.ticker
              FROM changes ch
              LEFT JOIN trials t ON t.nct_id = ch.entity_key
              LEFT JOIN companies c ON c.id = t.sponsor_company_id
             WHERE ch.entity_type = 'trial'
               AND ch.field = 'primary_completion_date'
               AND ch.change_type IN ({marks})
             ORDER BY ch.entity_key, ch.detected_at, ch.id
            """,
            _DATE_MOVE_TYPES,
        ).fetchall()
    finally:
        conn.close()

    trials: dict[str, dict] = {}
    for r in rows:
        if ticker and (r["ticker"] or "").upper() != ticker.upper():
            continue
        first_old = _parse(r["old_value"])
        new = _parse(r["new_value"])
        entry = trials.setdefault(r["nct_id"], {
            "nct_id": r["nct_id"], "ticker": r["ticker"], "title": r["title"],
            "phase": r["phase"], "overall_status": r["overall_status"],
            "first_date": r["old_value"], "current_date": r["new_value"],
            "_first": first_old, "_current": new, "observations": 0,
        })
        entry["observations"] += 1
        entry["current_date"] = r["new_value"]
        entry["_current"] = new

    out_rows = []
    for entry in trials.values():
        first, current = entry.pop("_first"), entry.pop("_current")
        entry["days_moved"] = ((current - first).days
                               if first and current else None)
        out_rows.append(entry)
    out_rows.sort(key=lambda e: -(abs(e["days_moved"] or 0)))

    by_company: dict[str, list[int]] = {}
    for entry in out_rows:
        if entry["days_moved"] is None or not entry["ticker"]:
            continue
        by_company.setdefault(entry["ticker"], []).append(entry["days_moved"])
    summary = [{
        "ticker": tk,
        "trials_moved": len(moves),
        "median_days": statistics.median(moves),
        "slipped": sum(1 for m in moves if m > 0),
        "pulled_in": sum(1 for m in moves if m < 0),
    } for tk, moves in sorted(by_company.items())]

    return {"rows": out_rows, "summary": summary, "ticker": ticker}
