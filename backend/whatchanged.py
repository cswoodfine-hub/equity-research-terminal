"""What-changed feed (the rules layer).

Merges recently detected changes (diff engine), upcoming catalysts (<=60 days), and
near-term loss of exclusivity into one list ranked by significance then date. The
optional Anthropic note layer that summarises this per company is phase 7.
"""

from __future__ import annotations

import db

_SIG_RANK = {"high": 0, "medium": 1, "low": 2}


def _trial_headline(ticker, entity_key, change_type, old, new):
    tag = f"{ticker} " if ticker else ""
    if change_type == "status_change":
        return f"{tag}trial {entity_key}: status {old} -> {new}"
    if change_type == "date_slip":
        return f"{tag}trial {entity_key}: primary completion slips {old} -> {new}"
    if change_type == "date_change":
        return f"{tag}trial {entity_key}: primary completion {old} -> {new}"
    if change_type in ("phase_advance", "phase_regress"):
        return f"{tag}trial {entity_key}: {old} -> {new}"
    return f"{tag}trial {entity_key}: {change_type}"


def _recent_changes(conn, days):
    nct_ticker = {
        r["nct_id"]: r["ticker"]
        for r in conn.execute(
            "SELECT t.nct_id, c.ticker FROM trials t LEFT JOIN companies c ON t.sponsor_company_id = c.id"
        )
    }
    items = []
    for r in conn.execute(
        """
        SELECT entity_type, entity_key, field, old_value, new_value, change_type,
               significance, detected_at
          FROM changes
         WHERE detected_at >= datetime('now', ?)
        """,
        (f"-{int(days)} days",),
    ):
        if r["entity_type"] == "trial":
            ticker = nct_ticker.get(r["entity_key"])
            headline = _trial_headline(ticker, r["entity_key"], r["change_type"],
                                       r["old_value"], r["new_value"])
        else:  # filing / approval headlines already carry the ticker prefix
            ticker = (r["new_value"] or "").split(" ", 1)[0] or None
            headline = r["new_value"]
        items.append({
            "kind": "change", "significance": r["significance"], "date": r["detected_at"],
            "ticker": ticker, "change_type": r["change_type"], "headline": headline,
        })
    return items


def _upcoming_catalysts(conn, within_days):
    soon_threshold = _date_offset(conn, 14)
    items = []
    for r in conn.execute(
        """
        SELECT c.ticker, cat.catalyst_type, cat.expected_date, cat.title
          FROM catalysts cat JOIN companies c ON cat.company_id = c.id
         WHERE cat.status = 'pending' AND cat.expected_date >= date('now')
           AND cat.expected_date <= date('now', ?)
        """,
        (f"+{int(within_days)} days",),
    ):
        soon = r["expected_date"] <= soon_threshold
        items.append({
            "kind": "catalyst", "significance": "high" if soon else "medium",
            "date": r["expected_date"], "ticker": r["ticker"],
            "change_type": r["catalyst_type"],
            "headline": f"{r['ticker']} {r['catalyst_type']}: {r['title']} ({r['expected_date']})",
        })
    return items


def _near_term_loe(conn, months, limit):
    horizon = _date_offset(conn, months * 30)
    items = []
    for r in conn.execute(
        """
        SELECT c.ticker, a.brand_name, a.modality, MAX(e.expiry_date) AS loe
          FROM assets a JOIN exclusivities e ON e.asset_id = a.id
          JOIN companies c ON a.owner_company_id = c.id
         GROUP BY a.id
        HAVING loe >= date('now') AND loe <= ?
         ORDER BY loe LIMIT ?
        """,
        (horizon, limit),
    ):
        items.append({
            "kind": "loe", "significance": "medium", "date": r["loe"], "ticker": r["ticker"],
            "change_type": "loe", "modality": r["modality"],
            "headline": f"{r['ticker']} LOE: {r['brand_name']} loses exclusivity {r['loe']}",
        })
    return items


def _date_offset(conn, days):
    return conn.execute("SELECT date('now', ?)", (f"+{int(days)} days",)).fetchone()[0]


def build_feed(db_path=None, days=30, catalyst_days=60, loe_months=24, loe_limit=15):
    conn = db.get_connection(db_path)
    try:
        items = (
            _recent_changes(conn, days)
            + _upcoming_catalysts(conn, catalyst_days)
            + _near_term_loe(conn, loe_months, loe_limit)
        )
    finally:
        conn.close()
    # Rank by significance (high first), then by date (recent changes / furthest-out
    # flags first). Two stable sorts keep the date order within each significance band.
    items.sort(key=lambda x: x["date"], reverse=True)
    items.sort(key=lambda x: _SIG_RANK.get(x["significance"], 3))
    return items
