"""Revenue lines that name a disease instead of a drug.

Some filers disaggregate revenue by franchise. GSK reports "Shingles" at 3.6bn,
"Meningitis" at 1.6bn and "Influenza" at 0.3bn, and none of those is a product, so none
can be dated and GSK could not be measured at all. There is no free way to resolve them:
openFDA's label endpoint returns 404 for every vaccine, so there is no indication text to
match a disease against, and the NDC register gives brands without saying what they treat.

So the membership is curated, in data/franchise_map.csv, and only the membership. Which
products a franchise covers is a stable fact about a portfolio that a reader can check
and correct. Every date still comes from the register, so a row in that file cannot make
a portfolio look newer than the data says it is.

Two refusals, both of which matter more than the resolutions:

A franchise whose members straddle the five-year cutoff has no answer. GSK's meningitis
revenue comes from Bexsero and Menveo, first marketed in 2016 and 2017, and from Penmenvy
in 2025, and there is no way to say how the 1.6bn splits between them. Picking the member
that suits would be inventing the number.

A franchise containing a seasonally reformulated vaccine has no usable date. The register
holds one entry per formulation and the old ones are delisted, so Fluarix reads
2026-07-01 for a franchise first licensed decades earlier. That is the one direction the
error must never run, and the only date available runs in it.
"""

from __future__ import annotations

import csv
import pathlib

import approval_dates

_PATH = (pathlib.Path(__file__).resolve().parent.parent / "data" / "franchise_map.csv")

# The refusal reasons, returned instead of a date so the caller can say why.
STRADDLES = "franchise members straddle the cutoff"
SEASONAL = "franchise contains a seasonally reformulated vaccine"


def load(path=None) -> dict:
    """{(ticker, normalised franchise): [(brand, seasonal, note)]} from the curated file.

    Keyed on the normalised label so "RSVArexvy" and "RSV Arexvy" reach the same row,
    which matters because the filing runs them together.
    """
    source = pathlib.Path(path) if path else _PATH
    if not source.exists():
        return {}
    out: dict = {}
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    for row in csv.DictReader(rows):
        ticker = (row.get("ticker") or "").strip().upper()
        franchise = approval_dates.normalise(row.get("franchise") or "")
        brand = (row.get("brand") or "").strip()
        if not ticker or not franchise or not brand:
            continue
        seasonal = (row.get("seasonal") or "").strip() in ("1", "true", "yes")
        out.setdefault((ticker, franchise), []).append(
            (brand, seasonal, (row.get("note") or "").strip()))
    return out


def _brand_dates(conn, company_id: int, brands: list) -> dict:
    """{brand: earliest date on file} from the register and the approvals table."""
    dates: dict = {}
    for brand in brands:
        row = conn.execute(
            "SELECT MIN(first_marketed) d FROM ndc_products"
            "  WHERE company_id = ? AND upper(brand_name) = upper(?)",
            (company_id, brand)).fetchone()
        found = row["d"] if row else None
        approved = conn.execute(
            "SELECT MIN(ap.approval_date) d FROM approvals ap"
            "  JOIN assets a ON a.id = ap.asset_id"
            " WHERE a.owner_company_id = ? AND upper(a.brand_name) = upper(?)",
            (company_id, brand)).fetchone()
        # The approval is the better record where both exist, since the register gives a
        # marketing date that can only be later.
        if approved and approved["d"]:
            found = approved["d"] if not found else min(found, approved["d"])
        if found:
            dates[brand] = found
    return dates


def resolve(conn, ticker: str, label: str, cutoff: str, mapping: dict | None = None):
    """(date, route) for a franchise revenue line, or (None, reason).

    A date only when every member of the franchise sits on the same side of the cutoff,
    in which case the oldest member's date stands for the line: the answer to "is this
    revenue from a recent approval" is the same whichever member earned it.
    """
    mapping = load() if mapping is None else mapping
    members = mapping.get((ticker.upper(), approval_dates.normalise(label)))
    if not members:
        return None, None

    if any(seasonal for _brand, seasonal, _note in members):
        return None, SEASONAL

    company = conn.execute(
        "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
    if company is None:
        return None, None
    dates = _brand_dates(conn, company["id"], [b for b, _s, _n in members])
    if not dates or len(dates) < len(members):
        # A member with no date at all could sit on either side, so the franchise is as
        # unresolved as if the members disagreed.
        return None, STRADDLES
    if all(d >= cutoff for d in dates.values()) or all(d < cutoff for d in dates.values()):
        return min(dates.values()), "curated franchise membership"
    return None, STRADDLES
