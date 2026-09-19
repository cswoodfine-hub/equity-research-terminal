"""The Medicare prices CMS has negotiated, and what each one puts at risk.

The Inflation Reduction Act lets Medicare set the price of a drug it spends heavily on.
CMS publishes the result as a Maximum Fair Price per thirty-day equivalent supply, one
per national drug code, with the year it takes effect: ten drugs from 2026, fifteen more
from 2027, sixteen from 2028. Forty-one of them, and the book holds most of them.

None of it was in the model. This is the pure half: the CMS file turned into one row per
drug, per code, per price period, and the join from a selected drug to the asset it is.

What the data cannot say, and why the model does not pretend otherwise. The MFP is a net
price, and the price it replaces is also net, because manufacturers already rebate a
large share of a Part D drug's list price back to the plans. Those rebates are
confidential. So the fall from today's net price to the MFP, which is the only number a
forecast could use, is not published anywhere free, and it varies enormously by drug: an
insulin rebates most of its list price, an oncology pill close to none of it. What is
published is CMS's own gross spending per prescription, which gives an upper bound on the
cut and nothing tighter. ``exposure`` reports that bound and the revenue standing behind
it, so the risk is sized and visible rather than estimated into the value.

Two things in the file are signals in their own right. An MFP row carrying an end date
has been superseded, either by the annual inflation adjustment or because CMS deselected
the drug, and CMS deselects a drug when a generic or biosimilar arrives, which is a dated
statement about exclusivity from the agency that pays for it.
"""

from __future__ import annotations

import csv
import io
import re

# CMS names a selected drug by every brand the price covers, semicolon separated:
# "OZEMPIC; RYBELSUS; WEGOVY" is one negotiation over three brands, and
# "JANUMET; JANUMET XR" is one over a formulation pair.
_SPLIT = re.compile(r"\s*;\s*")
_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _iso(value: str) -> str | None:
    """CMS writes dates as MM/DD/YYYY. Anything else is no date."""
    match = _DATE.match((value or "").strip())
    return f"{match.group(3)}-{match.group(1)}-{match.group(2)}" if match else None


def _number(value: str) -> float | None:
    text = (value or "").strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def brands(selected_drug_name: str) -> list[str]:
    """The brands one negotiated price covers."""
    return [b.strip() for b in _SPLIT.split(selected_drug_name or "") if b.strip()]


def parse(text: str) -> list[dict]:
    """One row per drug, code and price period from the CMS selected-drug file.

    Deduplicated to the nine-digit code: CMS repeats a price for every package size of
    the same product, and the package is not something the model has a view on. Pure.
    """
    seen, out = set(), []
    for row in csv.DictReader(io.StringIO(text)):
        drug = (row.get("Selected Drug Name") or "").strip()
        ndc9 = (row.get("NDC-9") or "").strip()
        ipay = _number(row.get("IPAY") or "")
        effective_from = _iso(row.get("MFP Effective Date") or "")
        if not drug or not ipay or not effective_from:
            continue
        key = (drug, ndc9, effective_from)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "drug": drug,
            "ingredient": (row.get("Active Ingredient Name or Active Moiety Name")
                           or "").strip() or None,
            "ipay": int(ipay),
            "ndc9": ndc9 or None,
            "hcpcs": (row.get("HCPCS Code") or "").strip() or None,
            "mfp_30des": _number(row.get("Single MFP per 30 DES") or ""),
            "unit_price": _number(row.get("NDC-9 MFP per Unit Price") or ""),
            "effective_from": effective_from,
            "effective_to": _iso(row.get("MFP End Date") or ""),
            "as_of": _iso(row.get("As of Date") or ""),
            "update_kind": (row.get("Type of Update") or "").strip() or None,
            "remarks": (row.get("Remarks") or "").strip() or None,
        })
    return out


def current(rows: list[dict], drug: str) -> dict | None:
    """The price in force for a drug: the row with no end date, latest effective date.

    A drug whose every row is end dated has no price in force. That is either a cycle
    whose prices CMS has not announced yet, or a drug CMS has deselected.
    """
    live = [r for r in rows if r["drug"] == drug and not r["effective_to"]
            and r["mfp_30des"]]
    return max(live, key=lambda r: r["effective_from"]) if live else None


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def selected(conn) -> list[dict]:
    """Every selected drug the book models, with the price in force and the asset it is.

    The match is an exact brand name, the same rule the demand fetcher uses, so a drug
    binds to its own asset and nothing is guessed. A brand CMS names that the book does
    not model is reported with no asset rather than dropped, because it is a real gap.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT drug, ingredient, ipay, mfp_30des, effective_from, effective_to,"
        "       update_kind, remarks FROM negotiated_prices")]
    assets = {}
    for row in conn.execute(
        "SELECT a.id AS asset_id, a.brand_name, c.ticker FROM assets a"
        " LEFT JOIN companies c ON c.id = a.owner_company_id"
        " WHERE a.brand_name IS NOT NULL"):
        assets.setdefault(_norm(row["brand_name"]), (row["asset_id"], row["ticker"]))
    out = []
    for drug in sorted({r["drug"] for r in rows}):
        price = current(rows, drug)
        for brand in brands(drug):
            asset_id, ticker = assets.get(_norm(brand), (None, None))
            out.append({"drug": drug, "brand": brand, "asset_id": asset_id,
                        "ticker": ticker,
                        "ipay": next(r["ipay"] for r in rows if r["drug"] == drug),
                        "mfp_30des": (price or {}).get("mfp_30des"),
                        "effective_from": (price or {}).get("effective_from"),
                        "in_force": bool(price)})
    return out


def exposure(conn, asset_id: int, year: int | None = None) -> dict:
    """What a negotiated price puts at risk on one asset, and the most it could cut.

    Medicare's gross spending on the drug, from the CMS spending tables already on file,
    against its gross spending per prescription and the MFP. The fall in gross price is
    the ceiling on the fall in revenue, never the expected fall: the price CMS replaced
    was net of rebates nobody publishes, so the true cut is smaller by an amount that is
    not knowable from free data.
    """
    row = conn.execute(
        "SELECT year, total_spending, total_claims FROM drug_demand"
        " WHERE asset_id = ? AND part = 'D' AND total_spending IS NOT NULL"
        "   AND (? IS NULL OR year = ?) ORDER BY year DESC LIMIT 1",
        (asset_id, year, year)).fetchone()
    if not row or not row["total_claims"]:
        return {"reason": "no Part D spending on file for the asset"}
    gross_per_claim = row["total_spending"] / row["total_claims"]
    return {"year": row["year"], "part_d_spending": row["total_spending"],
            "claims": row["total_claims"], "gross_per_claim": gross_per_claim,
            "reason": None}


def ceiling_cut(gross_per_claim: float | None, mfp_30des: float | None) -> float | None:
    """The most a negotiated price could cut a drug's price: one less the MFP over gross
    spending per prescription. None where either side is missing, and never below nil,
    since a negotiated price above what Medicare already pays cuts nothing."""
    if not gross_per_claim or not mfp_30des:
        return None
    return max(0.0, 1.0 - mfp_30des / gross_per_claim)
