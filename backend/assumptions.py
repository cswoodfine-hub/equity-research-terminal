"""Loading, saving and seeding the assumption layer the forecast engine computes from.

The engine (``forecast.py``) is pure; this module is everything around it: reading an
asset's assumption rows into the nested dict the engine takes, upserting edits, the
curated seed CSV that carries the CASGEVY workbook's numbers with their own stated
sources, the phase and erosion default files, and the xlsx export an analyst can vet in
Excel. The bargain throughout is the one the roadmap fixed: the analyst owns every
number and every number carries its source; the terminal computes and never invents.
"""

from __future__ import annotations

import csv
import json
import pathlib

import db
import forecast
import product_profile

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
SEED_DIR = DATA_DIR / "assumptions"
POS_DEFAULTS = DATA_DIR / "pos_defaults.csv"
EROSION_DEFAULTS = DATA_DIR / "erosion_defaults.csv"

# What the empty state asks for, per mode. Everything else refines rather than gates.
TEMPLATE = {
    "one_time": (
        ("therapy_mode", "one_time", "text"),
        ("net_price_per_patient", "net price per patient, mm USD", "value"),
        ("cogs_per_patient", "cost of goods per patient, mm USD", "value"),
        ("sga_pct", "SG&A as a share of revenue", "value"),
        ("rd_pct", "R&D as a share of revenue", "value"),
        ("tax_rate", "effective tax rate", "value"),
        ("wacc", "discount rate, or supply risk_free/erp/beta/cost_of_debt/debt_weight",
         "value"),
        ("forecast_start_year", "first DCF year", "value"),
        ("forecast_years", "DCF horizon, default 10", "value"),
        ("new_patients", "per indication, one row per year; or supply the pool inputs "
         "prevalence/eligible_pct/incidence/penetration_peak_pct/ramp_midpoint_year/"
         "ramp_steepness", "series"),
    ),
    "chronic": (
        ("therapy_mode", "chronic", "text"),
        ("net_price_per_patient", "annual net price per patient", "value"),
        ("cogs_pct", "cost of goods as a share of revenue", "value"),
        ("sga_pct", "SG&A as a share of revenue", "value"),
        ("rd_pct", "R&D as a share of revenue", "value"),
        ("tax_rate", "effective tax rate", "value"),
        ("wacc", "discount rate or CAPM components", "value"),
        ("forecast_start_year", "first DCF year", "value"),
        ("new_patients", "treated patients per year, per indication", "series"),
    ),
}


def _defaults(path, key_field):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    out = {}
    for row in csv.DictReader(rows):
        entry = dict(row)
        for field in ("pos", "year1_pct", "decay_pct"):
            if entry.get(field) not in (None, ""):
                entry[field] = float(entry[field])
        out[row[key_field]] = entry
    return out


def pos_defaults() -> dict:
    """The curated phase ramp, keyed by phase, each row carrying its source."""
    return _defaults(POS_DEFAULTS, "phase")


def erosion_defaults() -> dict:
    """The curated erosion shapes, keyed by modality, each row carrying its source."""
    return _defaults(EROSION_DEFAULTS, "modality")


# --- reading an asset's assumptions -----------------------------------------

def rows(conn, asset_id: int, scenario: str = "base") -> list[dict]:
    """Every assumption row for one asset and scenario, for the editor."""
    return [dict(r) for r in conn.execute(
        """SELECT a.id, a.asset_id, a.indication_id, i.name AS indication,
                  a.region, a.scenario, a.key, a.year, a.value, a.text_value,
                  a.unit, a.source, a.note, a.as_of, a.updated_at
             FROM assumptions a LEFT JOIN indications i ON i.id = a.indication_id
            WHERE a.asset_id = ? AND a.scenario = ?
            ORDER BY a.indication_id IS NOT NULL, i.name, a.key, a.year""",
        (asset_id, scenario))]


