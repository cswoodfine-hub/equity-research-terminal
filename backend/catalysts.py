"""Curated catalysts.

No free PDUFA/readout calendar exists, so catalysts are hand-entered (is_curated=1) and
edited in the UI. The table is empty until the analyst adds rows; nothing is fabricated.
Auto-extraction from 8-K/6-K via the Anthropic API is phase 7.
"""

from __future__ import annotations

import db

CATALYST_TYPES = ["PDUFA", "data readout", "EMA decision", "AdCom", "conference", "other"]


def add_catalyst(db_path, ticker, catalyst_type, expected_date, title,
                 description=None, date_confidence="estimated", source_url=None):
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if company is None:
            raise ValueError(f"unknown ticker {ticker.upper()}")
        cur = conn.execute(
            """
            INSERT INTO catalysts
                (company_id, catalyst_type, expected_date, date_confidence, title,
                 description, is_curated, source_url, status)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, 'pending')
            """,
            (company["id"], catalyst_type, expected_date, date_confidence, title,
             description, source_url),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_catalysts(db_path=None, within_days=90, ticker=None):
    """Upcoming catalysts (expected_date from today to +within_days), soonest first."""
    conn = db.get_connection(db_path)
    try:
        query = """
            SELECT cat.id, c.ticker, c.name, cat.catalyst_type, cat.expected_date,
                   cat.date_confidence, cat.title, cat.description, cat.status,
                   cat.is_curated, cat.source_url
              FROM catalysts cat JOIN companies c ON cat.company_id = c.id
             WHERE cat.expected_date >= date('now')
               AND cat.expected_date <= date('now', ?)
        """
        params = [f"+{int(within_days)} days"]
        if ticker:
            query += " AND c.ticker = ?"
            params.append(ticker.upper())
        query += " ORDER BY cat.expected_date"
        return [dict(r) for r in conn.execute(query, params)]
    finally:
        conn.close()


def delete_catalyst(db_path, catalyst_id) -> bool:
    conn = db.get_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM catalysts WHERE id = ?", (catalyst_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_status(db_path, catalyst_id, status) -> bool:
    conn = db.get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE catalysts SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, catalyst_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
