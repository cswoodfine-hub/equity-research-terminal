"""Every dated thing ahead of one company, in one list, in date order.

The dates live where they were found. A readout is a catalyst row, a panel vote is an
advisory committee notice, a loss of exclusivity is a patent or an exclusivity record,
and the day the cash runs out is arithmetic on the balance sheet. Each has its own view,
and a reader who wants to know what stands between today and a readout has to visit four
of them and hold the dates in their head. A raise that must happen before a result, or an
exclusivity that lapses the quarter after a successor reads out, is only visible when the
dates sit in one column.

This joins them and adds nothing. Every row keeps the date as its source states it and
says how firm that date is, in the source's own terms:

- **Catalysts**, pending and dated: readouts, PDUFA dates, regulatory decisions and
  submissions. Where the company has guided to a date of its own (``guided_date``), both
  are shown, because the registry's primary completion date and the company's "first
  half of 2027" are different claims and the gap between them is information.
- **Advisory committees** bound to the company (``adcomm_meetings``).
- **Losses of exclusivity** inside the window, at the date the valuation uses
  (``loe.loe_detail``'s ``valued_loe``), with its basis.
- **Cash out**, the day ``runway`` projects the cash is spent, for a company that burns.

What is not here is said in ``absent``. The book stores no announced date for the next
results: ``earnings_surprises`` holds the days results were reported, and a date a quarter
on from the last one is a projection, not a date, so it is given as the last report and
left to the reader. A row is kept only with a date that parses to at least a month.
"""

from __future__ import annotations

import datetime as dt

import db

DEFAULT_DAYS = 365
MAX_DAYS = 365 * 5
# A date known only to the month sorts at its first day and is marked as a month.
_PRECISION = {10: "day", 7: "month", 4: "year"}


def _sort_key(text: str) -> str:
    """An ISO day for ordering: "2027-03" sorts as the first of March, "2027" as the
    first of January."""
    text = (text or "").strip()
    if len(text) == 4:
        return text + "-01-01"
    if len(text) == 7:
        return text + "-01"
    return text[:10]


def _precision(text: str) -> str | None:
    return _PRECISION.get(len((text or "").strip()))


def _catalysts(conn, company_id: int, today: str, until: str) -> list:
    rows = []
    for r in conn.execute(
            """SELECT cat.id, cat.catalyst_type, cat.expected_date, cat.date_confidence,
                      cat.title, cat.source_url, cat.is_curated, cat.asset_id,
                      cat.guided_date, cat.guided_confidence, cat.guided_source_url,
                      COALESCE(a.brand_name, a.generic_name, a.internal_code) AS asset
                 FROM catalysts cat LEFT JOIN assets a ON a.id = cat.asset_id
                WHERE cat.company_id = ? AND cat.status = 'pending'
                  AND cat.expected_date IS NOT NULL""", (company_id,)):
        key = _sort_key(r["expected_date"])
        guided_key = _sort_key(r["guided_date"]) if r["guided_date"] else None
        # In the window on either date: a readout the registry dates to last month and the
        # company guides to next spring is still ahead.
        inside = [k for k in (key, guided_key) if k and today <= k <= until]
        if not inside:
            continue
        rows.append({
            "date": r["expected_date"], "sort": min(inside),
            "precision": _precision(r["expected_date"]),
            "kind": r["catalyst_type"], "what": r["title"], "asset": r["asset"],
            "asset_id": r["asset_id"], "catalyst_id": r["id"],
            "firmness": r["date_confidence"],
            "guided_date": r["guided_date"], "guided_firmness": r["guided_confidence"],
            "guided_source_url": r["guided_source_url"],
            "curated": bool(r["is_curated"]), "source_url": r["source_url"],
        })
    return rows


