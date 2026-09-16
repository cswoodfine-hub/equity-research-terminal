"""Count capital spending at depreciation in the other-costs calibration.

Each company's ``other_costs_pct`` was solved so its book reproduces the free-cash margin
it earned over a window, and free cash flow takes off every dollar of capital spending in
the year it is spent. A company building capacity spends far above what keeps its plant
running: Lilly spent $23.1bn over 2018 to 2025 against $7.3bn of depreciation, and Novo
DKK 133bn against DKK 20bn. Charging that on every product in perpetuity costs the book
the plants and never counts the volume they are built for, which the product forecasts
cap separately.

Depreciation is the standard measure of what keeps a plant running, so the calibration
now takes capital spending at depreciation. The charge was solved as other = book pre-tax
margin - FCF margin / (1 - tax), and replacing capex with depreciation lifts the FCF
margin by (capex - depreciation) / revenue, which lowers the charge by that over one
minus tax. It runs both ways: a company that spent less than its depreciation (Biogen)
was flattered by the window, and its charge rises. A charge cannot fall below nil.

Plant depreciation only, never depreciation and amortisation together: amortisation of
acquired intangibles is not spending on plant, and counting it as replacement would
charge Pfizer for Seagen twice. Where a filer tags only the combined line, plant
depreciation is that line less amortisation of intangibles, and the row says so.
"""

from __future__ import annotations

import interest_addback as IA

MARKER = "at replacement capex"


def _tax(conn, company_id: int):
    row = conn.execute(
        """SELECT a.value FROM assumptions a JOIN assets s ON s.id = a.asset_id
            WHERE s.owner_company_id = ? AND a.key = 'tax_rate' AND a.scenario = 'base'
            LIMIT 1""", (company_id,)).fetchone()
    return row["value"] if row else None


def measure(conn, ticker: str) -> dict:
    """Capital spending less plant depreciation over the company's window, as a share of
    revenue, and the change to the charge. ``cut`` is None, with ``reason``, wherever a
    line is missing for a year of the window."""
    ticker = ticker.upper()
    window = IA.WINDOWS.get(ticker)
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    if not window or company is None:
        return {"ticker": ticker, "cut": None, "reason": "no calibration window on file"}
    first, last = window
    cid = company["id"]
    years = list(range(first, last + 1))
    base = {"ticker": ticker, "first": first, "last": last}
    revenue = IA.fy_series(conn, cid, "Revenues", first, last)
    capex = IA.fy_series(conn, cid, "CapitalExpenditure", first, last)
    dep = IA.fy_series(conn, cid, "Depreciation", first, last)
    combined = IA.fy_series(conn, cid, "DepreciationAndAmortisation", first, last)
    amort = IA.fy_series(conn, cid, "AmortisationOfIntangibles", first, last)
    if set(revenue) != set(years):
        return {**base, "cut": None, "reason": "revenue is not on file for every year"}
    if set(capex) != set(years):
        return {**base, "cut": None, "reason": "no capital spending line on file for every year"}
    depreciation, derived = 0.0, False
    for year in years:
        if year in dep:
            depreciation += abs(dep[year]["value"])
        elif year in combined and year in amort:
            depreciation += abs(combined[year]["value"]) - abs(amort[year]["value"])
            derived = True
        else:
            return {**base, "cut": None,
                    "reason": "no plant depreciation on file for every year, and no "
                              "amortisation line to take it out of the combined figure"}
    units = ({r["unit"] for r in revenue.values()} | {r["unit"] for r in capex.values()})
    if len(units) != 1:
        return {**base, "cut": None, "reason": "revenue and capital spending in different units"}
    tax = _tax(conn, cid)
    if tax is None or tax >= 1:
        return {**base, "cut": None, "reason": "no tax rate on file"}
    total_capex = sum(abs(r["value"]) for r in capex.values())
    total_revenue = sum(r["value"] for r in revenue.values())
    share = (total_capex - depreciation) / total_revenue
    return {**base, "cut": share / (1.0 - tax), "share": share, "capex": total_capex,
            "depreciation": depreciation, "derived": derived, "revenue": total_revenue,
            "tax": tax, "unit": next(iter(units)), "reason": None}


def clause(m: dict, old: float, new: float, who: str) -> str:
    if m.get("cut") is None:
        return f" Checked {MARKER}: {m['reason']}, so the charge stands."
    span = f"{m['first']}" if m["first"] == m["last"] else f"{m['first']} to {m['last']}"
    how = ("depreciation and amortisation less amortisation of intangibles"
           if m["derived"] else "plant depreciation")
    lead = (f" Restated {MARKER}: {who} spent {IA._money(m['capex'], m['unit'])} on plant "
            f"over {span} against {IA._money(m['depreciation'], m['unit'])} of {how}, "
            f"{abs(m['share']):.2%} of revenue {'above' if m['share'] > 0 else 'below'} "
            f"what keeps the plant running. Taken at depreciation, the charge ")
    if old <= 0 and new <= 0:
        return lead + "stays nil."
    return lead + f"{'falls' if new < old else 'rises'} from {old:.2%} to {new:.2%}."


def restate_row(row: dict, m: dict, who: str) -> dict | None:
    source = row.get("source") or ""
    if MARKER in source:
        return None
    old = float(row["value"])
    new = old if m.get("cut") is None else max(0.0, old - m["cut"])
    return {**row, "value": new,
            "source": source.rstrip(". ") + "." + clause(m, old, new, who)}
