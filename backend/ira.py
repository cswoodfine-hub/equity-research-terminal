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
    # One row per drug, brand and selection year. It used to take the first ipay it
    # found per drug through next(...), which happens to be right today because no drug
    # yet spans two cycles, and would silently hide the second the moment one does.
    # CMS reselects: a 2026 drug can appear again for a later year at a new price.
    out = []
    for drug, ipay in sorted({(r["drug"], r["ipay"]) for r in rows}):
        for_year = [r for r in rows if r["drug"] == drug and r["ipay"] == ipay]
        price = current(for_year, drug)
        for brand in brands(drug):
            asset_id, ticker = assets.get(_norm(brand), (None, None))
            out.append({"drug": drug, "brand": brand, "asset_id": asset_id,
                        "ticker": ticker, "ipay": ipay,
                        "mfp_30des": (price or {}).get("mfp_30des"),
                        "effective_from": (price or {}).get("effective_from"),
                        "effective_to": (price or {}).get("effective_to"),
                        "in_force": bool(price)})
    return out


def company_exposure(conn, ticker: str, rates: dict | None = None) -> dict:
    """What Medicare's gross spending on a company's selected drugs is worth to it.

    Part D gross spending summed over the selected assets the company owns, against its
    latest reported revenue in dollars. It is a share of revenue exposed to a
    negotiated price, not a cut: the price CMS replaced was net of rebates nobody
    publishes, so how much of that spending actually falls is not knowable from free
    data. ``ceiling_cut`` gives the upper bound on the price and this gives the base it
    would apply to, and the two are deliberately not multiplied.

    Gross spending is Medicare's, in dollars, and revenue is the company's worldwide
    total converted to dollars, so the share is Medicare Part D against the world. That
    is the comparison a reader wants for a US policy, and it is stated rather than
    implied.

    ``assets_without_part_d`` is the count of selected assets carrying no Part D row.
    They are a gap in the figure, not a zero, so the share is a floor whenever it is
    above nil.
    """
    import fx as fx_module
    import productivity

    company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                           (ticker.upper(),)).fetchone()
    if company is None:
        return {"reason": f"unknown ticker {ticker}"}
    mine = [s for s in selected(conn)
            if (s["ticker"] or "").upper() == ticker.upper() and s["asset_id"]]
    if not mine:
        return {"reason": "no selected drug the book models belongs to this company"}

    # One asset can carry several selected brands (Ozempic, Rybelsus and Wegovy are one
    # asset), and Part D spending is per asset, so counting it once per brand would
    # multiply the exposure by the number of trade names.
    spending, missing, years = 0.0, 0, set()
    for asset_id in sorted({s["asset_id"] for s in mine}):
        got = exposure(conn, asset_id)
        if got.get("reason"):
            missing += 1
            continue
        spending += got["part_d_spending"] or 0.0
        years.add(got["year"])

    if rates is None:
        # fx takes a path, so ask the connection which file it is open on. With no path
        # the rates came from the default database whatever database the caller held.
        row = conn.execute("PRAGMA database_list").fetchone()
        rates = fx_module.latest_usd_rates((row["file"] or None) if row is not None
                                           else None)
    revenue = productivity.latest_revenue(conn, company["id"], rates)
    share = (spending / revenue) if (revenue and spending) else None
    return {"ticker": ticker.upper(), "part_d_spending": spending or None,
            "revenue_usd": revenue, "share": share,
            "brands": len(mine), "assets": len({s["asset_id"] for s in mine}),
            "assets_without_part_d": missing,
            "spending_years": sorted(years),
            "ipay_years": sorted({s["ipay"] for s in mine}),
            "reason": None if share is not None else
            ("no Part D spending on file for any selected asset" if not spending
             else "no reported revenue to read the spending against")}


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


# The share of latest reported revenue that Medicare's gross Part D spending on a
# company's selected drugs has to reach before a note says anything about it. Below
# this the selection is a fact for the feed and not a paragraph in a morning note.
NOTE_GATE = 0.01

# CMS marks why a row was end dated. "Deselect" is a drug leaving the programme because
# a generic or biosimilar is being sold; "Inflation" and "End Date" are the annual
# rebasing and administrative housekeeping, which are not events. The column says which
# directly, so nothing here reads the Remarks prose to tell them apart.
DESELECT_KIND = "Deselect"


