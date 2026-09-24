"""The two corrections to the marketed register an analyst has to make by hand.

The fetchers decide what is marketed from the FDA's registers, matched to a company by the
applicant name on the licence. Two kinds of product fall through, and each has a file:

``data/marketed_additions.csv``  approved and selling, but licensed under a name the maps
    do not know: an acquired company's (ImmunoGen's Elahere, now AbbVie's) or a small
    filer's. Without a row here the product does not exist in the book and its revenue
    has nowhere to land.
``data/withdrawn_products.csv``  still licensed, so still in the registers, but withdrawn
    from sale by its company. Without a row here it goes on reading as a live product.

Applied on every refresh, after the fetchers, so a rebuilt database gets both back and a
fetcher cannot undo either. Every row cites the approval letter or the company statement.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib

import db
from assets_util import upsert_asset

DATA = db.BACKEND_DIR.parent / "data"
ADDITIONS = DATA / "marketed_additions.csv"
WITHDRAWN = DATA / "withdrawn_products.csv"
SOURCE = "curated_register"
# The same labels the Purple Book fetcher writes, so a curated floor and a fetched one
# read alike wherever exclusivity is shown.
FLOOR_PROTECTION = "reference product exclusivity (12y)"
FLOOR_IDENTIFIER = "12-year statutory floor"


def _rows(path) -> list[dict]:
    path = pathlib.Path(path)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(l for l in handle if not l.lstrip().startswith("#")))


def _floor(licensed_on: str) -> str | None:
    """Twelve years from first licensure, the statutory floor for a biologic."""
    try:
        start = dt.date.fromisoformat(licensed_on)
    except (TypeError, ValueError):
        return None
    try:
        return start.replace(year=start.year + 12).isoformat()
    except ValueError:                        # a 29 February licence
        return start.replace(year=start.year + 12, day=28).isoformat()


def _snapshot(conn, key: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
        " VALUES (?, 'asset', ?, ?)", (SOURCE, key, json.dumps(payload)))


def apply(db_path=None, additions=None, withdrawn=None) -> dict:
    """Mark the additions marketed and the withdrawn unmarketed. Returns counts."""
    conn = db.get_connection(db_path)
    added = retired = 0
    try:
        companies = {r["ticker"]: r["id"] for r in conn.execute(
            "SELECT ticker, id FROM companies")}
        for row in _rows(additions or ADDITIONS):
            company_id = companies.get((row.get("ticker") or "").strip().upper())
            code = (row.get("internal_code") or "").strip()
            if company_id is None or not code:
                continue
            before = conn.execute(
                "SELECT id, is_marketed FROM assets WHERE internal_code = ?", (code,)).fetchone()
            asset_id = upsert_asset(conn, company_id, code, row["brand"].strip(),
                                    (row.get("generic") or "").strip() or None,
                                    (row.get("modality") or "").strip() or None)
            if before is None or not before["is_marketed"]:
                _snapshot(conn, code, {"asset_id": asset_id, "is_marketed": 1,
                                       "was": None if before is None else before["is_marketed"],
                                       "source": row.get("source")})
                added += 1
            expiry = _floor((row.get("licensed_on") or "").strip())
            has_any = conn.execute("SELECT 1 FROM exclusivities WHERE asset_id = ? LIMIT 1",
                                   (asset_id,)).fetchone()
            if expiry and not has_any:
                conn.execute(
                    """INSERT INTO exclusivities
                           (asset_id, region, protection_type, identifier, expiry_date, source)
                       VALUES (?, 'US', ?, ?, ?, ?)""",
                    (asset_id, FLOOR_PROTECTION, FLOOR_IDENTIFIER, expiry, SOURCE))
        for row in _rows(withdrawn or WITHDRAWN):
            code = (row.get("internal_code") or "").strip()
            asset = conn.execute(
                """SELECT a.id, a.is_marketed FROM assets a JOIN companies c
                     ON c.id = a.owner_company_id
                    WHERE c.ticker = ? AND a.internal_code = ?""",
                ((row.get("ticker") or "").strip().upper(), code)).fetchone()
            if asset is None or not asset["is_marketed"]:
                continue
            _snapshot(conn, code, {"asset_id": asset["id"], "is_marketed": 0, "was": 1,
                                   "withdrawn_on": row.get("withdrawn_on"),
                                   "source": row.get("source")})
            conn.execute("UPDATE assets SET is_marketed = 0, updated_at = datetime('now')"
                         " WHERE id = ?", (asset["id"],))
            retired += 1
        conn.commit()
    finally:
        conn.close()
    return {"added": added, "retired": retired}
