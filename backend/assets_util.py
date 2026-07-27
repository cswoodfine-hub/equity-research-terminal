"""Shared helper for marketed-product assets.

Orange Book, Purple Book, and openFDA all describe the same marketed products keyed by
FDA application number, so they dedup onto one asset via `internal_code` (a normalized
application id like NDA215866 or BLA761306). This lives outside `fetchers/` so the
fetchers can share it without importing each other.
"""

from __future__ import annotations

import re


def normalize_appl(appl_type: str, appl_no: str) -> str:
    """Build a normalized application id, e.g. ('N','215866') -> 'NDA215866'.

    Leading zeros are stripped so the same product from the Orange Book ('020610')
    and openFDA ('NDA020610') collapse to one asset.
    """
    digits = re.sub(r"\D", "", str(appl_no or ""))
    if digits:
        digits = str(int(digits))
    prefix = {"N": "NDA", "A": "ANDA", "B": "BLA"}.get((appl_type or "").upper()[:1], "")
    if not prefix and str(appl_type or "").upper() in ("NDA", "ANDA", "BLA"):
        prefix = str(appl_type).upper()
    return f"{prefix}{digits}" if digits else ""


def upsert_asset(conn, company_id, internal_code, brand, generic, modality) -> int:
    """Insert or fetch a marketed asset by internal_code; return its id."""
    row = conn.execute(
        "SELECT id FROM assets WHERE internal_code = ?", (internal_code,)
    ).fetchone()
    if row is not None:
        conn.execute(
            """
            UPDATE assets
               SET brand_name = COALESCE(?, brand_name),
                   generic_name = COALESCE(?, generic_name),
                   modality = COALESCE(?, modality),
                   is_marketed = 1,
                   updated_at = datetime('now')
             WHERE id = ?
            """,
            (brand, generic, modality, row[0]),
        )
        return row[0]
    cur = conn.execute(
        """
        INSERT INTO assets
            (owner_company_id, generic_name, brand_name, internal_code, modality,
             is_marketed, notes)
        VALUES (?, ?, ?, ?, ?, 1, 'derived from FDA marketed-product data')
        """,
        (company_id, generic, brand, internal_code, modality),
    )
    return cur.lastrowid


def referring_tables(conn) -> list:
    """Every table with an ``asset_id`` that points at ``assets``, from the schema.

    Written down by hand this list goes stale: completed trials arrived after two
    callers had already listed the tables they knew about, and both then failed on a
    foreign key the moment a derived asset had a completed study. Reading the schema
    keeps a new table respected the day it exists.
    """
    out = []
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"):
        if name == "assets":
            continue
        columns = {c[1] for c in conn.execute(f"PRAGMA table_info({name})")}
        if "asset_id" not in columns:
            continue
        if any(fk[2] == "assets" for fk in
               conn.execute(f"PRAGMA foreign_key_list({name})")):
            out.append(name)
    return sorted(out)
