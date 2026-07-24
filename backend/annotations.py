"""Annotations: the analyst's own line against a company, change, or catalyst.

Plain CRUD over the annotations table. The body is stored verbatim; rendering
escapes it. An annotation always belongs to a ticker so it can render on the
company's views, and optionally to one entity so it can sit inline beside it.
"""

from __future__ import annotations

import db

ENTITY_TYPES = ("company", "change", "catalyst")


def add(db_path, ticker: str, entity_type: str, entity_id: str | None,
        body: str) -> int:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {ENTITY_TYPES}")
    if not (body or "").strip():
        raise ValueError("an empty annotation says nothing; body is required")
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (ticker.upper(),)).fetchone()
        if company is None:
            raise ValueError(f"unknown ticker {ticker.upper()}")
        cur = conn.execute(
            """
            INSERT INTO annotations (ticker, entity_type, entity_id, body)
            VALUES (?, ?, ?, ?)
            """,
            (ticker.upper(), entity_type,
             str(entity_id) if entity_id is not None else None, body.strip()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_annotations(db_path=None, ticker: str | None = None,
                     entity_type: str | None = None,
                     entity_id: str | None = None) -> list[dict]:
    sql = ("SELECT id, created_at, ticker, entity_type, entity_id, body"
           " FROM annotations WHERE 1=1")
    params: list = []
    if ticker:
        sql += " AND ticker = ?"
        params.append(ticker.upper())
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    if entity_id is not None:
        sql += " AND entity_id = ?"
        params.append(str(entity_id))
    sql += " ORDER BY created_at DESC, id DESC"
    conn = db.get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def delete(db_path, annotation_id: int) -> bool:
    conn = db.get_connection(db_path)
    try:
        changed = conn.execute("DELETE FROM annotations WHERE id = ?",
                               (annotation_id,)).rowcount
        conn.commit()
        return bool(changed)
    finally:
        conn.close()
