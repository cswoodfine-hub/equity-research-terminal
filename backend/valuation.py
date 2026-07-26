"""Valuation scaffold: the protected-revenue value of the marketed portfolio.

A marketed drug is worth, roughly, the cash it throws off while it is still protected.
This takes each product's latest reported revenue as a flat run-rate, discounts it over
the years remaining to loss of exclusivity, and sums the result per company. It is a
scaffold, not a model: the run-rate is held flat, post-LOE generic revenue is counted as
zero, and the discount rate is one stated number. Every input is real, so a product with
revenue but no LOE date, or an LOE date but no revenue, is listed unvalued rather than
filled in.

The risk in a risk-adjusted NPV is the chance an asset ever reaches the market. For a
marketed drug that is one, so this is an NPV. The phase-to-probability benchmarks below
are the framework for a pipeline asset, but no free source gives a pipeline drug's peak
sales, so this values only what already sells and puts no number on the pipeline.
"""

from __future__ import annotations

import datetime as dt

import asset_revenue
import db
import fx

# The discount rate applied to the protected cash stream. One stated number, not a term
# structure, and exposed so a caller can re-run the scaffold at a different rate.
DISCOUNT_RATE = 0.10

# Likelihood of approval by phase, the published clinical-development success rates (BIO
# and Informa). Documentation for extending the scaffold to the pipeline; a product that
# is already marketed is 1.0, which is the only value this layer actually applies.
POS_BY_PHASE = {
    "Phase 1": 0.10, "Phase 1/2": 0.12, "Phase 2": 0.20, "Phase 2/3": 0.26,
    "Phase 3": 0.55, "Filed": 0.85, "Approved": 1.0, "Marketed": 1.0,
}

# Orphan exclusivity covers one orphan indication and lapses without the product losing
# anything, so it does not bound a revenue stream and is excluded, the same rule the LOE
# cliff uses.
NOT_A_CLIFF = "orphan exclusivity"


def annuity_factor(years: int, rate: float = DISCOUNT_RATE) -> float:
    """Present value of one unit a year for ``years`` years at ``rate``. Zero once the
    product is at or past its LOE, since the protected stream has run out."""
    if years is None or years <= 0:
        return 0.0
    return (1 - (1 + rate) ** -years) / rate


def company_valuation(db_path, ticker: str, rate: float = DISCOUNT_RATE) -> dict | None:
    today = dt.date.today()
    rates = fx.latest_usd_rates(db_path)
    conn = db.get_connection(db_path)
    try:
        company_id = asset_revenue._company_id(conn, ticker)
        if company_id is None:
            return None
        revenue = asset_revenue._latest_revenue(conn, company_id)
        loe_rows = conn.execute(
            """
            SELECT a.id AS asset_id, a.brand_name, a.generic_name, a.modality,
                   a.internal_code,
                   (SELECT MAX(e.expiry_date) FROM exclusivities e
                     WHERE e.asset_id = a.id
                       AND COALESCE(e.protection_type, '') != ?) AS book_loe,
                   bl.loe_date AS bio_loe, bl.basis AS bio_basis
              FROM assets a
              LEFT JOIN biologic_loe bl ON bl.asset_id = a.id
             WHERE a.owner_company_id = ?
            """,
            (NOT_A_CLIFF, company_id),
        ).fetchall()
        latest_year = conn.execute(
            "SELECT MAX(year) FROM drug_demand").fetchone()[0]
        demand = {r["asset_id"]: r["spend"] for r in conn.execute(
            "SELECT asset_id, SUM(total_spending) AS spend FROM drug_demand"
            " WHERE year = ? GROUP BY asset_id", (latest_year,))} if latest_year else {}
    finally:
        conn.close()

    rows = []
    total = 0.0
    for row in loe_rows:
        known = revenue.get(row["asset_id"])
        if not known:
            continue                          # no revenue: no basis, so not valued
        # USD is identity and must not depend on a stored rate; other currencies need
        # one, and stay null when it is absent rather than being counted at par.
        revenue_usd = (known["value"] if known["unit"] == "USD"
                       else fx.to_usd(known["value"], known["unit"], rates))
        # The protection date is the later of the published Orange or Purple Book cliff
        # and the derived biologic LOE, since a biologic is protected until both have
        # lapsed. The basis records which one governs, so the source is always visible.
        book, bio = row["book_loe"], row["bio_loe"]
        if book and bio:
            loe, loe_basis = (book, "Orange/Purple Book") if book >= bio else (bio, row["bio_basis"])
        elif book:
            loe, loe_basis = book, "Orange/Purple Book"
        elif bio:
            loe, loe_basis = bio, row["bio_basis"]
        else:
            loe, loe_basis = None, None
        loe_year = int(loe[:4]) if loe else None
        years = (loe_year - today.year) if loe_year is not None else None
        rnpv = None
        if revenue_usd is not None and years is not None and years > 0:
            rnpv = revenue_usd * annuity_factor(years, rate)
            total += rnpv
        # Why a revenue-bearing product is not valued, so the gap reads as a fact rather
        # than a zero. The common one is a biologic whose only free date is orphan
        # exclusivity, excluded above, leaving no cliff to discount to.
        if rnpv is not None:
            reason = "valued"
        elif revenue_usd is None:
            reason = "no_fx"
        elif years is None:
            reason = "no_cliff"
        else:
            reason = "past_loe"
        rows.append({
            "brand": row["brand_name"], "generic": row["generic_name"],
            "modality": row["modality"], "application": row["internal_code"],
            "revenue": known["value"], "currency": known["unit"],
            "revenue_usd": revenue_usd, "fiscal_year": known["fiscal_year"],
            "loe": loe, "loe_year": loe_year, "loe_basis": loe_basis,
            "years_protected": years,
            "pos": POS_BY_PHASE["Marketed"], "rnpv_usd": rnpv, "reason": reason,
            "medicare_spend": demand.get(row["asset_id"]),
        })
    rows.sort(key=lambda a: a["rnpv_usd"] if a["rnpv_usd"] is not None else -1,
              reverse=True)
    valued = [r for r in rows if r["rnpv_usd"] is not None]
    # Earning but past or without a usable protection date: full generic exposure or a
    # biologic with no free patent cliff, shown so the portfolio is not read as only the
    # valued part. Sorted by revenue, since that is the size of what is not valued.
    unvalued = sorted((r for r in rows if r["rnpv_usd"] is None),
                      key=lambda a: a["revenue_usd"] or 0, reverse=True)
    return {
        "ticker": ticker.upper(),
        "discount_rate": rate,
        "fx_as_of": rates.get("as_of"),
        "protected_value_usd": total,
        "valued": valued,
        "unvalued": unvalued,
        "unvalued_revenue_usd": sum(r["revenue_usd"] or 0 for r in unvalued),
        "pos_by_phase": POS_BY_PHASE,
    }