def load(conn, asset_id: int, scenario: str = "base") -> dict:
    """The engine's input dict for one asset: scalars, indications, LOE, actuals, phase.

    Scenario rows fall back to base where the scenario does not restate them, which is
    how a bear case can change three numbers without copying forty.
    """
    merged: dict = {}
    for row in rows(conn, asset_id, "base") + (
            rows(conn, asset_id, scenario) if scenario != "base" else []):
        key = (row["indication_id"], row["region"], row["key"], row["year"])
        merged[key] = row

    scalars: dict = {}
    indications: dict = {}
    for (indication_id, _region, key, year), row in merged.items():
        value = row["value"] if row["value"] is not None else row["text_value"]
        if indication_id is None:
            if year is None:
                scalars[key] = value
            continue
        entry = indications.setdefault(
            indication_id, {"name": row["indication"], "scalars": {}, "series": {}})
        if year is None:
            entry["scalars"][key] = value
        else:
            entry["series"].setdefault(key, {})[int(year)] = value

    asset = conn.execute(
        "SELECT modality, brand_name, generic_name, owner_company_id FROM assets"
        " WHERE id = ?", (asset_id,)).fetchone()
    loe = product_profile._loe(conn, asset_id)
    loe_year = int(loe["loe"][:4]) if loe and loe.get("loe") else None
    actuals = [dict(r) for r in conn.execute(
        "SELECT fiscal_year, period, value FROM asset_revenue"
        " WHERE asset_id = ? ORDER BY fiscal_year, period", (asset_id,))]
    # Actuals are stored in dollars; assumptions and the workbook run in millions.
    for row in actuals:
        row["value"] = row["value"] / 1e6 if row["value"] is not None else None
    phase = conn.execute(
        """SELECT phase FROM asset_indications WHERE asset_id = ?
            ORDER BY CASE phase WHEN 'Phase 4' THEN 6 WHEN 'Phase 3' THEN 5
                     WHEN 'Phase 2/3' THEN 4 WHEN 'Phase 2' THEN 3
                     WHEN 'Phase 1/2' THEN 2 WHEN 'Phase 1' THEN 1 ELSE 0 END DESC
            LIMIT 1""", (asset_id,)).fetchone()

    return {
        "scalars": scalars,
        "indications": list(indications.values()),
        "loe": {"year": loe_year, "basis": loe.get("basis")} if loe_year else None,
        "actuals": actuals,
        "phase": phase["phase"] if phase else None,
        "modality": asset["modality"] if asset else None,
        "pos_defaults": pos_defaults(),
        "erosion_defaults": erosion_defaults(),
    }


# --- writing -----------------------------------------------------------------

def save(conn, asset_id: int, incoming: list[dict]) -> int:
    """Upsert assumption rows for one asset. Returns rows written.

    A row is identified by (indication, region, scenario, key, year); writing one that
    exists replaces its value and provenance. A row whose value and text are both empty
    deletes, which is how the editor removes a line.
    """
    written = 0
    for row in incoming:
        key = (row.get("key") or "").strip()
        if not key:
            raise ValueError("an assumption row needs a key")
        indication_id = row.get("indication_id")
        region = (row.get("region") or "US").strip()
        scenario = (row.get("scenario") or "base").strip()
        year = row.get("year")
        value, text = row.get("value"), (row.get("text_value") or "").strip() or None
        if value is None and text is None:
            conn.execute(
                """DELETE FROM assumptions WHERE asset_id = ?
                    AND IFNULL(indication_id, 0) = IFNULL(?, 0) AND region = ?
                    AND scenario = ? AND key = ? AND IFNULL(year, 0) = IFNULL(?, 0)""",
                (asset_id, indication_id, region, scenario, key, year))
            continue
        conn.execute(
            """INSERT INTO assumptions
                   (asset_id, indication_id, region, scenario, key, year, value,
                    text_value, unit, source, note, as_of, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(asset_id, IFNULL(indication_id, 0), region, scenario, key,
                           IFNULL(year, 0))
               DO UPDATE SET value = excluded.value, text_value = excluded.text_value,
                             unit = excluded.unit, source = excluded.source,
                             note = excluded.note, as_of = excluded.as_of,
                             updated_at = datetime('now')""",
            (asset_id, indication_id, region, scenario, key, year, value, text,
             row.get("unit"), row.get("source"), row.get("note"), row.get("as_of")))
        written += 1
    return written


