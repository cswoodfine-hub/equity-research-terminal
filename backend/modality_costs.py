"""What a product costs to make, by what kind of product it is.

Every product in a company's book carries that company's blended cost of sales, so a
biologic is costed like a pill and a pill like a biologic. They are not alike: an antibody
is grown in cells, filled and cold chained, a tablet is pressed.

Nobody publishes cost of sales per product, so it is measured from what filers publish.
Each company's ratio is its own modality mix priced at some pair of rates, so across
filers the pair can be read off the mix: regress the filed ratio on the share of revenue
that is biologic, and the intercept is the small molecule rate while the far end is the
biologic one. Revenue weighted across the fifteen filers with no peptide revenue, a
biologic costs 32.6% of its sales against a small molecule's 18.6%, so 1.75 times as much.

Three things this measurement is not, each of which shaped how it is used.

It is not precise. Equal weighted the same regression gives 35.6% against 14.5%, a ratio
of 2.46 rather than 1.75, so the central number moves by 40% on the choice of weighting.
Revenue weighting is taken because the residuals say the unweighted fit is dominated by
small filers whose ratio is not about modality at all.

It is not only about modality. The largest residuals are Incyte at 12 points below its
fitted ratio, United Therapeutics 8 below and Vertex 5 below, and all three are
single-product specialists whose prices are high enough that making the drug barely
registers. Pricing power is confounded with modality here and cannot be separated on
seventeen observations, which is why the fit explains 42% of the variance rather than
most of it.

It does not measure peptides. Lilly and Novo are 68% and 71% peptide by revenue, and a
synthetic peptide is neither a pressed tablet nor a cell culture. Fitting a third rate for
it lands at 15.4%, close to the small molecule rate, but on two filers, which is an
attribution of those two companies' own ratios rather than a measurement. Both are left
out of the fit, and a peptide is left out of the reshuffle: it keeps the company's blend.
Charging Mounjaro a pill's cost of sales would have raised Lilly by $13.50 a share on a
coefficient estimated from Lilly.

The measurement is applied as a reshuffle, never as a new cost level. Each company's
factors are normalised over the part of its revenue that was measured, so the
revenue-weighted cost of sales in the anchor year is exactly what was filed, and exactly
what the other-costs charge was solved against. What changes is which products carry it:
in a book that is half biologic, the pills cost about a third less than the blend and the
biologics about a third more. The normalisation holds at the anchor year's mix, so a book
whose biologics grow faster carries a slowly rising weighted ratio later, which is what a
changing mix should do but is no longer tied to the filed figure.
"""

from __future__ import annotations

# Measured 2026-09-19, revenue weighted, over the fifteen filers with a solved cost of
# sales, a modality mix on file and no material peptide revenue. Only the ratio between
# the two is used; the level is each company's own filed figure.
BIOLOGIC_RATE = 0.326
SMALL_MOLECULE_RATE = 0.186
R_SQUARED = 0.42
EQUAL_WEIGHTED = (0.145, 0.356)          # the same fit unweighted, for the range
BASIS = ("measured by regressing each filer's own cost of sales on the biologic share of "
         "its revenue, 15 filers with no peptide revenue, revenue weighted, R2 0.42: "
         "biologic 32.6% of sales against small molecule 18.6%, so 1.75x. Equal weighted "
         "the ratio is 2.46x")
RATES = {"biologic": BIOLOGIC_RATE, "small molecule": SMALL_MOLECULE_RATE}
# The INN stem for a peptide. A drug tagged biologic stays biologic whatever its stem, so
# dulaglutide is read as the fusion protein it is rather than as a peptide.
PEPTIDE_STEM = "tide"


def classify(modality: str | None, generic_name: str | None) -> str:
    """The cost class of one product: biologic, peptide, or whatever it is tagged."""
    found = (modality or "").strip().lower()
    if found == "biologic":
        return "biologic"
    if (generic_name or "").strip().lower().endswith(PEPTIDE_STEM):
        return "peptide"
    return found


def rate_for(modality: str | None, generic_name: str | None = None) -> float | None:
    """The measured rate for a product's class, or None where it was not measured. A
    peptide is not measured, and neither is a product with no modality on file."""
    return RATES.get(classify(modality, generic_name))


def mix(conn, company_id: int, year: int | None = None) -> dict:
    """{cost class: share of the company's reported product revenue} in the anchor year."""
    if year is None:
        row = conn.execute(
            """SELECT MAX(r.fiscal_year) y FROM asset_revenue r
                JOIN assets a ON a.id = r.asset_id
                WHERE a.owner_company_id = ? AND r.period = 'FY'""",
            (company_id,)).fetchone()
        year = row["y"] if row else None
    if not year:
        return {}
    rows = conn.execute(
        """SELECT a.modality, a.generic_name, SUM(r.value) v
            FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
            WHERE a.owner_company_id = ? AND r.fiscal_year = ? AND r.period = 'FY'
              AND r.value IS NOT NULL GROUP BY a.id""", (company_id, year)).fetchall()
    total = sum(r["v"] for r in rows) or 0.0
    if not total:
        return {}
    out: dict = {}
    for row in rows:
        found = classify(row["modality"], row["generic_name"])
        out[found] = out.get(found, 0.0) + row["v"] / total
    return out


def factors(conn, company_id: int) -> dict:
    """{cost class: factor on the company's blended cost of sales}, normalised so the
    revenue-weighted factor over the measured part of the book is one.

    Only measured revenue is normalised over, so a peptide or an untagged product neither
    takes a factor nor changes anyone else's.
    """
    shares = mix(conn, company_id)
    measured = {m: s for m, s in shares.items() if m in RATES}
    weight = sum(measured.values())
    if not weight:
        return {}
    blend = sum(s * RATES[m] for m, s in measured.items()) / weight
    if not blend:
        return {}
    return {m: RATES[m] / blend for m in measured}


def for_asset(conn, company_id: int, modality: str | None, cogs_pct: float | None,
              generic_name: str | None = None):
    """(cost of sales for this product, why it moved), or (None, None) where the product's
    class was not measured, the company has no mix on file, or there is no ratio."""
    if cogs_pct is None:
        return None, None
    found = factors(conn, company_id).get(classify(modality, generic_name))
    if not found:
        return None, None
    return cogs_pct * found, (f"{classify(modality, generic_name)} at {found:.2f}x the "
                              f"company's blended cost of sales; {BASIS}")
