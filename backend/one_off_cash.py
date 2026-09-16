"""Take one-off cash out of each company's other-costs charge.

Each company's ``other_costs_pct`` is solved so its book reproduces the free cash flow it
earned over a window of years (``interest_addback.WINDOWS``). Three kinds of payment sit
inside that operating cash flow and do not recur, so charging them on every product for
ever takes them off the valuation many times over:

- **Deal payments.** Upfront, milestone, option and continuation payments for licensed or
  acquired pipeline, where the filer books them in operating cash flow. Merck paid $8.3bn
  of them over 2023 to 2025 and none of what they bought is a cost of running the book.
  They are capital allocation. A sum of the parts values what past deals bought as assets,
  and takes future deals as worth what they cost. So the cost comes out of the charge, and
  the assets go into the book as seeds. A filer that books this cash under investing (Lilly,
  AbbVie, Bristol and the five European filers do) has nothing to take out, since free cash
  flow never carried it.
- **Legal settlements** paid in the window, named with an amount by the filer: Merck's
  $572.5mm Zetia antitrust settlement in 2023.
- **The US transition tax** of the Tax Cuts and Jobs Act, the tax on accumulated foreign
  earnings, paid in eight instalments to 2025 (Pfizer's to 2026). Only an instalment the
  filer states it paid is counted: a fall in the stated balance is not cash, since Merck's
  is shown net of foreign tax credits.

The charge was solved as other = book pre-tax margin - FCF margin / (1 - tax). A deal
payment or a settlement is deductible, so adding it back net of tax lowers the charge by
the payment over revenue, as the interest add-back does. The transition tax is itself a
tax and is added back gross, lowering the charge by the payment over revenue over one
minus tax. A charge cannot fall below nil.

The amounts are read off each filer's annual reports into ``data/cash_one_offs.csv``, with
a verbatim quote per row.
"""

from __future__ import annotations

import csv
import pathlib

import interest_addback as IA
import replacement_capex as RC

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "cash_one_offs.csv"
MARKER = "without one-off cash"


def rows_for(ticker: str, path=None) -> list[dict]:
    source = pathlib.Path(path) if path else DATA
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#")]
    out = []
    for row in csv.DictReader(lines):
        if (row.get("ticker") or "").strip().upper() != ticker.upper():
            continue
        try:
            row["fiscal_year"] = int(row["fiscal_year"])
            row["amount"] = float(row["amount"])
        except (TypeError, ValueError, KeyError):
            continue
        out.append(row)
    return out


def _transition_paid(rows: list[dict], first: int, last: int) -> tuple[float, str | None]:
    """(paid over the window in millions, how it was read): the instalments the filer
    states it paid, year by year. A fall in the stated balance is not taken as a payment.
    Merck's 2024 balance is shown net of $702mm of foreign tax credits, and Pfizer's fell
    partly on an amended return, so the difference between two balances is not cash.
    A year with no stated instalment counts nothing."""
    paid = {r["fiscal_year"]: r["amount"] for r in rows
            if r["kind"] == "transition_tax" and first <= r["fiscal_year"] <= last}
    read = [f"{year} instalment {amount:,.0f}mm" for year, amount in sorted(paid.items())]
    return sum(paid.values()), ("; ".join(read) if read else None)