def snapshot(conn, asset_id: int, scenario: str, result: dict) -> None:
    """Write the (assumptions, outputs) pair to the snapshots table.

    Source 'forecast', so forecast history sits beside every other history the terminal
    keeps and is never overwritten. This is what a later build diffs pre-event against.
    """
    payload = {
        "scenario": scenario,
        "assumptions": rows(conn, asset_id, scenario),
        "rnpv": result.get("rnpv"), "npv": result.get("npv"),
        "wacc": result.get("wacc"), "pos": result.get("pos"),
        "revenue": result.get("revenue_after_loe"), "years": result.get("years"),
    }
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
        " VALUES ('forecast', 'asset', ?, ?)",
        (str(asset_id), json.dumps(payload)))


# --- the curated seed --------------------------------------------------------

def load_seeds(conn, directory=None) -> dict:
    """Load every CSV under data/assumptions/ into the table. Returns counts.

    Follows the asset_alias_map pattern: the file resolves ticker and brand to an asset,
    and an indication by name, so a rebuilt database reseeds itself. Rows only carry what
    an analyst wrote down; a file for a product not on file is skipped, not an error.

    The file bootstraps and never overwrites: a key that already has a row keeps it, so
    an edit made in the terminal survives every later reseed. Changing a seeded number
    therefore means editing it where it lives, not editing the file and waiting.
    """
    source_dir = pathlib.Path(directory) if directory else SEED_DIR
    written = skipped = 0
    if not source_dir.exists():
        return {"written": 0, "skipped": 0}
    for path in sorted(source_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            ticker = (row.get("ticker") or "").strip().upper()
            brand = (row.get("brand") or "").strip()
            asset = conn.execute(
                """SELECT a.id FROM assets a JOIN companies c
                     ON c.id = a.owner_company_id
                    WHERE c.ticker = ? AND LOWER(TRIM(a.brand_name)) = LOWER(?)
                    ORDER BY a.is_marketed DESC, a.id LIMIT 1""",
                (ticker, brand)).fetchone()
            if not asset:
                skipped += 1
                continue
            indication_id = None
            if (row.get("indication") or "").strip():
                ind = conn.execute(
                    "SELECT id FROM indications WHERE LOWER(name) = LOWER(?)",
                    (row["indication"].strip(),)).fetchone()
                if not ind:
                    skipped += 1
                    continue
                indication_id = ind["id"]
            value = row.get("value")
            year = int(row["year"]) if (row.get("year") or "").strip() else None
            exists = conn.execute(
                """SELECT 1 FROM assumptions WHERE asset_id = ?
                    AND IFNULL(indication_id, 0) = IFNULL(?, 0) AND region = ?
                    AND scenario = ? AND key = ? AND IFNULL(year, 0) = IFNULL(?, 0)""",
                (asset["id"], indication_id, row.get("region") or "US",
                 row.get("scenario") or "base", row.get("key"), year)).fetchone()
            if exists:
                continue
            written += save(conn, asset["id"], [{
                "indication_id": indication_id,
                "region": row.get("region") or "US",
                "scenario": row.get("scenario") or "base",
                "key": row.get("key"),
                "year": year,
                "value": float(value) if value not in (None, "") else None,
                "text_value": row.get("text_value"),
                "unit": row.get("unit"), "source": row.get("source"),
                "note": row.get("note"), "as_of": row.get("as_of"),
            }])
    conn.commit()
    return {"written": written, "skipped": skipped}


# --- the Excel handoff -------------------------------------------------------

def export_xlsx(conn, asset_id: int, scenario: str, result: dict | None) -> bytes:
    """The canonical two-sheet workbook: Assumptions to vet, Forecast to read.

    The assumptions sheet round-trips: its columns are the seed CSV's, so a vetted copy
    can come straight back in through the uploader.
    """
    import io

    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Assumptions"
    header = ("indication", "region", "scenario", "key", "year", "value", "text_value",
              "unit", "source", "note")
    sheet.append(header)
    for row in rows(conn, asset_id, scenario):
        sheet.append(tuple(row.get(k) if k != "indication" else row.get("indication")
                           for k in header))

    if result:
        out = book.create_sheet("Forecast")
        out.append(("year",) + tuple(result["years"]))
        out.append(("new patients",) + tuple(
            round(v, 1) for v in result["patients"]["total"]))
        out.append(("revenue, mm",) + tuple(
            round(v, 1) for v in result["revenue_after_loe"]))
        out.append(())
        for label, key in (("wacc", "wacc"), ("pos", "pos"), ("npv, mm", "npv"),
                           ("rnpv, mm", "rnpv")):
            out.append((label, result.get(key)))
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()
