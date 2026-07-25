"""Label changes: the detected label events, with the label state behind each.

The change rows the diff engine writes carry the headline; this joins them back to
the labels table so a view can show the version, the current indications text, and
the population fields alongside. Read-only.
"""

from __future__ import annotations

import db

LABEL_CHANGE_TYPES = ("label_change", "new_indication", "population_expansion")


def list_label_changes(db_path=None, ticker: str = None, days: int = 365) -> list[dict]:
    marks = ",".join("?" * len(LABEL_CHANGE_TYPES))
    sql = f"""
        SELECT ch.id AS change_id, ch.detected_at, ch.change_type, ch.significance,
               ch.old_value, ch.new_value AS headline, ch.entity_key AS setid,
               c.ticker, l.drug_name, l.spl_version, l.indication_count,
               l.age_floor_years, l.age_ceiling_years, l.population_text,
               l.effective_time
          FROM changes ch
          LEFT JOIN labels l ON l.setid = ch.entity_key
          LEFT JOIN assets a ON a.id = l.asset_id
          LEFT JOIN companies c ON c.id = a.owner_company_id
         WHERE ch.entity_type = 'label' AND ch.change_type IN ({marks})
           AND ch.detected_at >= datetime('now', ?)
    """
    params = [*LABEL_CHANGE_TYPES, f"-{int(days)} days"]
    if ticker:
        sql += " AND c.ticker = ?"
        params.append(ticker.upper())
    sql += " ORDER BY ch.detected_at DESC, ch.id DESC"
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def list_supplements(db_path=None, ticker: str = None, limit: int = 60) -> list[dict]:
    """Approved efficacy supplements, newest first. Each is a label expansion that
    already happened, from drugsfda; it corroborates the DailyMed label signal."""
    sql = """
        SELECT s.application_number, s.submission_number, s.approval_date,
               s.description, a.brand_name, c.ticker
          FROM supplements s
          LEFT JOIN assets a ON a.id = s.asset_id
          LEFT JOIN companies c ON c.id = a.owner_company_id
    """
    params = []
    if ticker:
        sql += " WHERE c.ticker = ?"
        params.append(ticker.upper())
    sql += " ORDER BY s.approval_date DESC, s.id DESC LIMIT ?"
    params.append(limit)
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def current_labels(db_path=None, ticker: str = None) -> list[dict]:
    """The current tracked label state per product, for the labels view."""
    sql = """
        SELECT l.setid, l.drug_name, l.spl_version, l.effective_time,
               l.indication_count, l.age_floor_years, l.age_ceiling_years,
               l.population_text, c.ticker
          FROM labels l
          LEFT JOIN assets a ON a.id = l.asset_id
          LEFT JOIN companies c ON c.id = a.owner_company_id
    """
    params = []
    if ticker:
        sql += " WHERE c.ticker = ?"
        params.append(ticker.upper())
    sql += " ORDER BY l.drug_name"
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()
