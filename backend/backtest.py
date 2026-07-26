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

# Windows around the event, in trading days relative to the last bar on or before the
# event date. Negative is the run-up into the event, positive is the reaction after it,
# so the study shows both whether a move was anticipated and how it landed. About 21
# trading days to a month, so 63 is the three-month run-up.
WINDOWS = (
    {"key": "runup_3m", "label": "run-up 3mo", "a": -63, "b": 0},
    {"key": "runup_1m", "label": "run-up 1mo", "a": -21, "b": 0},
    {"key": "runup_1w", "label": "run-up 1wk", "a": -5, "b": 0},
    {"key": "after_1d", "label": "after 1d", "a": 0, "b": 1},
    {"key": "after_1w", "label": "after 1wk", "a": 0, "b": 5},
    {"key": "after_1m", "label": "after 1mo", "a": 0, "b": 21},
)
EVENT_TYPES = ("new_approval", "new_filing", "risk_factors_change")


def _series(conn) -> dict:
    """Sorted daily closes per company: {company_id: [(date, close), ...]}."""
    series: dict[int, list] = defaultdict(list)
    for row in conn.execute(
        "SELECT company_id, as_of, close FROM prices"
        " WHERE interval = '1d' AND close IS NOT NULL ORDER BY company_id, as_of"):
        series[row["company_id"]].append((row["as_of"], row["close"]))
    return series


def span_return(series: dict, company_id: int, date: str, a: int, b: int):
    """Return between two bars offset ``a`` and ``b`` trading days from the last bar on or
    before ``date``, or None when either offset runs off the series. a<0 is before the
    event, b>0 is after it, so one function serves the run-up and the reaction."""
    bars = series.get(company_id)
    if not bars:
        return None
    idx = bisect.bisect_right([x[0] for x in bars], date) - 1
    i, j = idx + a, idx + b
    if not (0 <= i < len(bars)) or not (0 <= j < len(bars)):
        return None
    base = bars[i][1]
    return bars[j][1] / base - 1 if base else None


def universe_span(series: dict, date: str, a: int, b: int, exclude: int | None = None):
    """The equal-weight return of the universe over the same window, excluding the event's
    own company so it is a clean benchmark."""
    rets = [span_return(series, cid, date, a, b) for cid in series if cid != exclude]
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

    # change_type -> window key -> list of abnormal returns
    by_type: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for event in events:
        for window in WINDOWS:
            own = span_return(series, event["company_id"], event["date"],
                              window["a"], window["b"])
            market = universe_span(series, event["date"], window["a"], window["b"],
                                   event["company_id"])
            if own is None or market is None:
                continue
            by_type[event["change_type"]][window["key"]].append(own - market)

    rows = []
    for change_type in sorted(by_type):
        windows = {}
        measured = 0
        for window in WINDOWS:
            values = by_type[change_type].get(window["key"], [])
            if values:
                windows[window["key"]] = {
                    "n": len(values),
                    "mean_abnormal": sum(values) / len(values),
                    "hit_rate": sum(1 for v in values if v > 0) / len(values),
                }
                measured = max(measured, len(values))
        if windows:
            rows.append({"change_type": change_type, "n": measured,
                         "windows": windows})

    dates = [e["date"] for e in events]
    return {
        "windows": [{"key": w["key"], "label": w["label"]} for w in WINDOWS],
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
