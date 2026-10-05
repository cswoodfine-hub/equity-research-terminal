"""Every seed that charges costs charges all of them, at its company's own rates.

A product's P&L is four ratios of revenue plus tax: cost of goods, R&D, SG&A and the
other-costs charge, which carries amortisation, restructuring and the capital spending
the filed lines leave out. The engine reads a missing ratio as nil, so a seed without
one is not refused, it is valued as if that cost did not exist. Seven pipeline scaffolds
(six written on 2026-08-27, and Eloralintide built from them) had no other_costs_pct:
Lilly's three kept 16.87 points of margin their company's charge takes away, and Amgen's
two missed its -11.70%, so they were valued too low. Cagrilintide had no SG&A either,
while Novo's charge was struck on the assumption that SG&A carries its selling costs.

The other-costs charge is a company figure, solved once from the company's own cash flow,
so every product of one company carries the same value. Its source text is also read by
the engine: growth_investment.carries() looks for the restatement markers in it, and a
row that drops them silently changes what growth costs the company.

Hermetic: these read the seed files only. A product's rows can span files (MariTide's
live in two), so rows are grouped by ticker and brand rather than by file.
"""

from __future__ import annotations

import collections
import csv
import pathlib

import growth_investment

_SEEDS = pathlib.Path(__file__).resolve().parents[2] / "data" / "assumptions"

_STACK = ("sga_pct", "other_costs_pct", "tax_rate")
# Casgevy is seeded from its reference workbook, which has no other-costs line. The key is
# named so that a second gap on the same product is still caught.
_ALLOWED_GAPS = {("VRTX", "Casgevy"): {"other_costs_pct"}}


def _groups() -> dict:
    """(ticker, brand) -> key -> [(file, row)], asset-level base-case rows only."""
    groups: dict = collections.defaultdict(lambda: collections.defaultdict(list))
    for path in sorted(_SEEDS.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as handle:
            lines = [line for line in handle if not line.lstrip().startswith("#")]
        for row in csv.DictReader(lines):
            if ((row.get("indication") or "").strip() or (row.get("year") or "").strip()
                    or (row.get("scenario") or "base").strip() != "base"
                    or (row.get("region") or "US").strip() != "US"):
                continue
            group = ((row.get("ticker") or "").strip().upper(),
                     (row.get("brand") or "").strip())
            groups[group][(row.get("key") or "").strip()].append((path.name, row))
    return groups


def _costed(groups: dict) -> dict:
    return {g: keys for g, keys in groups.items()
            if "cogs_pct" in keys or "rd_pct" in keys}


def _other_costs_by_company(groups: dict) -> dict:
    """ticker -> [(brand, file, value, source)] for every other_costs_pct row."""
    out: dict = collections.defaultdict(list)
    for (ticker, brand), keys in groups.items():
        for name, row in keys.get("other_costs_pct", []):
            source = row.get("source") or ""
            out[ticker].append((brand, name, float(row["value"]), source))
    return out


def test_every_seed_that_charges_costs_charges_the_whole_stack():
    """A seed with cost of goods or R&D also carries SG&A, the other-costs charge and a
    tax rate, since the engine would read any of the three as nil."""
    gaps = []
    for group, keys in sorted(_costed(_groups()).items()):
        missing = {k for k in _STACK if k not in keys} - _ALLOWED_GAPS.get(group, set())
        if missing:
            files = sorted({name for rows in keys.values() for name, _ in rows})
            gaps.append((group, sorted(missing), files))
    assert gaps == [], gaps


def test_the_allowed_gaps_are_still_gaps():
    """An exception that is no longer needed is removed, so it cannot hide a later one."""
    groups = _groups()
    stale = [(group, key) for group, allowed in _ALLOWED_GAPS.items() for key in allowed
             if group not in groups or key in groups[group]]
    assert stale == [], stale


def test_every_product_carries_its_companys_other_costs_charge():
    """One charge per company, solved from its own cash flow. A product carrying another
    figure is a copy that drifted, or a scaffold that took a different template."""
    off = []
    for ticker, rows in sorted(_other_costs_by_company(_groups()).items()):
        modal = collections.Counter(value for _, _, value, _ in rows).most_common(1)[0][0]
        off += [(ticker, brand, name, value, modal) for brand, name, value, _ in rows
                if abs(value - modal) > 1e-6]
    assert off == [], off


def test_every_other_costs_source_carries_the_markers_its_siblings_carry():
    """growth_investment.carries() reads the restatement markers off the row's own text.
    A copy that loses one charges the company's growth capex or working capital twice,
    or not at all, without any error."""
    off = []
    for ticker, rows in sorted(_other_costs_by_company(_groups()).items()):
        read = [(brand, name, growth_investment.carries(source))
                for brand, name, _, source in rows]
        modal = collections.Counter(found for _, _, found in read).most_common(1)[0][0]
        off += [(ticker, brand, name, markers, modal) for brand, name, markers in read
                if markers != modal]
    assert off == [], off


def test_the_markers_are_the_ones_the_engine_reads():
    """If the engine's marker text changes, the guard above compares the wrong thing."""
    assert growth_investment.carries(
        f"x. {growth_investment.CAPEX_MARKER}: y. {growth_investment.WC_MARKER}: z."
    ) == (True, True)
    assert growth_investment.carries("Checked at replacement capex") == (False, False)
