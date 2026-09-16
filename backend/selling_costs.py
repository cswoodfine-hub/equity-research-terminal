"""Put selling costs back into SG&A where the filer tags them under its own name.

An IFRS filer that presents costs by function reports sales and distribution separately
from administration. The SG&A line reads ``ifrs-full:AdministrativeExpense`` when no
combined concept is tagged, and for a filer whose selling line sits under a standard
concept that is harmless. Novo Nordisk tags it under its own extension,
``SellingExpenseAndDistributionCosts``, and the companyfacts API carries no extension
concepts at all. So Novo's SG&A read DKK 5,969mm, administration alone, against DKK
70,279mm filed, and every Novo product was costed at 1.9% of revenue for SG&A where the
filer spends 22.7%.

The figure is filed, not derived. The SEC Financial Statement Data Sets keep extension
tags, with the filing's accession as their version, and the product revenue fetcher
already caches them. Novo's 20-F for 2025 (0000353278-26-000012) tags DKK 56,743mm,
62,101mm and 64,310mm for 2023 to 2025, which is also exactly revenue less cost of sales,
R&D, administration and operating profit, plus other operating income. AstraZeneca is
the other filer the check finds: it reports distribution costs of $579mm apart from SG&A
under the standard concept, and no cost line in its book carried them.

Each other-costs charge was solved as other = book pre-tax margin - FCF margin / (1 - tax),
with SG&A inside the book margin. Raising SG&A by d lowers that margin by d, so the charge
falls by d, and cannot fall below nil. For Novo it does fall to nil: the charge was
carrying the selling costs the SG&A line had lost.
"""

from __future__ import annotations

import csv
import io
import pathlib
import re
import zipfile

import interest_addback as IA

MARKER = "with selling costs"
CACHE_DIR = pathlib.Path(__file__).resolve().parent / "cache"
ANNUAL_FORMS = ("10-K", "20-F")

# Standard concepts a by-function filer may use for its selling line.
STANDARD_TAGS = ("SellingExpense", "DistributionCosts", "SellingAndDistributionExpense")
# An extension concept counts only when its name says selling (or sales) and
# distribution, and says nothing of administration, which would be the whole of SG&A.
_EXTENSION = re.compile(r"^(Selling|Sales)\w*Distribution\w*(Costs?|Expenses?)$")


def is_selling_tag(tag: str, version: str, adsh: str) -> bool:
    if "Administrative" in tag:
        return False
    if version == adsh:
        return bool(_EXTENSION.match(tag))
    return tag in STANDARD_TAGS


def parse_selling_costs(rows, adsh: str) -> dict:
    """{fiscal_year: {"value", "tag", "unit"}} for the consolidated selling line of one
    annual filing. Segment rows are the same cost split by segment and are skipped, as
    are a co-registrant's figures and anything but a full year."""
    out: dict[int, dict] = {}
    for row in rows:
        if row.get("adsh") != adsh or row.get("qtrs") != "4":
            continue
        if (row.get("segments") or "").strip() or (row.get("coreg") or "").strip():
            continue
        if not is_selling_tag(row.get("tag") or "", row.get("version") or "", adsh):
            continue
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        year = int(row["ddate"][:4])
        # One line per year. Two selling concepts in one filing would be a split the
        # filer made, and summing them could double count, so the first one stands.
        out.setdefault(year, {"value": abs(value), "tag": row["tag"], "unit": row.get("uom")})
    return out


def read_cached(cik: str, cache_dir: pathlib.Path = CACHE_DIR) -> dict | None:
    """The latest cached annual filing for a CIK and its selling line, or None."""
    cik = str(int(cik))
    for path in sorted(cache_dir.glob("fsds_*.zip"), reverse=True):
        with zipfile.ZipFile(path) as archive:
            with archive.open("sub.txt") as handle:
                sub = next((r for r in csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                                      delimiter="\t")
                            if r.get("cik") == cik and r.get("form") in ANNUAL_FORMS), None)
            if sub is None:
                continue
            with archive.open("num.txt") as handle:
                rows = [r for r in csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                                  delimiter="\t")
                        if r.get("adsh") == sub["adsh"]]
            return {"adsh": sub["adsh"], "form": sub["form"], "filed": sub.get("filed"),
                    "years": parse_selling_costs(rows, sub["adsh"])}
    return None


