"""Re-point the history tables at the rows this build gave out.

``asset_id`` is a surrogate key. ``history.py rebuild`` restores the history tables
before ``seed.py`` repopulates assets, so every id a restored row carries was issued by
an earlier build and need not mean the same thing twice. Measured on the cloud book
after a single rebuild on 2026-10-26: 1,135 of 17,119 ledger rows and 545 of 1,815
gate_calls rows pointed at no asset at all. The alpha dataset was quietly losing its
joins, a little more every day, and nothing reported it.

The names are the record and the id is an index into it. ``gate_calls`` already carried
ticker, asset name and the NCT; ``assumption_edits`` gained them in 091. This re-points
the id from the names, after the refresh has settled the asset rows.

What it will not do:

* It never invents a link. A name that matches no asset, or more than one, is left
  unresolved and counted, because a ledger row pointing at the wrong product is worse
  than one pointing at none.
* It never touches a row whose id still resolves. A correct pointer is not improved by
  being recomputed, and leaving it alone keeps the repair to what actually broke.
* It changes no value, reason, author or date. Repairing a pointer is not rewriting a
  record: what was said, when and why is untouched.
"""

from __future__ import annotations

import sqlite3

import db


def _asset_by_name(conn) -> dict:
    """{(ticker, lowered name): asset_id}, dropping any name two assets share.

    A company that sells a brand and a compound under names that collide gives no safe
    answer, so the key is removed rather than resolved to whichever row sorted first.
    """
    seen: dict = {}
    for r in conn.execute(
            """SELECT a.id, c.ticker, a.brand_name, a.generic_name
                 FROM assets a JOIN companies c ON c.id = a.owner_company_id"""):
        for name in (r["brand_name"], r["generic_name"]):
            name = (name or "").strip().lower()
            if not name:
                continue
            key = (r["ticker"], name)
            if key in seen and seen[key] != r["id"]:
                seen[key] = None                 # ambiguous: no safe answer
            else:
                seen.setdefault(key, r["id"])
    return {k: v for k, v in seen.items() if v is not None}


def _indication_by_name(conn) -> dict:
    return {(r["name"] or "").strip().lower(): r["id"]
            for r in conn.execute("SELECT id, name FROM indications")}


def _live_assets(conn) -> set:
    return {r[0] for r in conn.execute("SELECT id FROM assets")}


def _repair(conn, table: str, assets: dict, live: set, indications: dict | None) -> dict:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if not {"asset_id", "ticker", "asset_name"} <= cols:
        return {"checked": 0, "relinked": 0, "unresolved": 0}
    rows = conn.execute(
        f"""SELECT id, asset_id, ticker, asset_name
              FROM {table} WHERE asset_id IS NOT NULL""").fetchall()
    relinked = unresolved = 0
    for r in rows:
        if r["asset_id"] in live:
            continue
        key = ((r["ticker"] or "").strip().upper(),
               (r["asset_name"] or "").strip().lower())
        found = assets.get(key)
        if found is None:
            unresolved += 1
            continue
        try:
            conn.execute(f"UPDATE {table} SET asset_id = ? WHERE id = ?",
                         (found, r["id"]))
        except sqlite3.IntegrityError:
            # Re-pointing would collide with a row already there, which means the event
            # is already recorded against the right asset. Leave both alone.
            unresolved += 1
            continue
        relinked += 1
    out = {"checked": len(rows), "relinked": relinked, "unresolved": unresolved}
    if indications is not None and "indication_name" in cols:
        out["indications"] = _repair_indications(conn, table, indications)
    return out


def _repair_indications(conn, table: str, indications: dict) -> int:
    live = {r[0] for r in conn.execute("SELECT id FROM indications")}
    fixed = 0
    for r in conn.execute(
            f"""SELECT id, indication_id, indication_name FROM {table}
                 WHERE indication_id IS NOT NULL""").fetchall():
        if r["indication_id"] in live:
            continue
        found = indications.get((r["indication_name"] or "").strip().lower())
        if found is None:
            continue
        try:
            conn.execute(f"UPDATE {table} SET indication_id = ? WHERE id = ?",
                         (found, r["id"]))
        except sqlite3.IntegrityError:
            continue
        fixed += 1
    return fixed


def run(db_path=None) -> dict:
    """Repair every history table that can name its subject. Returns what moved."""
    conn = db.get_connection(db_path)
    try:
        assets, live = _asset_by_name(conn), _live_assets(conn)
        indications = _indication_by_name(conn)
        out = {
            "assumption_edits": _repair(conn, "assumption_edits", assets, live,
                                        indications),
            "gate_calls": _repair(conn, "gate_calls", assets, live, None),
        }
        conn.commit()
    finally:
        conn.close()
    return out
