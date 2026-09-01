"""Revenue a company reports that no asset carries, forecast beside the assets.

Vertex reports Kalydeco, Orkambi and Symdeko as one line and never splits it. Biogen
books Ocrevus royalties that are not a product of its own. A company call measured only
against the product rows on file read a name as fully modelled while a third of its
revenue was invisible, and the model could never reconcile to the reported total.

A line is a marketed forecast without an asset. It carries a reported base, a growth
rate, margins and a discount rate, and runs through ``forecast.build`` unchanged, so it
fades, discounts and reports its notes exactly as a product does. Seeds live under
``data/company_lines/`` and follow the assumptions convention: one row per key, a source
on every row, and the file bootstraps without overwriting what is already on file.
"""

from __future__ import annotations

import csv
import pathlib

import forecast

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
SEED_DIR = DATA_DIR / "company_lines"

# What a line may carry. The marketed vocabulary, less an LOE: a line is not a molecule
# and has no patent to lose. A negative growth rate is how a line runs off.
KEYS = ("therapy_mode", "base_revenue", "revenue_growth_pct", "terminal_growth_pct",
        "growth_fade_years", "revenue_ceiling_musd", "cogs_pct", "sga_pct", "rd_pct",
        "tax_rate", "wacc", "risk_free", "erp", "beta", "cost_of_debt", "debt_weight",
        "forecast_start_year", "forecast_years", "pos")


def rows(conn, company_id: int, scenario: str = "base") -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT line, scenario, key, value, text_value, unit, source, note
             FROM company_lines WHERE company_id = ? AND scenario = ?
            ORDER BY line, key""", (company_id, scenario))]


def load(conn, company_id: int, scenario: str = "base") -> list[dict]:
    """[{line, scalars, unsourced}] for every line the company has, scenario over base."""
    merged: dict = {}
    for row in rows(conn, company_id, "base") + (
            rows(conn, company_id, scenario) if scenario != "base" else []):
        merged[(row["line"], row["key"])] = row
    lines: dict = {}
    for (line, key), row in merged.items():
        entry = lines.setdefault(line, {"line": line, "scalars": {}, "unsourced": []})
        entry["scalars"][key] = (row["value"] if row["value"] is not None
                                 else row["text_value"])
        if not (row["source"] or "").strip():
            entry["unsourced"].append(key)
    # Always marketed. The key is accepted in a seed for symmetry with an asset file
    # and ignored otherwise, because a line has no patients to build from.
    for entry in lines.values():
        entry["scalars"]["therapy_mode"] = "marketed"
        entry["scalars"].setdefault("pos", 1.0)
    return list(lines.values())


def build(entry: dict) -> dict:
    """The engine's result for one line, or {"ok": False, "missing": [...]}."""
    try:
        result = forecast.build({"scalars": entry["scalars"], "indications": [],
                                 "loe": None, "actuals": [], "phase": None})
    except forecast.ForecastError as err:
        return {"ok": False, "line": entry["line"], "missing": err.missing}
    return {"ok": True, "line": entry["line"], "result": result,
            "unsourced": entry.get("unsourced") or []}


def save(conn, company_id: int, line: str, incoming: list[dict],
         scenario: str = "base") -> int:
    """Upsert rows for one line. A row with neither value nor text is a delete."""
    written = 0
    for row in incoming:
        key = (row.get("key") or "").strip()
        if key not in KEYS:
            raise ValueError(f"'{key}' is not something a revenue line carries")
        value, text = row.get("value"), (row.get("text_value") or "").strip() or None
        if value is None and text is None:
            conn.execute("DELETE FROM company_lines WHERE company_id = ? AND line = ?"
                         "  AND scenario = ? AND key = ?", (company_id, line, scenario, key))
            continue
        conn.execute(
            """INSERT INTO company_lines
                   (company_id, line, scenario, key, value, text_value, unit, source,
                    note, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(company_id, line, scenario, key)
               DO UPDATE SET value = excluded.value, text_value = excluded.text_value,
                             unit = excluded.unit, source = excluded.source,
                             note = excluded.note, updated_at = datetime('now')""",
            (company_id, line, scenario, key, value, text, row.get("unit"),
             row.get("source"), row.get("note")))
        written += 1
    return written


def load_seeds(conn, directory=None) -> dict:
    """Load every CSV under data/company_lines/. Bootstraps and never overwrites."""
    source_dir = pathlib.Path(directory) if directory else SEED_DIR
    written = skipped = 0
    if not source_dir.exists():
        return {"written": 0, "skipped": 0}
    for path in sorted(source_dir.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                   ((row.get("ticker") or "").strip().upper(),)).fetchone()
            line = (row.get("line") or "").strip()
            key = (row.get("key") or "").strip()
            if not company or not line or key not in KEYS:
                skipped += 1
                continue
            scenario = (row.get("scenario") or "base").strip() or "base"
            if conn.execute(
                    "SELECT 1 FROM company_lines WHERE company_id = ? AND line = ?"
                    "  AND scenario = ? AND key = ?",
                    (company["id"], line, scenario, key)).fetchone():
                continue
            value = (row.get("value") or "").strip()
            conn.execute(
                """INSERT INTO company_lines (company_id, line, scenario, key, value,
                       text_value, unit, source, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (company["id"], line, scenario, key, float(value) if value else None,
                 (row.get("text_value") or "").strip() or None, row.get("unit"),
                 row.get("source"), row.get("note")))
            written += 1
    conn.commit()
    return {"written": written, "skipped": skipped}
