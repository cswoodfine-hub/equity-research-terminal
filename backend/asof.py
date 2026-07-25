"""Time machine: the tracked state of the universe as of a past date.

Read-only reconstruction from the snapshots table, which is append-only and
therefore already a full history. Three entities reconstruct at field grain:

- trials, from the per-trial snapshots the diff engine writes (status, phase,
  primary completion date as they stood then);
- financials, from the per-company financial snapshot in force at the date
  (revenue, net income, R&D, currency);
- approvals, as the set whose first snapshot is at or before the date, joined to
  the current brand for a readable label.

Nothing here writes. A date before the first snapshot has no state to show and
says so rather than presenting an empty universe as though nothing existed.
"""

from __future__ import annotations

import datetime as dt
import json

import db


def _latest_per_key(conn, entity_type: str, cutoff: str, source: str = None):
    """The newest snapshot at or before ``cutoff`` for each entity_key. The subquery
    takes the max capture time per key; the join reads that row's payload."""
    source_clause = "AND s.source = :source" if source else ""
    inner_source = "AND source = :source" if source else ""
    return conn.execute(
        f"""
        SELECT s.entity_key, s.payload, s.captured_at
          FROM snapshots s
          JOIN (SELECT entity_key, MAX(captured_at) AS latest
                  FROM snapshots
                 WHERE entity_type = :etype AND captured_at <= :cutoff {inner_source}
                 GROUP BY entity_key) last
            ON last.entity_key = s.entity_key AND last.latest = s.captured_at
         WHERE s.entity_type = :etype {source_clause}
        """,
        {"etype": entity_type, "cutoff": cutoff, "source": source},
    ).fetchall()


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
        trial_rows = _latest_per_key(conn, "trial", cutoff)
        fin_rows = _latest_per_key(conn, "company", cutoff, source="financials")
        # Approvals known by then: the earliest snapshot per application at or before
        # the cutoff. First-seen is the fact; a later re-snapshot does not change that
        # it was already known.
        approval_rows = conn.execute(
            """
            SELECT entity_key, MIN(captured_at) AS first_seen,
                   json_extract(payload, '$.ticker') AS ticker,
                   json_extract(payload, '$.approval_date') AS approval_date
              FROM snapshots
             WHERE entity_type = 'approval' AND captured_at <= ?
             GROUP BY entity_key
            """,
            (cutoff,),
        ).fetchall()
        brands = {r["application_number"]: r["brand_name"] for r in conn.execute(
            "SELECT ap.application_number, a.brand_name FROM approvals ap"
            " JOIN assets a ON ap.asset_id = a.id")}
    finally:
        conn.close()

    trials = {}
    for row in trial_rows:
        payload = json.loads(row["payload"])
        trials[row["entity_key"]] = {
            "nct_id": row["entity_key"], "ticker": payload.get("ticker"),
            "title": payload.get("title"), "phase": payload.get("phase"),
            "overall_status": payload.get("overall_status"),
            "primary_completion_date": payload.get("primary_completion_date"),
            "captured_at": row["captured_at"],
        }

    financials = {}
    for row in fin_rows:
        payload = json.loads(row["payload"])
        if payload.get("ticker"):
            financials[payload["ticker"]] = {
                "fiscal_year": payload.get("fiscal_year"),
                "currency": payload.get("currency"),
                "revenue": payload.get("revenue"),
                "net_income": payload.get("net_income"),
                "rd_expense": payload.get("rd_expense"),
                "captured_at": row["captured_at"],
            }

    approvals = []
    for row in approval_rows:
        approvals.append({
            "application_number": row["entity_key"], "ticker": row["ticker"],
            "approval_date": row["approval_date"],
            "brand_name": brands.get(row["entity_key"]),
            "first_seen": row["first_seen"],
        })
    approvals.sort(key=lambda a: (a["ticker"] or "", a["approval_date"] or ""))

    by_ticker: dict[str, dict] = {}
    for trial in trials.values():
        ticker = trial["ticker"] or "unmapped"
        entry = by_ticker.setdefault(ticker, {"trials": 0, "statuses": {},
                                              "approvals_known": 0})
        entry["trials"] += 1
        status = trial["overall_status"] or "unknown"
        entry["statuses"][status] = entry["statuses"].get(status, 0) + 1
    for approval in approvals:
        ticker = approval["ticker"] or "unmapped"
        by_ticker.setdefault(ticker, {"trials": 0, "statuses": {},
                                      "approvals_known": 0})["approvals_known"] += 1
    for ticker, fin in financials.items():
        entry = by_ticker.setdefault(ticker, {"trials": 0, "statuses": {},
                                              "approvals_known": 0})
        entry["revenue"] = fin["revenue"]
        entry["fiscal_year"] = fin["fiscal_year"]
        entry["currency"] = fin["currency"]

    return {
        "as_of": when.isoformat(),
        "history_begins": first,
        "before_history": bool(first) and when.isoformat() < first[:10],
        "trials": sorted(trials.values(), key=lambda t: t["nct_id"]),
        "financials": financials,
        "approvals": approvals,
        "by_ticker": by_ticker,
    }
