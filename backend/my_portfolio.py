"""The user's own holdings beside the model's view of each (fetchers/broker_t212.py).

Read live on every call and never cached or stored: the positions are the user's, so they
stay out of the response cache's disk copy and out of the history export that reaches git.
A holding the book covers carries the model's latest recorded call (call_log) and the
company's next dated catalyst; any other holding is listed as it is, with no view.
"""

from __future__ import annotations

import datetime as dt

import db
from fetchers import broker_t212


def mine(db_path=None, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    held = broker_t212.positions()
    if not held.get("ok"):
        return {"ok": False, "status": held.get("status"), "reason": held.get("reason")
                or "Trading 212 did not answer", "rows": []}
    conn = db.get_connection(db_path)
    try:
        covered = {r["ticker"]: r["name"] for r in conn.execute(
            "SELECT ticker, name FROM companies")}
        rows = []
        for p in held["rows"]:
            row = {**p, "covered": p["ticker"] in covered, "model": None, "next_catalyst": None}
            if row["covered"]:
                call = conn.execute(
                    """SELECT as_of, price, fair_value, upside_12m, rating, target_mid
                         FROM model_calls WHERE ticker = ? ORDER BY as_of DESC LIMIT 1""",
                    (p["ticker"],)).fetchone()
                row["model"] = dict(call) if call else None
                cat = conn.execute(
                    """SELECT c.expected_date, c.catalyst_type,
                              COALESCE(a.brand_name, a.generic_name) AS asset, c.title
                         FROM catalysts c JOIN companies co ON co.id = c.company_id
                         LEFT JOIN assets a ON a.id = c.asset_id
                        WHERE co.ticker = ? AND c.status = 'pending'
                          AND c.expected_date >= ?
                        ORDER BY c.expected_date LIMIT 1""",
                    (p["ticker"], today.isoformat())).fetchone()
                row["next_catalyst"] = dict(cat) if cat else None
            rows.append(row)
    finally:
        conn.close()
    rows.sort(key=lambda r: -(r.get("value") or 0))
    return {"ok": True, "currency": held.get("currency"), "rows": rows,
            "covered": sum(1 for r in rows if r["covered"]), "positions": len(rows),
            "source": "your Trading 212 account, read only, live"}
