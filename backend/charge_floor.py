"""Let the other-costs charge fall below nil by the amortisation the cost lines carry.

Each company's ``other_costs_pct`` is solved so its book reproduces the free cash flow it
earned over a window: other = book pre-tax margin - cash pre-tax margin, where the cash
margin is free cash flow restated before interest, at replacement capex, without one-off
cash and without working capital build (``interest_addback``, ``replacement_capex``,
``one_off_cash``, ``working_capital``). A charge was
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
import working_capital as WC

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "amortisation_in_cost_lines.csv"
MARKER = "to the amortisation floor"
INSIDE = ("cost_of_sales", "sga", "rd", "split")


OTHER_REVENUES = pathlib.Path(__file__).resolve().parent.parent / "data" / "other_revenues.csv"


def other_revenues(ticker: str, path=None) -> dict:
    """{fiscal_year: amount} a filer reports beside the revenue total the model
    reconciles to, in the millions the file prints. Empty for a filer with one total."""
    source = pathlib.Path(path) if path else OTHER_REVENUES
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            if (row.get("ticker") or "").strip().upper() != ticker.upper():
                continue
            try:
                out[int(row["fiscal_year"])] = float(row["other_revenues_mm"]) * 1e6
            except (TypeError, ValueError, KeyError):
                continue
    return out


def extra_unit(ticker: str, path=None) -> str:
    source = pathlib.Path(path) if path else OTHER_REVENUES
    if not source.exists():
        return ""
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            if (row.get("ticker") or "").strip().upper() == ticker.upper():
                return (row.get("unit") or "").strip()
    return ""


def _weighted(conn, company_id: int) -> dict:
    """The book's own cost ratios, weighted by what each part sells. A company that costs
    its segments apart (Johnson & Johnson) has no single ratio to read, and a company
    whose filed lines miss a cost its seeds carry (Novo's selling expense, which the
    companyfacts API has no tag for) cannot be rebuilt from the filed lines at all."""
    rows = conn.execute(
        """SELECT a.key, a.value, COALESCE((SELECT MAX(r.value) FROM asset_revenue r
                    WHERE r.asset_id = a.asset_id AND r.period = 'FY'), 0) AS revenue
             FROM assumptions a JOIN assets s ON s.id = a.asset_id
            WHERE s.owner_company_id = ? AND a.scenario = 'base'
              AND a.indication_id IS NULL AND a.year IS NULL
              AND a.key IN ('cogs_pct', 'sga_pct', 'rd_pct')""", (company_id,)).fetchall()
    lines = conn.execute(
        """SELECT cl.key, cl.value, COALESCE((SELECT b.value * 1000000 FROM company_lines b
                    WHERE b.company_id = cl.company_id AND b.line = cl.line
                      AND b.scenario = cl.scenario AND b.key = 'base_revenue'), 0) AS revenue
             FROM company_lines cl WHERE cl.company_id = ? AND cl.scenario = 'base'
              AND cl.key IN ('cogs_pct', 'sga_pct', 'rd_pct')""", (company_id,)).fetchall()
    out = {}
    for key in ("cogs_pct", "sga_pct", "rd_pct"):
        weights = [(r["revenue"], r["value"]) for r in list(rows) + list(lines)
                   if r["key"] == key and r["value"] is not None and r["revenue"]]
        if not weights:
            return {}
        out[key] = sum(w * v for w, v in weights) / sum(w for w, _ in weights)
    return out


def _scale(revenue_unit: str, extra: str) -> float:
    """1 where the two are the same currency, 0 where they are not: a figure in another
    currency is left out rather than converted into a denominator."""
    return 1.0 if (not extra or extra == revenue_unit) else 0.0


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
    if ratios["tax_rate"] is None or ratios["tax_rate"] >= 1:
        return {**base, "new": None, "reason": "cost ratios or tax rate not on file"}
    total = sum(r["value"] for r in revenue.values())
    # The book margin comes from the filed cost lines of the year the product ratios were
    # struck on, over the revenue they were struck on. A company that costs its segments
    # separately (Johnson & Johnson) has no single product ratio to read, and one whose
    # ratios sit on net sales and other revenues together (Sanofi, Novartis, in
    # data/other_revenues.csv) would otherwise rebuild against the wrong denominator.
    extra = other_revenues(ticker)
    basis = {y: r["value"] + extra.get(y, 0.0) * _scale(r["unit"], extra_unit(ticker))
             for y, r in revenue.items()}
    weighted = _weighted(conn, cid)
    if weighted:
        ratios.update(weighted)
        base["book_basis"] = "the book's own ratios, weighted by what each part sells"
    elif any(ratios[k] is None for k in ("cogs_pct", "sga_pct", "rd_pct")):
        return {**base, "new": None, "reason": "cost ratios not on file"}
    else:
        base["book_basis"] = "the product ratios on file"
    reported_total = sum(r["value"] for r in revenue.values())
    total = sum(basis.values())
    # The restatement shares are struck on the reported revenue, so they move onto the
    # basis the ratios are struck on before they are added to the cash margin.
    onto_basis = (reported_total / total) if total else 1.0
    fcf = sum(r["value"] for r in cfo.values()) - sum(abs(r["value"]) for r in capex.values())
    tax = ratios["tax_rate"]
    cash = (fcf / total / (1.0 - tax)
            + ((IA.measure(conn, ticker).get("share") or 0.0)
               + (RC.measure(conn, ticker).get("cut") or 0.0)
               + (OC.measure(conn, ticker).get("cut") or 0.0)
               + (WC.measure(conn, ticker).get("cut") or 0.0)) * onto_basis)
    book = 1.0 - ratios["cogs_pct"] - ratios["sga_pct"] - ratios["rd_pct"]
    rebuilt = book - cash
    out = {**base, "book": book, "cash": cash, "rebuilt": rebuilt, "floor": 0.0}
    amort = amortisation(ticker, path)
    where = ((amort or {}).get("presented_in") or "").strip()
    year_revenue = revenue[last]
    unit = (((amort or {}).get("unit") or "").split() or [""])[0]
    if not amort or not (amort.get("amount") or "").strip():
        reason = "no amortisation figure on file for the filer"
    elif where not in INSIDE:
        reason = ("the filer books amortisation on a line of its own, outside the cost "
                  "lines the book uses" if where == "separate_line" else
                  "the filer does not say which line carries its amortisation")
    elif unit not in ("", year_revenue["unit"]):
        reason = "amortisation and revenue in different units"
    else:
        reason = None
        out.update(floor=-float(amort["amount"]) * 1e6 / year_revenue["value"],
                   amount=float(amort["amount"]), where=where,
                   accession=(amort.get("accession") or "").strip(),
                   unit=year_revenue["unit"], year=last)
    if rebuilt >= 0:
        return {**out, "new": None, "reason": "the charge rebuilds at or above nil, so no floor binds"}
    if reason:
        return {**out, "new": None, "reason": reason}
    return {**out, "new": max(out["floor"], rebuilt), "reason": None}


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
