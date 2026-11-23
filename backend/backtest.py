"""Backtest: did the change signals lead price moves?

Every window is measured against XBI (``benchmark_series`` says why), with the book's
own universe only as a stated fallback where XBI's series does not reach.

The snapshot engine records a change when it first sees one. That is the point of
keeping the history: over time it becomes a labelled set of events whose worth can be
measured against what the stock actually did. This replays that set. For each change
with a real event date, it takes the stock's forward return over one day, one week and
one month, subtracts the equal-weight return of the rest of the universe over the same
window so a sector-wide move does not read as signal, and aggregates the abnormal return
and the hit rate by change type.

Where the news sits among the closes is decided by ``market_session.news_window``: the
run-up ends at the last close before the news could have been known, the reaction runs
from that close to the first close by which the market had certainly had it, and the
windows after are counted from there. Measured from the event day's own close, as this
was until 2026-11-23, a result released before the open had its reaction counted as
run-up.

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

import benchmark_series
import db
import market_session

# Windows around the event, in trading days. A run-up ends at the last close before the
# news. The reaction runs from that close for as many sessions as the news needs to be
# certainly in the price (one or two; market_session.news_window). A window after is
# counted from the end of the reaction, so it is what was left for somebody who bought
# once the news was out. About 21 trading days to a month, so 63 is the three-month
# run-up. The keys are the ones the views and the desk tools already read.
WINDOWS = (
    {"key": "runup_3m", "label": "run-up 3mo", "kind": "runup", "days": 63},
    {"key": "runup_1m", "label": "run-up 1mo", "kind": "runup", "days": 21},
    {"key": "runup_1w", "label": "run-up 1wk", "kind": "runup", "days": 5},
    {"key": "after_1d", "label": "reaction", "kind": "reaction", "days": 0},
    {"key": "after_1w", "label": "1wk after it", "kind": "after", "days": 5},
    {"key": "after_1m", "label": "1mo after it", "kind": "after", "days": 21},
)


def offsets(window: dict, sessions: int) -> tuple:
    """(a, b) in bars from the last close before the news, for one window of an event
    whose reaction takes ``sessions`` sessions."""
    if window["kind"] == "runup":
        return -window["days"], 0
    if window["kind"] == "reaction":
        return 0, sessions
    return sessions, sessions + window["days"]
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
    """Changes resolved to a company and a real event date, dropping those without one,
    plus the classified Phase 2/3 trial readouts, each a signed event on its filing date."""
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
                "SELECT company_id AS cid, filed_date AS d, accepted_at AS t"
                "  FROM filings WHERE accession = ?", (change["entity_key"],)).fetchone()
        else:
            row = None
        if row and row["cid"] and row["d"]:
            out.append({"company_id": row["cid"], "date": row["d"],
                        "accepted_at": row["t"] if "t" in row.keys() else None,
                        "change_type": ct, "significance": change["significance"]})
    # A readout's type carries its phase and sign, so the study splits into Phase 2 and
    # Phase 3, positive and negative, on its own.
    # The time comes from the filing the readout was read out of, where there is one; a
    # readout read from a press page or the registry has a date and no time.
    for r in conn.execute(
        "SELECT r.company_id, r.event_date, r.phase, r.outcome, f.accepted_at"
        "  FROM trial_readouts r LEFT JOIN filings f ON f.accession = r.accession"
        " WHERE r.outcome IN ('positive', 'negative')"):
        out.append({"company_id": r["company_id"], "date": r["event_date"],
                    "accepted_at": r["accepted_at"],
                    "change_type": f"phase{r['phase']}_{r['outcome']}",
                    "significance": "high"})
    return out


def build(db_path=None) -> dict:
    conn = db.get_connection(db_path)
    try:
        series = _series(conn)
        bars = benchmark_series.series(conn, benchmark_series.BENCHMARK)
        events = _events(conn)
    finally:
        conn.close()

    # change_type -> window key -> list of abnormal returns
    by_type: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    timing: dict[str, dict] = defaultdict(lambda: {"timed": 0, "date only": 0})
    for event in events:
        news = market_session.news_window(event["date"], event.get("accepted_at"))
        if news is None:
            continue
        timing[event["change_type"]][news["basis"]] += 1
        for window in WINDOWS:
            a, b = offsets(window, news["sessions"])
            own = span_return(series, event["company_id"], news["anchor"], a, b)
            # XBI where it covers the window, the book's own universe only where it does
            # not, and the result says which: the universe is a benchmark almost anything
            # beats (benchmark_series), so a figure against it is not the same claim.
            market = benchmark_series.span(bars, news["anchor"], a, b)
            if market is None:
                market = universe_span(series, news["anchor"], a, b,
                                       exclude=event["company_id"])
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
                         "windows": windows,
                         # How many events had a filing time and how many a date alone,
                         # since the second kind is given a two-session reaction.
                         "timing": dict(timing[change_type])})

    dates = [e["date"] for e in events]
    return {
        "windows": [{"key": w["key"], "label": w["label"]} for w in WINDOWS],
        "rows": rows,
        "measured_events": len(events),
        "total_changes": _count_changes(db_path),
        "event_date_min": min(dates) if dates else None,
        "event_date_max": max(dates) if dates else None,
        "reading": ("a run-up ends at the last close before the news; the reaction runs "
                    "from that close for one session where the filing was accepted "
                    "before the New York close, and two where it was accepted after it "
                    "or only a date is on file; the windows after are counted from the "
                    "end of the reaction"),
    }


def _count_changes(db_path) -> int:
    conn = db.get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
    finally:
        conn.close()