def measure(conn, ticker: str, filing: dict | None, year: int, seed_sga: float) -> dict:
    """What SG&A is with the filed selling line added, for the fiscal year the seed costs
    are struck on. ``new`` is None, with ``reason``, wherever nothing should change."""
    ticker = ticker.upper()
    base = {"ticker": ticker, "year": year, "old": seed_sga}
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    if company is None:
        return {**base, "new": None, "reason": "company not on file"}
    if not filing or year not in filing["years"]:
        return {**base, "new": None, "reason": "no separate selling line in the annual filing"}
    cid = company["id"]
    revenue = IA.fy_series(conn, cid, "Revenues", year, year).get(year)
    sga = IA.fy_series(conn, cid, "SellingGeneralAndAdministrative", year, year).get(year)
    if revenue is None or sga is None:
        return {**base, "new": None, "reason": "revenue or SG&A not on file for the year"}
    selling = filing["years"][year]
    if selling["unit"] and selling["unit"] != revenue["unit"]:
        return {**base, "new": None, "reason": "selling costs and revenue in different units"}
    line_share = abs(sga["value"]) / revenue["value"]
    # Only a seed struck on the SG&A line as read is short of the separate selling line.
    # A seed set any other way was not built on that line and is left to its source.
    if abs(seed_sga - line_share) > 0.0005:
        return {**base, "new": None,
                "reason": "the seed is not struck on the SG&A line on file"}
    return {**base, "new": (abs(sga["value"]) + selling["value"]) / revenue["value"],
            "admin": abs(sga["value"]), "selling": selling["value"], "tag": selling["tag"],
            "revenue": revenue["value"], "unit": revenue["unit"], "adsh": filing["adsh"],
            "form": filing["form"], "reason": None}


def restate_sga(row: dict, m: dict) -> dict | None:
    """The sga_pct row with the selling line added, or None when already done or when
    nothing applies."""
    source = row.get("source") or ""
    if MARKER in source or m.get("new") is None:
        return None
    where = ("under its own concept" if m["tag"] not in STANDARD_TAGS else "as")
    clause = (f" Restated {MARKER}: the SG&A line on file, "
              f"{IA._money(m['admin'], m['unit'])} for FY{m['year']}, leaves out the "
              f"{IA._money(m['selling'], m['unit'])} of selling or distribution costs "
              f"{m['ticker']} reports as a line of its own, tagged {where} {m['tag']} "
              f"({m['form']} {m['adsh']}, SEC financial statement data sets), so SG&A "
              f"rises from {m['old']:.2%} to {m['new']:.2%} of revenue.")
    return {**row, "value": m["new"], "source": source.rstrip(". ") + "." + clause}


def restate_other(row: dict, m: dict) -> dict | None:
    """The other_costs_pct row lowered by the rise in SG&A, floored at nil."""
    source = row.get("source") or ""
    if MARKER in source or m.get("new") is None:
        return None
    old = float(row["value"])
    rise = m["new"] - m["old"]
    new = max(0.0, old - rise)
    lead = (f" Restated {MARKER}: SG&A now carries {m['ticker']}'s filed selling or "
            f"distribution costs, {rise:.2%} of revenue this charge was absorbing, so it ")
    tail = (f"falls from {old:.2%} to nil. The filed lines alone now leave less than the "
            f"cash the company made before interest and at replacement capex, and a charge "
            f"below nil would credit the book with cash its own costs do not leave."
            if new == 0.0 else f"falls from {old:.2%} to {new:.2%}.")
    return {**row, "value": new, "source": source.rstrip(". ") + "." + lead + tail}
