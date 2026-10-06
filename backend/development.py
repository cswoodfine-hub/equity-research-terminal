"""Published per-phase drug development costs, read from data/development_costs.csv.

The cost to a pipeline asset's next gate is a view beside the valuation, never in it,
because the company R&D ratio already pays for today's trials. This module reads the
published figures it rests on: Sertkaya et al. 2024 (HHS ASPE), 2018 dollars, by
therapeutic area, as the point, and DiMasi, Grabowski and Hansen 2016, 2013 dollars, as
the high bound through its per-phase ratio to Sertkaya's All row. Every row is graded
analogue and carries its own price year: the book holds no price index, so nothing is
restated.
"""

from __future__ import annotations

import csv
import pathlib

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
COSTS = DATA_DIR / "development_costs.csv"

# The model's therapeutic areas in Sertkaya's own words. Sertkaya has no metabolic class,
# so the endocrine rates stand in for it: a mapping judgement, said in the basis. An area
# with no counterpart (Renal and hepatic, Healthy volunteers, Other, unknown) takes All.
AREA_TO_SOURCE = {
    "Oncology": "Oncology",
    "Immunology and inflammation": "Immunomodulation",
    "Metabolic": "Endocrine",
    "Neuroscience": "Central nervous system",
    "Cardiovascular": "Cardiovascular",
    "Infectious disease": "Anti-infective",
    "Respiratory": "Respiratory system",
    "Haematology": "Hematology",
    "Urology": "Genitourinary system",
    "Ophthalmology": "Ophthalmology",
}
AREA_JUDGEMENT = {"Metabolic": "Sertkaya has no metabolic class, so the endocrine rates "
                               "stand in for it"}
ALL = "All"
SOURCE_PRICE_YEAR = 2018


class CostTableError(ValueError):
    """A row of data/development_costs.csv that cannot be read as a sourced figure."""


# --- the published figures -----------------------------------------------------------

def costs_table(path=None) -> dict:
    """{(source_id, area, phase, measure): row} from data/development_costs.csv, value as
    a float. A row without a source or a price year, or with a value that is not a
    number, is refused: the whole file is, since a cost view on part of a table would
    silently fall back to another area's rate."""
    source = pathlib.Path(path) if path else COSTS
    out = {}
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
        for number, row in enumerate(reader, start=1):
            row = {k: (v or "").strip() for k, v in row.items()}
            key = (row.get("source_id"), row.get("area"), row.get("phase"),
                   row.get("measure"))
            if not row.get("source") or not row.get("price_year"):
                raise CostTableError(f"row {number} {key}: no source or price year")
            try:
                value = float(row["value"])
                year = int(row["price_year"])
            except (KeyError, TypeError, ValueError):
                raise CostTableError(f"row {number} {key}: value or price year is not a "
                                     f"number") from None
            out[key] = {**row, "value": value, "price_year": year,
                        "n": int(row["n"]) if row.get("n") else None}
    return out


def _figure(table: dict, area: str, phase: str, measure: str) -> dict:
    """Sertkaya's figure for the area, else its All column."""
    return (table.get(("sertkaya2024", area, phase, measure))
            or table[("sertkaya2024", ALL, phase, measure)])


def dimasi_ratio(table: dict) -> dict:
    """{phase: DiMasi's mean phase cost over Sertkaya's All programme cost}."""
    return {phase: table[("dimasi2016", ALL, phase, "phase_mean_musd")]["value"]
            / table[("sertkaya2024", ALL, phase, "programme_oop_musd")]["value"]
            for phase in ("2", "3")}


def cost_area(area: str | None) -> tuple:
    """(Sertkaya's area, how it was read)."""
    mapped = AREA_TO_SOURCE.get(area or "")
    if mapped is None:
        return ALL, (f"{area or 'no area on file'} has no counterpart in Sertkaya, so the "
                     f"All column is used")
    note = AREA_JUDGEMENT.get(area)
    return mapped, (f"{area} read as Sertkaya's {mapped}" + (f": {note}" if note else ""))


