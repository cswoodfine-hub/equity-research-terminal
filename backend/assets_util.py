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


def brand_family(name: str | None) -> tuple:
    """(the first word of a brand, the brand reduced to letters and digits)."""
    words = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    return (words[0] if words else ""), "".join(words)


def same_brand_family(a: str | None, b: str | None) -> bool:
    """Whether two brand strings name one product rather than two.

    A brand string names a presentation as often as a product: ZEPBOUND beside ZEPBOUND
    KWIKPEN, LANTUS beside LANTUS SOLOSTAR. Two brands are one product if they share a
    first word or one contains the other, and two products only where neither holds, as
    with OZEMPIC and RYBELSUS on the one application NDA213051. Measured on the 33
    applications in the book carrying more than one live brand: 28 are pens, five are
    two products, and this rule separates them exactly. A missing brand is treated as
    the same family, because an unbranded row is a programme, not a rival product.
    """
    if not (a or "").strip() or not (b or "").strip():
        return True
    first_a, flat_a = brand_family(a)
    first_b, flat_b = brand_family(b)
    return bool((first_a and first_a == first_b)
                or (flat_a and flat_b and (flat_a in flat_b or flat_b in flat_a)))


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
            # The alias, but only for its own product. An alias records which
            # applications make up one product, and this application makes up two:
            # resolving the second brand through it is what put Rybelsus inside Ozempic
            # and left its revenue line nowhere. The same family still resolves, so oral
            # Ozempic lands on Ozempic rather than being created again every night.
            merged_into = resolve_alias(conn, internal_code)
            if merged_into is not None:
                held = conn.execute("SELECT brand_name FROM assets WHERE id = ?",
                                    (merged_into,)).fetchone()
                if held is not None and same_brand_family(held[0], brand):
                    row = (merged_into,)
        if row is None:
            return _insert_asset(conn, company_id, internal_code, brand, generic,
                                 modality)
        conn.execute(
            "UPDATE assets SET generic_name = COALESCE(?, generic_name),"
            "  modality = COALESCE(?, modality), is_marketed = 1,"
            "  updated_at = datetime('now') WHERE id = ?",
            (generic, modality, row[0]))
        return row[0]
    # Every asset on the application, and of those the one this brand already names. A
    # caller without ``brand_key`` knows the application and not that it carries two
    # products: the Purple Book lists BLA125326 once as ARZERRA and once as KESIMPTA, and
    # taking whichever row came first sent both to one asset.
    held = conn.execute(
        "SELECT id, brand_name FROM assets WHERE internal_code = ? ORDER BY id",
        (internal_code,)).fetchall()
    row = next((r for r in held if (r[1] or "").strip() and (brand or "").strip()
                and same_brand_family(r[1], brand)), held[0] if held else None)
    if row is None:
        merged_into = resolve_alias(conn, internal_code)
        if merged_into is not None:
            row = conn.execute("SELECT id, brand_name FROM assets WHERE id = ?",
                               (merged_into,)).fetchone()
    if row is not None:
        # The name is filled in or tidied, never changed to another product's. This
        # wrote brand_name = COALESCE(?, brand_name) whatever the row was called, so a
        # register naming the application's other product renamed the asset to it:
        # Novartis's ofatumumab, selling 4.4bn as Kesimpta, became "Arzerra", the brand
        # withdrawn from sale, with Kesimpta's revenue and forecast still on the row.
        # Kesimpta was then created a second time and the revenue stood in the book
        # twice.
        named = brand if same_brand_family(row[1], brand) else None
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
            (named, generic, modality, row[0]),
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
