"""The disease a marketed product treats, resolved once for every view that shows it.

The label states it, so the label is read first, and the same product can be filed more
than once: Aromasin's label sits on a row that carries no approval, Humalog KwikPen has
no label of its own because DailyMed lists Humalog, and Calquence is filed twice, once as
the base and once as the maleate salt. So a row with no label of its own borrows one from
another row of the same brand or the same ingredient, which is the same product either
way.

Where no label can be found at all, what the drug's own trials study answers instead, and
failing that the ingredient name where it names a class: an insulin treats diabetes.
A product that satisfies none of these is returned as None and shown as unstated, never
filed under a guess.
"""

from __future__ import annotations

import db
import therapeutic_areas


def _label_for(conn, asset_id: int) -> str | None:
    """The product's own indications, or those of another row of the same product."""
    own = conn.execute(
        "SELECT indications_text FROM labels WHERE asset_id = ?"
        "  AND indications_text IS NOT NULL"
        "  ORDER BY effective_time DESC LIMIT 1", (asset_id,)).fetchone()
    if own:
        return own["indications_text"]
    shared = conn.execute(
        """
        SELECT l.indications_text FROM labels l
          JOIN assets a2 ON a2.id = l.asset_id
          JOIN assets a ON a.id = ?
         WHERE a2.owner_company_id = a.owner_company_id
           AND (LOWER(a2.brand_name) = LOWER(a.brand_name)
                OR LOWER(a2.generic_name) = LOWER(a.generic_name))
           AND l.indications_text IS NOT NULL
         ORDER BY l.effective_time DESC LIMIT 1
        """, (asset_id,)).fetchone()
    return shared["indications_text"] if shared else None


def area_for(conn, asset_id: int) -> str | None:
    """The therapeutic area of one product, or None when nothing on file states it."""
    row = conn.execute(
        "SELECT generic_name, brand_name FROM assets WHERE id = ?",
        (asset_id,)).fetchone()
    if row is None:
        return None

    label = _label_for(conn, asset_id)
    area = therapeutic_areas.classify_label(label) if label else therapeutic_areas.OTHER
    if area == therapeutic_areas.OTHER:
        conditions = conn.execute(
            "SELECT GROUP_CONCAT(conditions, ' ') AS blob FROM trials"
            "  WHERE asset_id = ?", (asset_id,)).fetchone()["blob"]
        if conditions:
            area = therapeutic_areas.classify([conditions])
    if area == therapeutic_areas.OTHER and row["generic_name"]:
        area = therapeutic_areas.classify([row["generic_name"]])
    return None if area == therapeutic_areas.OTHER else area


def areas_for(db_path, asset_ids) -> dict:
    """{asset_id: area or None} for many products in one connection."""
    ids = [i for i in dict.fromkeys(asset_ids) if i]
    if not ids:
        return {}
    conn = db.get_connection(db_path)
    try:
        return {asset_id: area_for(conn, asset_id) for asset_id in ids}
    finally:
        conn.close()
