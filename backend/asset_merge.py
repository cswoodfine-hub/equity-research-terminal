"""Fold a derived compound into the marketed product it turns out to be.

The pipeline derives a compound from the drug each trial names, and the registry names
drugs by ingredient. Marketed products arrive from openFDA under their brand. So one
drug could sit in the database twice, once as "Jaypirca" with an approval and once as
"Pirtobrutinib" with five trials, and the second row read as an unapproved compound in
the pipeline. Across the universe, 34 compounds were running Phase 4 studies, which only
an approved product can run.

Matching is on the canonical name the trial mapper already uses, so the two rows have to
agree on the drug itself rather than on spelling, and only within one company: two firms
can develop compounds with similar names, and a merge across owners would be a fabricated
relationship. The derived row's trials move to the marketed row and the empty row goes,
so a merge cannot lose a study or leave a duplicate behind.

Idempotent: a second run finds nothing to merge.
"""

from __future__ import annotations

import assets_util
import db
import trial_mapping


def _canonical_names(asset) -> set:
    """Every canonical spelling a row answers to: its generic, its brand, its code."""
    names = set()
    for field in ("generic_name", "brand_name", "internal_code"):
        value = asset[field] if field in asset.keys() else None
        if not value:
            continue
        canon = trial_mapping.canonical(str(value))
        if canon and len(canon) > 2:
            names.add(canon)
    return names


def find_duplicates(conn, company_id: int) -> list[tuple]:
    """(derived_asset_id, marketed_asset_id) for every unapproved row that names the
    same drug as one of the company's marketed products."""
    marketed = conn.execute(
        "SELECT id, generic_name, brand_name, internal_code FROM assets"
        "  WHERE owner_company_id = ? AND is_marketed = 1", (company_id,)).fetchall()
    by_name: dict = {}
    for row in marketed:
        for name in _canonical_names(row):
            # A name held by two marketed rows identifies neither, so it is dropped
            # rather than merged into whichever came first.
            by_name[name] = None if name in by_name else row["id"]

    pairs = []
    derived = conn.execute(
        "SELECT id, generic_name, brand_name, internal_code FROM assets"
        "  WHERE owner_company_id = ? AND is_marketed = 0", (company_id,)).fetchall()
    for row in derived:
        targets = {by_name[n] for n in _canonical_names(row)
                   if by_name.get(n) is not None}
        if len(targets) == 1:
            pairs.append((row["id"], targets.pop()))
    return pairs


def merge(db_path=None) -> dict:
    """Move every duplicate's trials onto the marketed row and delete the empty row."""
    conn = db.get_connection(db_path)
    merged = moved = 0
    try:
        companies = [r["id"] for r in conn.execute("SELECT id FROM companies")]
        for company_id in companies:
            for derived_id, marketed_id in find_duplicates(conn, company_id):
                moved += conn.execute(
                    "UPDATE trials SET asset_id = ? WHERE asset_id = ?",
                    (marketed_id, derived_id)).rowcount
                # Anything else keyed to the derived row follows the trials, so the
                # delete cannot orphan a mapping or break a foreign key. Where the
                # marketed row already holds the same key, the move is skipped and the
                # duplicate dropped: it is the same fact recorded twice, and the copy
                # kept is the one on the row that survives.
                for table in assets_util.referring_tables(conn):
                    if table == "trials":
                        continue          # already moved, and counted, above
                    conn.execute(f"UPDATE OR IGNORE {table} SET asset_id = ?"
                                 "  WHERE asset_id = ?", (marketed_id, derived_id))
                    conn.execute(f"DELETE FROM {table} WHERE asset_id = ?",
                                 (derived_id,))
                conn.execute("DELETE FROM assets WHERE id = ?", (derived_id,))
                merged += 1
        conn.commit()
    finally:
        conn.close()
    return {"merged": merged, "trials_moved": moved}
