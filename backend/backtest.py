"""Backtest: did the change signals lead price moves?

The snapshot engine records a change when it first sees one. That is the point of
keeping the history: over time it becomes a labelled set of events whose worth can be
measured against what the stock actually did. This replays that set. For each change
with a real event date, it takes the stock's forward return over one day, one week and
one month, subtracts the equal-weight return of the rest of the universe over the same
window so a sector-wide move does not read as signal, and aggregates the abnormal return
and the hit rate by change type.

Only changes with a real event date are measured. An FDA approval and a filing carry
their own date, which may sit years before we first saw them, and the five-year daily
series covers it. A trial status or completion-date change has no such date, only our
detection time, and there is no forward window after that yet, so those are left out and
said to be, rather than measured against a date that is not the event.

Small by construction: a young install has tens of events, not thousands, so this reads
as a direction and a hit rate, not a p-value, and the view says so.
"""

from __future__ import annotations

import bisect
from collections import defaultdict

import db

HORIZONS = (1, 5, 21)                 # trading days: about a day, a week, a month
EVENT_TYPES = ("new_approval", "new_filing", "risk_factors_change")


def _series(conn) -> dict:
    """Sorted daily closes per company: {company_id: [(date, close), ...]}."""
    series: dict[int, list] = defaultdict(list)
    for row in conn.execute(
        "SELECT company_id, as_of, close FROM prices"
        " WHERE interval = '1d' AND close IS NOT NULL ORDER BY company_id, as_of"):
        series[row["company_id"]].append((row["as_of"], row["close"]))
    return series


def forward_return(series: dict, company_id: int, date: str, horizon: int):
    """Return from the last bar on or before ``date`` to ``horizon`` bars later, or None
    when the window runs off either end of the series."""
    bars = series.get(company_id)
    if not bars:
        return None
    idx = bisect.bisect_right([b[0] for b in bars], date) - 1
    if idx < 0 or idx + horizon >= len(bars):
        return None
    entry, exit_ = bars[idx][1], bars[idx + horizon][1]
    return exit_ / entry - 1 if entry else None


def universe_return(series: dict, date: str, horizon: int, exclude: int | None = None):
    """The equal-weight forward return of the universe over the same window, excluding the
    event's own company so it is a clean benchmark."""
    rets = [forward_return(series, cid, date, horizon)
            for cid in series if cid != exclude]
    rets = [r for r in rets if r is not None]
    return sum(rets) / len(rets) if rets else None


def _events(conn) -> list[dict]:
    """Changes resolved to a company and a real event date, dropping those without one."""
    out = []
    for change in conn.execute(
        "SELECT entity_key, change_type, significance FROM changes"):
        ct = change["change_type"]
        if ct == "new_approval":
            row = conn.execute(
                "SELECT a.owner_company_id AS cid, ap.approval_date AS d FROM approvals ap"
                " JOIN assets a ON a.id = ap.asset_id WHERE ap.application_number = ?",
                (change["entity_key"],)).fetchone()
        elif ct in ("new_filing", "risk_factors_change"):
            row = conn.execute(
                "SELECT company_id AS cid, filed_date AS d FROM filings WHERE accession = ?",
                (change["entity_key"],)).fetchone()
        else:
            row = None
        if row and row["cid"] and row["d"]:
            out.append({"company_id": row["cid"], "date": row["d"],
                        "change_type": ct, "significance": change["significance"]})
    return out


def build(db_path=None) -> dict:
    conn = db.get_connection(db_path)
    try:
        series = _series(conn)
        events = _events(conn)
    finally:
        conn.close()

    # change_type -> horizon -> list of abnormal returns
    by_type: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for event in events:
        for horizon in HORIZONS:
            own = forward_return(series, event["company_id"], event["date"], horizon)
            market = universe_return(series, event["date"], horizon, event["company_id"])
            if own is None or market is None:
                continue
            by_type[event["change_type"]][horizon].append(own - market)

    rows = []
    for change_type in sorted(by_type):
        horizons = {}
        measured = 0
        for horizon in HORIZONS:
            values = by_type[change_type].get(horizon, [])
            if values:
                horizons[horizon] = {
                    "n": len(values),
                    "mean_abnormal": sum(values) / len(values),
                    "hit_rate": sum(1 for v in values if v > 0) / len(values),
                }
                measured = max(measured, len(values))
        if horizons:
            rows.append({"change_type": change_type, "n": measured,
                         "horizons": horizons})

    dates = [e["date"] for e in events]
    return {
        "horizons": list(HORIZONS),
        "rows": rows,
        "measured_events": len(events),
        "total_changes": _count_changes(db_path),
        "event_date_min": min(dates) if dates else None,
        "event_date_max": max(dates) if dates else None,
    }


def _count_changes(db_path) -> int:
    conn = db.get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    finally:
        conn.close()
