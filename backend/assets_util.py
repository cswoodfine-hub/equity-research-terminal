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


def resolve_alias(conn, internal_code):
    """The asset an absorbed application number now belongs to, or None.

    One product holds several applications, one per formulation and strength, and the
    merge folds them onto a single row. Without this the next refresh would recreate every
    row the merge removed, since a product is looked up by application number alone.
    """
    row = conn.execute(
        "SELECT asset_id FROM asset_aliases WHERE internal_code = ?",
        (internal_code,)).fetchone()
    return row[0] if row else None


def upsert_asset(conn, company_id, internal_code, brand, generic, modality,
                 *, brand_key: bool = False) -> int:
    """Insert or fetch a marketed asset by internal_code; return its id.

    An application number already folded into another product resolves to that product
    rather than being inserted again.

    ``brand_key`` widens the key to the application and the brand together, and the
    caller sets it only for an application openFDA shows carrying more than one brand.
    NDA213051 is the case: RYBELSUS at 3, 7 and 14mg beside OZEMPIC at 1.5, 4 and 9mg,
    two products with two labels and two reported revenue lines on one application.
    Keyed by the number alone, the second brand resolves onto the first brand's asset
    and then overwrites its name, so which product the book holds depends on the order
    openFDA happens to return products in. Every single-brand application, which is
    nearly all of them, is looked up exactly as before.
    """
    if brand_key and brand:
        row = conn.execute(
            "SELECT id FROM assets WHERE internal_code = ?"
            "   AND LOWER(TRIM(COALESCE(brand_name, ''))) = LOWER(TRIM(?))",
            (internal_code, brand)).fetchone()
        if row is None:
            # Not the alias either: an alias records which applications make up one
            # product, and this application makes up two. Resolving through it is what
            # put Rybelsus inside Ozempic and left its revenue line nowhere.
            return _insert_asset(conn, company_id, internal_code, brand, generic,
                                 modality)
        conn.execute(
            "UPDATE assets SET generic_name = COALESCE(?, generic_name),"
            "  modality = COALESCE(?, modality), is_marketed = 1,"
            "  updated_at = datetime('now') WHERE id = ?",
            (generic, modality, row[0]))
        return row[0]
    row = conn.execute(
        "SELECT id FROM assets WHERE internal_code = ?", (internal_code,)
    ).fetchone()
    if row is None:
        merged_into = resolve_alias(conn, internal_code)
        if merged_into is not None:
            row = (merged_into,)
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
    return _insert_asset(conn, company_id, internal_code, brand, generic, modality)


def _insert_asset(conn, company_id, internal_code, brand, generic, modality) -> int:
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


def referring_columns(conn) -> list:
    """Every (table, column) in the schema that points at ``assets(id)``.

    The whole reference graph, not the part that happens to be named ``asset_id``.
    Molecule grouping added ``assets.molecule_id``, a row pointing at the head of its
    own molecule, and that is a reference like any other: absorb the head into another
    row and the delete breaks a foreign key. The daily refresh crashed on exactly that
    for five days, on Otezla, because the caller below only ever looked for a column
    called ``asset_id`` and skipped the assets table outright.

    Reading the FK list rather than the column names keeps the next such column covered
    the day it exists, whatever it is called and whichever table it sits in.
    """
    out = []
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"):
        for fk in conn.execute(f"PRAGMA foreign_key_list({name})"):
            if fk[2] == "assets" and (fk[4] or "id") == "id":
                out.append((name, fk[3]))
    return sorted(set(out))


def referring_tables(conn) -> list:
    """Every table with an ``asset_id`` that points at ``assets``, from the schema.

    Written down by hand this list goes stale: completed trials arrived after two
    callers had already listed the tables they knew about, and both then failed on a
    foreign key the moment a derived asset had a completed study. Reading the schema
    keeps a new table respected the day it exists.

    Rows in other tables only. A caller that has to account for every reference,
    including the assets table's own, wants ``referring_columns``.
    """
    return sorted({table for table, column in referring_columns(conn)
                   if table != "assets" and column == "asset_id"})
