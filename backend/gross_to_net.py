"""What the house gross-to-net convention is worth, measured against a negotiated price.

Almost every pipeline asset in the book is priced off a marketed comparator's CMS
spending per Medicare beneficiary, cut by a gross-to-net share. The two halves of that
are both wrong, in opposite directions, and nobody had checked whether they cancel.

CMS spending is gross of the rebates a manufacturer pays, so it is above a net price.
Against that, spending per beneficiary is not a year of therapy: the denominator is every
patient who filled the drug at any point in the year, and starters, stoppers and switchers
fill only part of it, so the figure is below an annual price. Measured against each drug's
own schedule the coverage runs from 48% of a year (Verzenio, Xtandi) to 124% (Leqvio).

The Inflation Reduction Act settles it. CMS publishes a Maximum Fair Price per 30-day
equivalent supply for each selected drug, which is a real negotiated net price on a real
annual basis, and the ten cycle-one drugs are all in the demand table. Comparing the two
says what the convention is worth, per drug, from free data already on file.

It comes out at a median 96% of the negotiated price across the nine drugs that carry
both, so the two errors do cancel, and the convention is a little conservative rather
than wrong. The spread is the thing to respect: 65% on Imbruvica, whose beneficiaries
fill 358 of 730 capsules, against 167% on Januvia, where the rebate is far deeper than
half. So the convention is sound for a book and loose for one asset, and an asset with a
published annual list price should use that instead.

Two things this is not. A Maximum Fair Price is a ceiling CMS negotiated for a drug seven
or more years past launch that it selected because it was expensive and had no generic,
so it sits below what a fresh launch realises, and a convention landing at 96% of it is
therefore conservative for a launch rather than calibrated to one. And it says nothing
about Part B, where the convention is not this one: Part B pays 106% of average sales
price, which is already net of manufacturer discounts, so the deduction there is the 6%
add-on and is derived from the statute rather than assumed.
"""

from __future__ import annotations

import statistics

DAYS_IN_MONTH = 30
DAYS_IN_YEAR = 365

# The share of a gross figure the house convention says a manufacturer keeps in a
# competitive Part D retail class. This module measures it; it does not set it.
PART_D_CONVENTION = 0.5


def annual_mfp(mfp_30des: float) -> float:
    """A Maximum Fair Price per 30-day equivalent supply, as a year."""
    return mfp_30des * DAYS_IN_YEAR / DAYS_IN_MONTH


def calibration(conn, *, convention: float = PART_D_CONVENTION,
                effective_from: str = "2026-01-01") -> dict:
    """The convention against every negotiated price the demand table can answer.

    One row per drug: the negotiated annual price, the CMS gross spending per
    beneficiary, what the convention makes of it, and the ratio. A drug CMS has
    negotiated but the demand table does not carry is reported, not dropped, because a
    missing comparator is the reason a calibration would be quietly built on fewer drugs
    than it claims.
    """
    drugs = conn.execute(
        "SELECT drug, MIN(mfp_30des) AS mfp FROM negotiated_prices"
        " WHERE effective_from = ? AND mfp_30des IS NOT NULL"
        " GROUP BY drug ORDER BY drug", (effective_from,)).fetchall()
    rows, missing = [], []
    for drug in drugs:
        demand = conn.execute(
            "SELECT d.total_spending AS spending, d.total_beneficiaries AS benes,"
            "       d.total_dosage_units AS units, d.year"
            "  FROM drug_demand d JOIN assets a ON a.id = d.asset_id"
            " WHERE UPPER(a.brand_name) = ? AND d.part = 'D'"
            "   AND d.total_beneficiaries IS NOT NULL"
            " ORDER BY d.year DESC LIMIT 1", (drug["drug"],)).fetchone()
        if demand is None:
            missing.append(drug["drug"])
            continue
        per_bene = demand["spending"] / demand["benes"]
        negotiated = annual_mfp(drug["mfp"])
        rows.append({
            "drug": drug["drug"], "year": demand["year"],
            "mfp_30des": drug["mfp"], "negotiated_annual": negotiated,
            "gross_per_beneficiary": per_bene,
            "convention_net": per_bene * convention,
            "ratio": (per_bene * convention) / negotiated if negotiated else None,
            "units_per_beneficiary": (demand["units"] / demand["benes"]
                                      if demand["units"] else None)})
    ratios = sorted(r["ratio"] for r in rows if r["ratio"])
    return {"convention": convention, "rows": rows, "missing": missing,
            "median": statistics.median(ratios) if ratios else None,
            "low": ratios[0] if ratios else None,
            "high": ratios[-1] if ratios else None,
            "n": len(ratios)}
