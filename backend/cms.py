"""CMS Medicare Spending by Drug, the real-world demand proxy.

Company revenue says what a drug earned; this says how many people took it. CMS
publishes two datasets, Part D for retail pharmacy drugs and Part B for the ones given
in a clinic, each with per-drug, per-year total spending, prescription claims and
distinct beneficiaries. The data API returns them as JSON with a column per metric per
year (Tot_Spndng_2024, Tot_Benes_2024, and so on).

This is the pure half: it turns a payload row into one record per year. The network
fetch and the brand match to an asset live in the fetcher. A metric CMS suppressed for
a small count comes back empty; it is read as null, never zero.
"""

from __future__ import annotations

import re

# The two datasets, resolved from the CMS DCAT catalogue. Part D is filtered to the
# Overall rows, which total a brand across its manufacturers; Part B has no
# manufacturer split.
PART_D_URL = ("https://data.cms.gov/data-api/v1/dataset/"
              "7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b/data")
PART_B_URL = ("https://data.cms.gov/data-api/v1/dataset/"
              "76a714ad-3a2c-43ac-b76d-9dadf8f7d890/data")

_YEAR = re.compile(r"Tot_Spndng_(\d{4})$")


def years_in(row: dict) -> list[int]:
    """The years a payload row carries, read from its spending columns."""
    return sorted(int(m.group(1)) for k in row
                  for m in [_YEAR.match(k)] if m)


def parse_row(row: dict, part: str) -> list[dict]:
    """One record per year for a CMS drug row: brand, part, and the four volume metrics.
    A year with no spending figure is skipped; a suppressed metric is null."""
    brand = (row.get("Brnd_Name") or "").strip()
    if not brand:
        return []
    out = []
    for year in years_in(row):
        spending = _num(row.get(f"Tot_Spndng_{year}"))
        if spending is None:
            continue                       # a year the drug was not on the programme
        out.append({
            "brand": brand,
            "part": part,
            "year": year,
            "total_spending": spending,
            "total_claims": _int(row.get(f"Tot_Clms_{year}")),
            "total_beneficiaries": _int(row.get(f"Tot_Benes_{year}")),
            "total_dosage_units": _num(row.get(f"Tot_Dsg_Unts_{year}")),
        })
    return out


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None
