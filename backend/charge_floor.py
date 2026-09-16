"""Let the other-costs charge fall below nil by the amortisation the cost lines carry.

Each company's ``other_costs_pct`` is solved so its book reproduces the free cash flow it
earned over a window: other = book pre-tax margin - cash pre-tax margin, where the cash
margin is free cash flow restated before interest, at replacement capex and without
one-off cash (``interest_addback``, ``replacement_capex``, ``one_off_cash``). A charge was
never allowed below nil, on the reasoning that it should not credit the book with cash its
own costs do not leave.

That reasoning holds for cash costs, and the three filed lines are not all cash. AbbVie
books $7,377mm of amortisation of acquired intangibles inside cost of products sold, 12.1%
of revenue, so its lines leave a 32.5% margin where its cash supports 38.4%. The charge
solved to -5.9% and was held at nil, and every AbbVie product lost 5.9 points of margin.
Twelve of the eighteen companies were held at nil the same way.

So the floor is now minus the amortisation of acquired intangibles the filer books inside
cost of sales, SG&A or R&D, as its own annual report states, over revenue in the same year.
A charge can fall that far and no further: below it the book would be crediting cash that
no non-cash cost in its lines explains. A filer that presents amortisation on a line of its
own, or does not say where, keeps the floor at nil. Stock compensation is non-cash too, and
stays a cost, since it is paid for in shares.

Only a charge held at nil moves. The rebuild of the charge from the filed figures is checked
against the charges on file that were never floored, and reproduces them.
"""

from __future__ import annotations

import csv
import pathlib

import interest_addback as IA
import one_off_cash as OC
import replacement_capex as RC

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "amortisation_in_cost_lines.csv"
MARKER = "to the amortisation floor"
INSIDE = ("cost_of_sales", "sga", "rd", "split")


def amortisation(ticker: str, path=None) -> dict | None:
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return None
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            if (row.get("ticker") or "").strip().upper() == ticker.upper():
                return row
    return None


def _modal(conn, company_id: int, key: str):
    row = conn.execute(
        """SELECT a.value, COUNT(*) n FROM assumptions a JOIN assets s ON s.id = a.asset_id
            WHERE s.owner_company_id = ? AND a.scenario = 'base' AND a.key = ?
              AND a.indication_id IS NULL AND a.value IS NOT NULL
            GROUP BY a.value ORDER BY n DESC LIMIT 1""", (company_id, key)).fetchone()
    return row["value"] if row else None


def measure(conn, ticker: str, path=None) -> dict:
    """The charge rebuilt from the filed figures, and the floor under it. ``new`` is the
    charge a nil row takes, or None, with ``reason``, where it stays at nil."""
    ticker = ticker.upper()
    window = IA.WINDOWS.get(ticker)
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    if not window or company is None:
        return {"ticker": ticker, "new": None, "reason": "no calibration window on file"}
    first, last = window
    cid = company["id"]
    base = {"ticker": ticker, "first": first, "last": last}
    revenue = IA.fy_series(conn, cid, "Revenues", first, last)
    cfo = IA.fy_series(conn, cid, "CashFlowOperating", first, last)
    capex = IA.fy_series(conn, cid, "CapitalExpenditure", first, last)
    years = set(range(first, last + 1))
    if not (set(revenue) == set(cfo) == set(capex) == years):
        return {**base, "new": None, "reason": "revenue, operating cash or capex missing for a year"}
    ratios = {k: _modal(conn, cid, k) for k in ("cogs_pct", "sga_pct", "rd_pct", "tax_rate")}
    if any(v is None for v in ratios.values()) or ratios["tax_rate"] >= 1:
        return {**base, "new": None, "reason": "cost ratios or tax rate not on file"}
    total = sum(r["value"] for r in revenue.values())
    fcf = sum(r["value"] for r in cfo.values()) - sum(abs(r["value"]) for r in capex.values())
    tax = ratios["tax_rate"]
    cash = (fcf / total / (1.0 - tax) + (IA.measure(conn, ticker).get("share") or 0.0)
            + (RC.measure(conn, ticker).get("cut") or 0.0)
            + (OC.measure(conn, ticker).get("cut") or 0.0))
    book = 1.0 - ratios["cogs_pct"] - ratios["sga_pct"] - ratios["rd_pct"]
    rebuilt = book - cash
    out = {**base, "book": book, "cash": cash, "rebuilt": rebuilt}
    if rebuilt >= 0:
        return {**out, "new": None, "reason": "the charge rebuilds at or above nil, so no floor binds"}
    amort = amortisation(ticker, path)
    if not amort or not (amort.get("amount") or "").strip():
        return {**out, "new": None, "reason": "no amortisation figure on file for the filer"}
    where = (amort.get("presented_in") or "").strip()
    if where not in INSIDE:
        return {**out, "new": None,
                "reason": ("the filer books amortisation on a line of its own, outside the cost "
                           "lines the book uses" if where == "separate_line" else
                           "the filer does not say which line carries its amortisation")}
    year_revenue = revenue[last]
    unit = ((amort.get("unit") or "").split() or [""])[0]
    if unit not in ("", year_revenue["unit"]):
        return {**out, "new": None, "reason": "amortisation and revenue in different units"}
    floor = -float(amort["amount"]) * 1e6 / year_revenue["value"]
    return {**out, "new": max(floor, rebuilt), "floor": floor, "amount": float(amort["amount"]),
            "where": where, "accession": (amort.get("accession") or "").strip(),
            "unit": year_revenue["unit"], "year": last, "reason": None}


def clause(m: dict) -> str:
    span = f"{m['first']}" if m["first"] == m["last"] else f"{m['first']} to {m['last']}"
    lines = {"cost_of_sales": "cost of sales", "sga": "SG&A", "rd": "R&D",
             "split": "its cost lines"}[m["where"]]
    bound = ("the charge takes the rebuilt figure" if m["new"] > m["floor"]
             else "the charge stops at that floor")
    return (f" Restated {MARKER}: the filed cost lines leave a {m['book']:.2%} pre-tax margin "
            f"where the cash over {span} supports {m['cash']:.2%}, so the charge rebuilds at "
            f"{m['rebuilt']:+.2%}. It was held at nil, but {m['ticker']} books "
            f"{IA._money(m['amount'] * 1e6, m['unit'])} of non-cash amortisation of acquired "
            f"intangibles inside {lines} in FY{m['year']} ({m['accession']}), "
            f"{-m['floor']:.2%} of revenue, so {bound}: {m['new']:+.2%}.")


def restate_row(row: dict, m: dict) -> dict | None:
    """A nil charge moved below nil, or None where nothing changes or it is done."""
    source = row.get("source") or ""
    if MARKER in source or m.get("new") is None or abs(float(row["value"])) > 1e-12:
        return None
    return {**row, "value": m["new"], "source": source.rstrip(". ") + "." + clause(m)}
