"""The analyst's fair value against the price, day by day, with what moved it.

The price line is the market's view and the source hands back its history: a week the
machine was off still fills in, because Yahoo returns the whole series on the next fetch.
The fair value line is this book's own view and no source has it. It exists only where
call_log wrote it down on the day, which is the point of writing it down on the day.

So the two lines go stale differently, and the chart has to say which is which:

- A day with a call is the model's stated view, drawn solid.
- A day without one carries the last stated view flat. The model did not change its mind
  on a day nobody asked it, and a flat line says that honestly. It is marked carried, and
  a reader is shown the difference rather than being left to assume a daily rebuild.
- A day before the first call has no line at all. Nothing is carried backwards, because
  a value recomputed today for a past date carries everything learnt since.

Nothing here writes. The carry is a reading of the record, never an addition to it: a
carried point must never reach model_calls, where it would become eight days of track
record the model never stated and call_log.score would mark it against outcomes it never
saw.
"""

from __future__ import annotations

import assumption_log
import db
import whatchanged

# A line that carries for longer than this has stopped being a view and become an
# artefact. The chart still draws the price; the fair value stops and says when it was
# last stated.
MAX_CARRY_DAYS = 45


def _closes(conn, ticker: str, since: str | None) -> list[dict]:
    """Daily closes. The prices table holds intraday bars under the same column, stamped
    with a time, so a bare date is what makes a row the day's close."""
    args = [ticker.upper()]
    where = "c.ticker = ? AND p.as_of NOT LIKE '% %'"
    if since:
        where += " AND p.as_of >= ?"
        args.append(since)
    return [dict(r) for r in conn.execute(
        f"""SELECT p.as_of, p.close FROM prices p JOIN companies c ON c.id = p.company_id
             WHERE {where} ORDER BY p.as_of""", args)]


def _calls(conn, ticker: str, since: str | None) -> dict:
    args = [ticker.upper()]
    where = "ticker = ?"
    if since:
        where += " AND as_of >= ?"
        args.append(since)
    return {r["as_of"]: dict(r) for r in conn.execute(
        f"""SELECT as_of, fair_value, price, upside_12m, rating, forward_12m,
                   low_today, high_today, code_version
              FROM model_calls WHERE {where} ORDER BY as_of""", args)}


def _model_events(conn, ticker: str, since: str | None) -> list[dict]:
    """What the analyst changed, one marker per save rather than one per row.

    A save that moved nine numbers is one decision, and nine markers on one day would
    read as nine. The reason and the valuation either side are the batch's, so the batch
    is the unit.
    """
    rows = [r for r in assumption_log.log(conn, ticker=ticker, since=since, limit=2000)
            if r["reason"] and r["reason"] != "initial_seed"]
    batches: dict = {}
    for row in rows:
        key = row["batch_id"] or f"row:{row['id']}"
        held = batches.setdefault(key, {
            "date": row["changed_at"][:10], "kind": "model",
            "reason": row["reason"], "rationale": row["rationale"],
            "trigger_ref": row["trigger_ref"], "changed_by": row["changed_by"],
            "rnpv_before": row["rnpv_before"], "rnpv_after": row["rnpv_after"],
            "rows": []})
        held["rows"].append({
            "brand": row["brand_name"] or row["generic_name"],
            "indication": row["indication"], "key": row["key"],
            "from": row["old_value"], "to": row["new_value"],
            "evidence": row["new_evidence"]})
    out = []
    for held in batches.values():
        lead = held["rows"][0]
        more = len(held["rows"]) - 1
        where = f" in {lead['indication']}" if lead["indication"] else ""
        moved = (f"{lead['key']} {_num(lead['from'])} to {_num(lead['to'])}"
                 if lead["from"] is not None or lead["to"] is not None
                 else lead["key"])
        held["headline"] = (f"{lead['brand']}{where}: {moved}"
                            + (f", and {more} more" if more else ""))
        before, after = held["rnpv_before"], held["rnpv_after"]
        held["rnpv_move"] = (after - before) if (
            before is not None and after is not None) else None
        out.append(held)
    return sorted(out, key=lambda e: e["date"])


def _num(v):
    if v is None:
        return "nothing"
    return f"{v:g}"


def series(db_path=None, ticker: str = "", since: str | None = None,
           days: int = 180) -> dict:
    """The two lines and the events on them.

    ok False with a reason where the book has never recorded a call for the company, so
    an empty chart says why rather than drawing a flat line at zero.
    """
    conn = db.get_connection(db_path)
    try:
        closes = _closes(conn, ticker, since)
        calls = _calls(conn, ticker, since)
        if not calls:
            return {"ok": False, "ticker": ticker.upper(), "points": [], "events": [],
                    "reason": "no_calls",
                    "why": "the book has recorded no fair value for this company yet; "
                           "the daily refresh writes one and nothing can backfill it"}
        axis = sorted({row["as_of"] for row in closes} | set(calls))
        by_date = {row["as_of"]: row["close"] for row in closes}
        points, close, stated, since_stated = [], None, None, 0
        for day in axis:
            if day in by_date:
                close, close_stale = by_date[day], False
            else:
                close_stale = close is not None
            call = calls.get(day)
            if call:
                stated, since_stated = call, 0
            elif stated is not None:
                since_stated += 1
            carried = stated is not None and not call
            if carried and since_stated > MAX_CARRY_DAYS:
                stated = None
            points.append({
                "as_of": day, "close": close, "close_stale": close_stale,
                "fair_value": (stated or {}).get("fair_value") if stated else None,
                "low": (stated or {}).get("low_today") if stated else None,
                "high": (stated or {}).get("high_today") if stated else None,
                "rating": (stated or {}).get("rating") if stated else None,
                "stated": bool(call),
                "carried": bool(carried and stated is not None),
            })
        world = [e for e in whatchanged.build_feed(db_path, days=days, ticker=ticker)
                 if e.get("ticker") and e.get("date")]
        events = _model_events(conn, ticker, since) + [
            {"date": e["date"][:10], "kind": e.get("kind"),
             "headline": e.get("headline"), "significance": e.get("significance"),
             "change_type": e.get("change_type")} for e in world]
        first, last = axis[0], axis[-1]
        events = [e for e in events if first <= e["date"] <= last]
    finally:
        conn.close()
    said = [p for p in points if p["stated"]]
    # Counted apart: a day before the first call is not a day the view was carried, it is
    # a day there was no view. Calling it carried would claim a line the chart never draws.
    held = [p for p in points if p["carried"]]
    return {"ok": True, "ticker": ticker.upper(), "points": points,
            "events": sorted(events, key=lambda e: e["date"]),
            "stated_days": len(said), "carried_days": len(held),
            "blank_days": len(points) - len(said) - len(held),
            "begins": said[0]["as_of"] if said else None,
            "last_stated": said[-1]["as_of"] if said else None}
