"""A readout inside the business a product already sells, priced from a named scenario.

Fifty-eight readouts on the book sit in an indication the product's own pool already
covers. ``indication_layer`` refuses them on the evidence rather than for want of a seed:
Tezspire reads out again in asthma, Abrysvo again in RSV, Keytruda again in bladder, and
building a pool for those would count patients the marketed line is already sold to. The
stake tab called that ``in_the_base`` and priced it at nothing.

Nothing is the wrong answer. A second trial inside a disease the label covers moves
share, price or persistence, and a label that names a new population inside it moves the
rate the revenue grows at. The book has no way to derive how much, because the transition
tables say what fraction of programmes pass a gate, not what a win is worth to a product
already selling. That number is the analyst's, and the mechanism for an analyst's number
is already here: ``assumptions.load(conn, asset_id, scenario)`` merges a named scenario
over base, so a case can restate three figures without copying forty.

This file ties the two together. Each row names a readout by its registry id and the
scenario its success would put the product on, with the basis the restatement is written
from. The stake is then NPV(scenario) - NPV(base), risked at the published transitions
ahead of the study's phase, exactly as an indication layer is risked.

Keyed by ticker and the asset's name rather than by id, because ids are rebuilt with the
database and a name is not. Every row cites its basis. A row that names an asset the book
does not hold, or a scenario nobody has written, is reported by ``unresolved`` and caught
by a test, so a scenario cannot be named here and silently priced at base.
"""

from __future__ import annotations

import csv
import pathlib

import db

CURATED = db.BACKEND_DIR.parent / "data" / "catalyst_scenarios.csv"
FIELDS = ("ticker", "asset", "nct_id", "scenario", "basis")


def rows(path=None) -> list[dict]:
    """The file's rows, comment lines skipped. A missing file is an empty register."""
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    out = []
    for row in csv.DictReader(lines):
        got = {key: (row.get(key) or "").strip() for key in FIELDS}
        if got["ticker"] and got["asset"] and got["nct_id"] and got["scenario"]:
            out.append(got)
    return out


def _asset(conn, ticker: str, name: str):
    """The company's asset carrying the name as its brand, generic or code, or None."""
    found = conn.execute(
        """SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id
            WHERE c.ticker = ?
              AND LOWER(?) IN (LOWER(TRIM(COALESCE(a.generic_name, ''))),
                               LOWER(TRIM(COALESCE(a.brand_name, ''))),
                               LOWER(TRIM(COALESCE(a.internal_code, ''))))
            ORDER BY a.id""", (ticker.upper(), name)).fetchall()
    return found[0]["id"] if len(found) == 1 else None


def _written(conn, asset_id: int, scenario: str) -> bool:
    """Whether the asset has any assumption row restating something in this scenario."""
    return conn.execute(
        "SELECT 1 FROM assumptions WHERE asset_id = ? AND scenario = ? LIMIT 1",
        (asset_id, scenario)).fetchone() is not None


def load(conn, path=None) -> dict:
    """{(asset_id, nct_id): {"scenario", "basis"}} for every row that resolves.

    A row whose asset is not on the book, or whose scenario nobody has written, is left
    out here and named by ``unresolved``.
    """
    out: dict = {}
    for row in rows(path):
        asset_id = _asset(conn, row["ticker"], row["asset"])
        if asset_id is None or not _written(conn, asset_id, row["scenario"]):
            continue
        out[(asset_id, row["nct_id"].upper())] = {"scenario": row["scenario"],
                                                  "basis": row["basis"]}
    return out


def unresolved(conn, path=None) -> list[str]:
    """Rows the book cannot act on, each said in one line and why.

    Two failures, and they are different. An asset the file names and the book does not
    hold is ordinary once a merge folds an asset away, but it still means the readout is
    priced at nothing while the file claims otherwise. A scenario named with no rows
    written against it is worse: ``assumptions.load`` would fall back to base on every
    key, the delta would be zero, and the row would read as priced while saying nothing.
    """
    out = []
    for row in rows(path):
        asset_id = _asset(conn, row["ticker"], row["asset"])
        if asset_id is None:
            out.append(f"{row['ticker']} {row['asset']}: no single asset of that name")
            continue
        if not _written(conn, asset_id, row["scenario"]):
            out.append(f"{row['ticker']} {row['asset']}: no assumption row is written "
                       f"in scenario '{row['scenario']}'")
    return out
