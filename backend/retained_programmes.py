"""Programmes a seller kept when a company in the universe bought it.

Pfizer bought Biohaven Pharmaceuticals in 2022 for its migraine franchise. Just before
the deal closed Biohaven spun off Biohaven Ltd, which kept every development compound
that was not a CGRP drug. The registry still files the older studies of troriluzole and
taldefgrobep alfa under Biohaven Pharmaceuticals, Inc., the entity Pfizer now owns, so the
acquired-sponsor search took both drugs for Pfizer's and put them in its Phase 3 pipeline.

The sponsor name cannot tell them apart: rimegepant's studies carry the same sponsor and
are Pfizer's. What does is the acquirer's own filing saying what the seller kept, so
``data/retained_by_seller.csv`` names each programme with that quote. On every refresh,
after the trials are fetched and before the pipeline is derived, the studies naming a
kept programme are released from the acquirer: each keeps its record and loses its
sponsor company and asset. The derived pairs of the emptied programme row go with them,
and the pruning that follows removes the row itself. What is released is snapshotted
first.
"""

from __future__ import annotations

import csv
import json
import pathlib

import db
import trial_mapping

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "retained_by_seller.csv"


def load(path=None) -> list[dict]:
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
        return [r for r in rows
                if (r.get("ticker") or "").strip() and (r.get("programme") or "").strip()]


def _names(row) -> set:
    return set().union(*(trial_mapping.aliases(row[f]) for f in
                         ("brand_name", "generic_name", "internal_code") if row[f]))


def release(db_path=None, path=None) -> dict:
    """Unbind the acquirer from every study and derived row of a programme the seller
    kept. Idempotent: a released study has no sponsor company left to match."""
    conn = db.get_connection(db_path)
    released = unpaired = 0
    try:
        for kept in load(path):
            company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                   (kept["ticker"].strip().upper(),)).fetchone()
            if company is None:
                continue
            wanted = trial_mapping.aliases(kept["programme"])
            studies = {}
            for table in ("trials", "completed_trials"):
                for row in conn.execute(
                        f"""SELECT DISTINCT t.nct_id, i.name FROM {table} t
                              JOIN trial_interventions i ON i.nct_id = t.nct_id
                             WHERE t.sponsor_company_id = ?""", (company["id"],)):
                    if trial_mapping.aliases(row["name"]) & wanted:
                        studies.setdefault(table, set()).add(row["nct_id"])
            assets = [r["id"] for r in conn.execute(
                "SELECT id, brand_name, generic_name, internal_code FROM assets"
                " WHERE owner_company_id = ? AND is_marketed = 0", (company["id"],))
                if _names(r) & wanted]
            if not (studies or assets):
                continue
            marks = ", ".join("?" for _ in assets)
            pairs = [dict(r) for r in conn.execute(
                f"SELECT * FROM asset_indications WHERE asset_id IN ({marks})",
                assets)] if assets else []
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
                " VALUES ('retained_by_seller', 'programme', ?, ?)",
                (f"{kept['ticker'].strip().upper()}:{kept['programme'].strip()}",
                 json.dumps({"studies": {t: sorted(n) for t, n in studies.items()},
                             "assets": assets, "asset_indications": pairs,
                             "seller": kept.get("seller"),
                             "accession": kept.get("accession")})))
            for table, ncts in studies.items():
                for nct in sorted(ncts):
                    conn.execute(f"UPDATE {table} SET sponsor_company_id = NULL,"
                                 f" asset_id = NULL WHERE nct_id = ?", (nct,))
                    released += 1
            if assets:
                unpaired += conn.execute(
                    f"DELETE FROM asset_indications WHERE asset_id IN ({marks})",
                    assets).rowcount
        conn.commit()
    finally:
        conn.close()
    return {"released": released, "pairs_removed": unpaired}
