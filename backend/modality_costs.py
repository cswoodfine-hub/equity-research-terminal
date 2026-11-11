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

import csv
import pathlib
import re

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


# The WHO INN stem, read only where the book states no modality of its own. 339 modelled
# assets carry none, and every one of them takes the conservative twelve-year biologic
# floor from data/loe_defaults.csv: a small molecule is entitled to fourteen, so each
# wrongly-defaulted one loses two years of peak revenue.
#
# A stated modality always wins and this never overrules one. That rule is what makes the
# stem list safe: dulaglutide ends in -tide and is an Fc fusion protein, obecabtagene is
# a cell therapy rather than the gene therapy its stem suggests, and the book already
# says so for all eight such assets.
#
# The oligonucleotides and the peptides sit under small molecule on purpose, which is
# where the book's own stated facts put all thirty-seven of them: an antisense oligo or a
# peptide is filed as a drug under an NDA, not as a biologic under a BLA, so the
# fourteen-year ceiling is the one that applies. Measured 2026-11-10 against every asset
# with a stated modality: 407 agree, 8 disagree, and all eight state a modality already.
_SMALL_MOLECULE_STEMS = (
    ("rsen", "antisense oligonucleotide"), ("siran", "small interfering RNA"),
    ("tide", "peptide"), ("nib", "kinase inhibitor"), ("vir", "antiviral"),
    ("stat", "enzyme inhibitor"), ("pril", "ACE inhibitor"),
    ("sartan", "angiotensin antagonist"), ("azole", "antifungal"),
    ("cycline", "tetracycline"), ("floxacin", "quinolone"),
    ("prazole", "proton pump inhibitor"), ("ciclib", "CDK inhibitor"),
    ("parib", "PARP inhibitor"), ("rasib", "RAS inhibitor"),
    ("setron", "5-HT3 antagonist"), ("triptan", "5-HT1 agonist"),
    ("glifozin", "SGLT2 inhibitor"), ("gliptin", "DPP-4 inhibitor"),
    ("olol", "beta blocker"), ("statin", "HMG-CoA reductase inhibitor"))
_BIOLOGIC_STEMS = (
    ("mab", "monoclonal antibody"), ("cept", "receptor fusion protein"),
    ("ase", "enzyme"), ("kin", "interleukin"), ("poetin", "erythropoietin"),
    ("gene", "gene therapy"), ("cel", "cell therapy"))


# The curated override, for the assets no stem reaches: internal codes like
# JNJ-78934804, trade pairs like "Rybrevant / Lazcluze", and INNs whose stem is not in
# the table. Each row cites the filing, label or registry record that settles it, and the
# file fills only: a modality already on the asset row always wins, because the fetchers
# read it from the register and this is curation rather than correction.
CURATED = (pathlib.Path(__file__).resolve().parent.parent
           / "data" / "asset_modalities.csv")


def curated_modalities(path=None) -> dict:
    """{(ticker, lowercased asset name): modality} from data/asset_modalities.csv."""
    source = pathlib.Path(path) if path else CURATED
    if not source.exists():
        return {}
    out = {}
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle
                                  if not line.lstrip().startswith("#")):
            ticker = (row.get("ticker") or "").strip().upper()
            name = (row.get("asset") or "").strip().lower()
            found = (row.get("modality") or "").strip().lower()
            # A row with no source asserts nothing, the rule every curated file here
            # keeps: a wrong modality moves an exclusivity cliff two years in silence.
            if ticker and name and found and (row.get("source") or "").strip():
                out[(ticker, name)] = found
    return out


def infer_modality(name: str | None) -> tuple:
    """(modality, the stem that said so), or (None, None) where no stem fits.

    For filling a gap, never for correcting a statement: the caller must check that the
    asset has no modality of its own first.
    """
    text = re.sub(r"[^a-z ]+", " ", (name or "").lower()).strip()
    if not text:
        return None, None
    word = text.split()[0]
    for stem, what in _SMALL_MOLECULE_STEMS:
        if word.endswith(stem):
            return "small molecule", f"-{stem}, {what}"
    for stem, what in _BIOLOGIC_STEMS:
        if word.endswith(stem):
            return "biologic", f"-{stem}, {what}"
    return None, None


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
