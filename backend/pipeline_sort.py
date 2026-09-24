"""The late-stage gap, sorted by what each row actually is before any of it is priced.

The book counts every unmodelled asset at Phase 2 or later as a gap to be researched, and
half of them are not new medicines. Leqvio, Arexvy, Shingrix and Vyvgart Hytrulo each
sat in the gap under a development code or a formulation name, so pricing the gap row by
row would value them a second time. So each row is sorted first, into one of:

  NEW             a medicine the book does not hold in any form. The only class worth a
                  price and an uptake curve.
  DUPLICATE       the same molecule as something the book already carries, marketed or
                  modelled, under another name: a code, a misspelling, a second row.
  LINE_EXTENSION  a marketed molecule in a new formulation, dose, device or indication.
                  Its value belongs to the product it extends, not to a new line.
  DEAD            a programme the company has stopped, or whose pivotal trial failed and
                  which has no path left.
  REGIMEN         a combination of molecules valued elsewhere, named as one row because
                  the registry names the arms.
  NOT_A_PROGRAMME a comparator, a vehicle, a procedure or a supportive product the
                  registry lists as an intervention. Nothing to develop, nothing to value.

The sort lives in ``data/pipeline_sort.csv``, keyed like an assumption seed by ticker and
the asset's name, because asset ids are rebuilt with the database and a name is not.
``population`` is the set it covers, defined here so the count can be reproduced: an
earlier pass sized it at 353 on a database that was never published, and nothing recorded
how.
"""

from __future__ import annotations

import csv
import pathlib

import db

SORT_CSV = db.BACKEND_DIR.parent / "data" / "pipeline_sort.csv"

CLASSES = ("NEW", "DUPLICATE", "LINE_EXTENSION", "DEAD", "REGIMEN", "NOT_A_PROGRAMME")
LATE_PHASES = ("Phase 2", "Phase 2/3", "Phase 3")
# Roche's late stage was researched on its own when its workbook unblocked it, so the
# sort covers everyone else.
EXCLUDED_TICKERS = ("ROG",)


def name_of(row) -> str:
    """The name a sort row is keyed by: the generic name, else the brand, else the code.
    The same fallback an assumption seed resolves through."""
    for key in ("generic_name", "brand_name", "internal_code"):
        value = (row[key] or "").strip()
        if value:
            return value
    return ""


def population(conn) -> list[dict]:
    """Every asset the sort covers: not marketed, no assumptions, at least one indication
    at Phase 2, 2/3 or 3, and not excluded. Returned with the keys a sort row joins on."""
    phases = ",".join("?" * len(LATE_PHASES))
    excluded = ",".join("?" * len(EXCLUDED_TICKERS))
    rows = conn.execute(
        f"""SELECT a.id, c.ticker, a.generic_name, a.brand_name, a.internal_code
              FROM assets a JOIN companies c ON c.id = a.owner_company_id
             WHERE a.is_marketed = 0
               AND c.ticker NOT IN ({excluded})
               AND NOT EXISTS (SELECT 1 FROM assumptions s WHERE s.asset_id = a.id)
               AND EXISTS (SELECT 1 FROM asset_indications ai
                            WHERE ai.asset_id = a.id AND ai.phase IN ({phases}))
             ORDER BY c.ticker, a.id""",
        (*EXCLUDED_TICKERS, *LATE_PHASES)).fetchall()
    return [{"asset_id": r["id"], "ticker": r["ticker"], "name": name_of(r)} for r in rows]


def load(path=None) -> dict[tuple[str, str], dict]:
    """The sort, as {(ticker, lower-cased name): row}. Comment lines are skipped."""
    source = pathlib.Path(path) if path else SORT_CSV
    if not source.exists():
        return {}
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    return {(row["ticker"].strip().upper(), row["name"].strip().lower()): row
            for row in csv.DictReader(lines)}


def unsorted(conn, path=None) -> list[dict]:
    """Population rows the sort does not yet cover. New rows arrive with every trials
    refresh, so this is the list to work through, not a failure."""
    sort = load(path)
    return [row for row in population(conn)
            if (row["ticker"], row["name"].lower()) not in sort]


def counts(path=None) -> dict[str, int]:
    """How many rows the sort puts in each class."""
    out = {cls: 0 for cls in CLASSES}
    for row in load(path).values():
        out[row["class"]] = out.get(row["class"], 0) + 1
    return out