def signals(conn) -> dict:
    """{"selections": [...], "deselections": [...]} worth flagging.

    Pure of side effects. The caller decides what to write and what to anchor.
    """
    chosen = [s for s in selected(conn) if s["ticker"]]
    years: dict = {}
    for row in chosen:
        years.setdefault((row["ticker"], row["ipay"]), []).append(row)
    selections = [{"ticker": t, "ipay": y, "brands": sorted(r["brand"] for r in rows),
                   "assets": sorted({r["asset_id"] for r in rows if r["asset_id"]}),
                   "key": f"IRA:{t}:{y}"}
                  for (t, y), rows in sorted(years.items())]

    by_brand = {}
    for row in chosen:
        by_brand.setdefault(row["drug"], row)
    dropped = []
    for drug, count in conn.execute(
            "SELECT drug, COUNT(*) FROM negotiated_prices WHERE update_kind = ?"
            " GROUP BY drug", (DESELECT_KIND,)):
        row = by_brand.get(drug)
        dropped.append({"drug": drug, "ndcs": count,
                        "ticker": (row or {}).get("ticker"),
                        "key": f"IRA:DESELECT:{drug}"})
    return {"selections": selections, "deselections": sorted(
        dropped, key=lambda d: d["drug"])}


def sentence(conn, ticker: str, ipay: int, rates: dict | None = None) -> str | None:
    """The paragraph for one company's selection year, or None below the gate.

    Every figure is read rather than asserted, and the one thing it refuses to do is
    multiply the ceiling cut by the exposure. The ceiling is the most a list price
    could fall and the exposure is gross spending at list, so their product would be a
    loss estimate built from two numbers that are both gross of rebates nobody
    publishes.
    """
    got = company_exposure(conn, ticker, rates)
    if got.get("share") is None or got["share"] < NOTE_GATE:
        return None
    names = [s["brand"] for s in selected(conn)
             if (s["ticker"] or "").upper() == ticker.upper() and s["ipay"] == ipay]
    count = len(set(names))
    noun = "drug" if count == 1 else "drugs"
    gap = ""
    if got["assets_without_part_d"]:
        gap = (f" {got['assets_without_part_d']} of them carry no Part D row, so the "
               "share is a floor.")
    return (f"CMS lists {count} {ticker.upper()} {noun} for IPAY {ipay}: "
            f"{', '.join(sorted(set(names)))}. Medicare's gross Part D spending on this "
            f"company's selected drugs was ${got['part_d_spending'] / 1e9:,.1f}bn, "
            f"{got['share']:.1%} of its latest reported revenue.{gap} That is gross "
            "spending at list against net revenue, not revenue at risk: the rebates a "
            "maximum fair price replaces are confidential, so the realised cut is "
            "smaller by an amount free data cannot show.")


def company_view(conn, ticker: str, rates: dict | None = None) -> dict:
    """One company's Medicare selection, for a strip: what, when, at what price.

    The ceiling cut and the exposure are both carried and neither is multiplied by the
    other. Each is an upper bound built from a gross figure, and their product would
    read as a loss estimate that free data cannot support.
    """
    mine = [s for s in selected(conn)
            if (s["ticker"] or "").upper() == ticker.upper()]
    if not mine:
        return {"ticker": ticker.upper(), "selected": [], "reason":
                "no drug CMS has selected belongs to this company"}
    got = company_exposure(conn, ticker, rates)
    drugs = []
    for row in sorted(mine, key=lambda r: (r["ipay"], r["brand"])):
        bound = None
        if row["asset_id"]:
            spend = exposure(conn, row["asset_id"])
            bound = ceiling_cut(spend.get("gross_per_claim"), row["mfp_30des"])
        drugs.append({**row, "ceiling_cut": bound})
    priced = [d["mfp_30des"] for d in drugs if d["mfp_30des"]]
    return {"ticker": ticker.upper(), "selected": drugs,
            "count": len({d["brand"] for d in drugs}),
            "earliest_ipay": min(d["ipay"] for d in drugs),
            "mfp_30des_low": min(priced) if priced else None,
            "mfp_30des_high": max(priced) if priced else None,
            "exposure": got, "reason": None}