def measure(conn, ticker: str, path=None) -> dict:
    """The one-off cash in the company's window and the cut to its charge. ``cut`` is
    None, with ``reason``, wherever nothing should change."""
    ticker = ticker.upper()
    window = IA.WINDOWS.get(ticker)
    company = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    if not window or company is None:
        return {"ticker": ticker, "cut": None, "reason": "no calibration window on file"}
    first, last = window
    base = {"ticker": ticker, "first": first, "last": last}
    rows = [r for r in rows_for(ticker, path)
            if first - 1 <= r["fiscal_year"] <= last]
    revenue = IA.fy_series(conn, company["id"], "Revenues", first, last)
    if set(revenue) != set(range(first, last + 1)):
        return {**base, "cut": None, "reason": "revenue is not on file for every year"}
    units = {r["unit"] for r in revenue.values()}
    if len(units) != 1:
        return {**base, "cut": None, "reason": "revenue in more than one unit"}
    unit = next(iter(units))
    # A row printed only in another currency is left out rather than converted: Sanofi
    # states its Plavix settlement in dollars and reports in euros.
    foreign = [r for r in rows if (r.get("unit") or "").strip() not in ("", unit)
               and r["kind"] in ("deal_payments", "legal_settlement", "transition_tax")
               and first <= r["fiscal_year"] <= last]
    rows = [r for r in rows if r not in foreign]
    in_window = [r for r in rows if first <= r["fiscal_year"] <= last]
    base["left_out"] = [f"{r['amount']:,.0f}mm {r['unit']} of {r['kind'].replace('_', ' ')} in "
                        f"{r['fiscal_year']}, printed only in {r['unit']}" for r in foreign]
    deals = sum(r["amount"] for r in in_window if r["kind"] == "deal_payments")
    settlements = sum(r["amount"] for r in in_window if r["kind"] == "legal_settlement")
    transition, transition_basis = _transition_paid(rows, first, last)
    if not (deals or settlements or transition):
        investing = any(r["kind"] == "deal_payments_investing" for r in rows)
        return {**base, "cut": None,
                "reason": ("deal payments are booked under investing, so free cash flow "
                           "never carried them, and no settlement or transition tax is "
                           "stated for the window") if investing else
                          "no one-off cash stated for the window"}
    tax = RC._tax(conn, company["id"])
    if tax is None or tax >= 1:
        return {**base, "cut": None, "reason": "no tax rate on file"}
    total = sum(r["value"] for r in revenue.values())
    cut = (deals + settlements) * 1e6 / total + transition * 1e6 / total / (1.0 - tax)
    return {**base, "cut": cut, "deals": deals, "settlements": settlements,
            "transition": transition, "transition_basis": transition_basis,
            "revenue": total, "unit": unit, "tax": tax, "reason": None}


def _mm(value: float, unit: str) -> str:
    return IA._money(value * 1e6, unit)


def clause(m: dict, old: float, new: float) -> str:
    if m.get("cut") is None:
        left = (f" Left out: {'; '.join(m['left_out'])}, rather than converted."
                if m.get("left_out") else "")
        return f" Checked {MARKER}: {m['reason']}, so the charge stands.{left}"
    span = f"{m['first']}" if m["first"] == m["last"] else f"{m['first']} to {m['last']}"
    parts = []
    if m["deals"]:
        parts.append(f"{_mm(m['deals'], m['unit'])} of deal payments in operating cash flow, "
                     "capital allocation whose assets the book values separately")
    if m["settlements"]:
        parts.append(f"{_mm(m['settlements'], m['unit'])} of legal settlements")
    if m["transition"]:
        parts.append(f"{_mm(m['transition'], m['unit'])} of US transition tax "
                     f"({m['transition_basis']})")
    left = (f" Left out: {'; '.join(m['left_out'])}, rather than converted."
            if m.get("left_out") else "")
    lead = (f" Restated {MARKER}: {m['ticker']}'s free cash flow over {span} carried "
            + "; ".join(parts) + "." + left + " None recurs, so the charge ")
    if old <= 0 and new <= 0:
        return lead + "stays nil."
    return lead + f"falls from {old:.2%} to {new:.2%}."


def restate_row(row: dict, m: dict) -> dict | None:
    """The row with its value and source restated, or None when already done."""
    source = row.get("source") or ""
    if MARKER in source:
        return None
    old = float(row["value"])
    new = old if m.get("cut") is None else max(0.0, old - m["cut"])
    return {**row, "value": new, "source": source.rstrip(". ") + "." + clause(m, old, new)}
