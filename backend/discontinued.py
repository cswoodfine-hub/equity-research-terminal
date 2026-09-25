"""Programmes a company has stopped, taken out of the pipeline without being deleted.

An asset derived from the trial registry stays a live programme for as long as the
registry lists it, and the registry lags the companies. Regeneron's 10-Q says REGN7999 is
discontinued while its trial still reads recruiting, and the extension study of Alector
and GSK's nivisnebart reads recruiting only because nobody updated the record after the
futility stop. A trial status cannot retire a programme, so the company's own word does.

``data/discontinued_programmes.csv`` names each one by ticker and the asset's name, the key
an assumption seed and the late-stage sort use, because asset ids are rebuilt with the
database and a name is not. Every row cites the statement, filing or registry record.

Applied on every refresh after the merges and the register, and rebuilt from the file each
time, so a retirement cannot outlive its row, and a duplicate folded into a live product
cannot carry its retirement with it. Nothing is deleted: the asset, its trials and its
snapshots stay, while the pipeline views, the late-stage coverage count and the valuation
skip it. A change of state is snapshotted, so when a programme was retired is on record.

A marketed product is not retired here. Withdrawal from sale is
``data/withdrawn_products.csv``'s job, and a product retired as a programme would vanish
from a portfolio it still sells in.
"""

from __future__ import annotations

import csv
import json
import pathlib

import db

DATA = db.BACKEND_DIR.parent / "data" / "discontinued_programmes.csv"
SOURCE = "discontinued_programmes"


def load(path=None) -> list[dict]:
    """The file's rows, comment lines skipped. A missing file is an empty register."""
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    return [row for row in csv.DictReader(lines)
            if (row.get("ticker") or "").strip() and (row.get("name") or "").strip()]


def _matches(conn, ticker: str, name: str) -> list:
    """Every asset of the company carrying the name as its generic, brand or code."""
    return conn.execute(
        """SELECT a.id, a.is_marketed FROM assets a JOIN companies c
             ON c.id = a.owner_company_id
            WHERE c.ticker = ?
              AND LOWER(?) IN (LOWER(TRIM(COALESCE(a.generic_name, ''))),
                               LOWER(TRIM(COALESCE(a.brand_name, ''))),
                               LOWER(TRIM(COALESCE(a.internal_code, ''))))
            ORDER BY a.id""", (ticker, name)).fetchall()


def apply(db_path=None, path=None) -> dict:
    """Rebuild the retired set from the file. Returns {retired, unmatched, marketed}.

    ``unmatched`` names rows whose asset is not on file, which is ordinary: a row can
    outlive the asset it names once a merge folds that asset away. ``marketed`` names rows
    that match only a product still on sale, which is refused rather than retired.
    """
    conn = db.get_connection(db_path)
    try:
        prior = {r["asset_id"] for r in conn.execute(
            "SELECT asset_id FROM retired_programmes")}
        wanted: dict[int, dict] = {}
        unmatched, marketed = [], []
        for row in load(path):
            ticker = row["ticker"].strip().upper()
            name = row["name"].strip()
            found = _matches(conn, ticker, name)
            if not found:
                unmatched.append(f"{ticker} {name}")
                continue
            live = [a["id"] for a in found if not a["is_marketed"]]
            if not live:
                marketed.append(f"{ticker} {name}")
                continue
            for asset_id in live:
                wanted[asset_id] = {"stopped_on": (row.get("stopped_on") or "").strip()
                                    or None,
                                    "basis": (row.get("basis") or "").strip()}
        for asset_id in wanted.keys() - prior:
            entry = wanted[asset_id]
            _snapshot(conn, asset_id, {"asset_id": asset_id, "retired": True,
                                       "stopped_on": entry["stopped_on"],
                                       "basis": entry["basis"]})
        for asset_id in prior - wanted.keys():
            _snapshot(conn, asset_id, {"asset_id": asset_id, "retired": False})
        conn.execute("DELETE FROM retired_programmes")
        conn.executemany(
            "INSERT INTO retired_programmes (asset_id, stopped_on, basis) VALUES (?, ?, ?)",
            [(asset_id, e["stopped_on"], e["basis"]) for asset_id, e in wanted.items()])
        conn.commit()
    finally:
        conn.close()
    return {"retired": len(wanted), "unmatched": unmatched, "marketed": marketed}


def retired(conn) -> dict[int, dict]:
    """{asset_id: {stopped_on, basis}} for every retired programme."""
    return {r["asset_id"]: {"stopped_on": r["stopped_on"], "basis": r["basis"]}
            for r in conn.execute(
                "SELECT asset_id, stopped_on, basis FROM retired_programmes")}


def _snapshot(conn, asset_id: int, payload: dict) -> None:
    """Keyed by ticker and the asset's own name, which survive a rebuild where the id
    does not, so a retirement and its reversal read as one entity's history."""
    row = conn.execute(
        """SELECT c.ticker, COALESCE(NULLIF(TRIM(a.generic_name), ''),
                                     NULLIF(TRIM(a.brand_name), ''), a.internal_code) AS name
             FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE a.id = ?""", (asset_id,)).fetchone()
    key = f"{row['ticker']}:{row['name']}" if row else f"asset:{asset_id}"
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
        " VALUES (?, 'asset', ?, ?)", (SOURCE, key, json.dumps(payload)))