def _panels(conn, company_id: int, today: str, until: str) -> list:
    return [{
        "date": r["meeting_date"], "sort": r["meeting_date"], "precision": "day",
        "kind": "advisory committee",
        "what": " ".join(x for x in (r["committee"], r["product"]) if x),
        "asset_id": r["asset_id"], "firmness": "scheduled in the Federal Register",
        "source_url": r["url"],
    } for r in conn.execute(
        """SELECT committee, meeting_date, product, asset_id, url FROM adcomm_meetings
            WHERE company_id = ? AND meeting_date BETWEEN ? AND ?""",
        (company_id, today, until))]


def _exclusivities(db_path, ticker: str, today: str, until: str) -> list:
    import loe
    out = []
    for r in loe.loe_detail(db_path, ticker) or []:
        day = r.get("valued_loe") or r.get("loe")
        if not day or not (today <= _sort_key(day) <= until):
            continue
        out.append({
            "date": day, "sort": _sort_key(day), "precision": _precision(day),
            "kind": "loss of exclusivity",
            "what": r.get("brand_name") or r.get("generic_name"),
            "asset": r.get("brand_name") or r.get("generic_name"),
            "asset_id": r.get("asset_id"),
            "firmness": r.get("valued_loe_basis") or r.get("loe_basis"),
            "challenged": bool(r.get("challenged")),
        })
    return out


def _cash_out(db_path, ticker: str, today: str, until: str) -> tuple:
    """(row or None, the runway headline for context)."""
    import runway
    try:
        got = runway.for_company(db_path, ticker)
    except Exception:                      # a company with no balance sheet on file
        got = None
    if not got:
        return None, None
    context = {"runway_months": got.get("runway_months"), "cash_as_of": got.get("cash_as_of"),
               "funded_to_readout": got.get("funded_to_readout"),
               "burn_basis": got.get("burn_basis")}
    day = got.get("cash_out")
    if not day or not (today <= _sort_key(day) <= until):
        return None, context
    return ({"date": day, "sort": _sort_key(day), "precision": _precision(day),
             "kind": "cash out", "what": "cash spent at the current burn",
             "firmness": "projected from the last balance sheet and the trailing burn"},
            context)


def for_company(db_path=None, ticker: str = "", days: int = DEFAULT_DAYS,
                today=None) -> dict | None:
    """The dated events ahead of one company, soonest first. None for an unknown ticker."""
    ticker = (ticker or "").strip().upper()
    today = today or dt.date.today()
    days = max(1, min(int(days or DEFAULT_DAYS), MAX_DAYS))
    start, until = today.isoformat(), (today + dt.timedelta(days=days)).isoformat()
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id, name FROM companies WHERE ticker = ?",
                               (ticker,)).fetchone()
        if company is None:
            return None
        rows = (_catalysts(conn, company["id"], start, until)
                + _panels(conn, company["id"], start, until))
        last_results = conn.execute(
            "SELECT MAX(reported_on) FROM earnings_surprises WHERE company_id = ?",
            (company["id"],)).fetchone()[0]
        overdue = conn.execute(
            """SELECT COUNT(*) FROM catalysts WHERE company_id = ? AND status = 'pending'
                AND expected_date IS NOT NULL AND length(expected_date) = 10
                AND expected_date < ?""", (company["id"], start)).fetchone()[0]
    finally:
        conn.close()
    rows += _exclusivities(db_path, ticker, start, until)
    cash, runway_context = _cash_out(db_path, ticker, start, until)
    if cash:
        rows.append(cash)
    rows.sort(key=lambda r: (r["sort"], r["kind"]))
    for row in rows:
        row.pop("sort")
    return {
        "ticker": ticker, "name": company["name"], "from": start, "to": until,
        "events": rows,
        "runway": runway_context,
        "pending_past_due": overdue,
        "last_results_reported": last_results,
        "absent": [
            "No announced date for the next results is stored; the last report date is "
            "given and a date a quarter on from it would be a projection.",
            "Conference presentations and investor days are not tracked.",
        ],
    }
