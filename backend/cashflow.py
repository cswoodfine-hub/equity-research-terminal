"""Cash generation and leverage, derived from figures already filed.

Nothing here is a new source. Operating cash flow and capital expenditure are both
stored and were never subtracted, which left the app showing what a company earned but
never what it kept. These are the first figures an analyst reaches for, and the two that
decide who can afford the next acquisition.

Every ratio is null when any of its inputs is missing, and the inputs travel with the
result so a blank is explained by the line that was absent rather than looking like a
zero. Debt and cash are balance sheet instants, so they are taken at the latest date
available; cash flow and earnings are the latest full year, since a quarter of cash flow
against a year of debt would compare two different things.
"""

from __future__ import annotations

import db
import fx

# Net debt is debt less the cash that could repay it. Short-term investments are counted
# when the filer reports them, since they are cash in all but name at this horizon; the
# result records whether they were included so the definition is never ambiguous.
_CASH_LINES = ("CashAndEquivalents", "ShortTermInvestments")


def _fy(conn, cid, metric):
    """The latest full fiscal year of a flow line, or None."""
    return conn.execute(
        """
        SELECT value, unit, fiscal_year FROM financials
         WHERE company_id = ? AND metric = ? AND period_type = 'FY'
         ORDER BY fiscal_year DESC LIMIT 1
        """, (cid, metric)).fetchone()


def _instant(conn, cid, metric):
    """The latest balance sheet value of a stock line, or None."""
    return conn.execute(
        """
        SELECT value, unit, period_end FROM financials
         WHERE company_id = ? AND metric = ? AND period_type = 'instant'
         ORDER BY period_end DESC LIMIT 1
        """, (cid, metric)).fetchone()


def _ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def build_cashflow(db_path=None, ticker: str = "") -> dict | None:
    """Cash generation and leverage for one company. None when the ticker is unknown."""
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
        if company is None:
            return None
        cid = company["id"]

        revenue = _fy(conn, cid, "Revenues")
        net_income = _fy(conn, cid, "NetIncomeLoss")
        cfo = _fy(conn, cid, "CashFlowOperating")
        capex = _fy(conn, cid, "CapitalExpenditure")
        operating = _fy(conn, cid, "OperatingIncomeLoss")
        dna = _fy(conn, cid, "DepreciationAndAmortisation")
        cost_of_revenue = _fy(conn, cid, "CostOfRevenue")
        rd = _fy(conn, cid, "ResearchAndDevelopmentExpense")
        sga = _fy(conn, cid, "SellingGeneralAndAdministrative")
        debt = _instant(conn, cid, "TotalDebt")
        cash_rows = {name: _instant(conn, cid, name) for name in _CASH_LINES}
        rates = fx.latest_usd_rates(db_path)
    finally:
        conn.close()

    currency = (revenue or cfo or {}) and (revenue["unit"] if revenue else cfo["unit"])

    def val(row):
        return row["value"] if row else None

    # Capital expenditure is filed as a positive outflow by some and a negative by
    # others, so its sign is taken from the magnitude rather than trusted.
    capex_value = abs(val(capex)) if val(capex) is not None else None
    cfo_value = val(cfo)
    fcf = (cfo_value - capex_value
           if cfo_value is not None and capex_value is not None else None)

    cash_value = None
    cash_lines_used = []
    for name, row in cash_rows.items():
        if val(row) is not None:
            cash_value = (cash_value or 0) + val(row)
            cash_lines_used.append(name)
    net_debt = (val(debt) - cash_value
                if val(debt) is not None and cash_value is not None else None)

    # Operating income is not tagged by every filer: Lilly reports its way down to income
    # before tax without it, which left the leverage multiple blank while every line it
    # is made of was on file. Where it is missing, it is the subtraction the income
    # statement already shows, and marked as arithmetic rather than a filed figure. It
    # is not attempted unless all three deductions are present, so a partial statement
    # cannot produce an operating income that quietly omits a cost.
    operating_value, operating_basis = val(operating), "reported"
    if operating_value is None:
        parts = [val(revenue), val(cost_of_revenue), val(rd), val(sga)]
        if all(p is not None for p in parts):
            operating_value = parts[0] - abs(parts[1]) - abs(parts[2]) - abs(parts[3])
            operating_basis = "derived from revenue less cost of sales, R&D and SG&A"
        else:
            operating_basis = None

    ebitda = (operating_value + abs(val(dna))
              if operating_value is not None and val(dna) is not None else None)

    def usd(value):
        if value is None or not currency:
            return None
        return value if currency == "USD" else fx.to_usd(value, currency, rates)

    return {
        "ticker": ticker.upper(),
        "fiscal_year": revenue["fiscal_year"] if revenue else None,
        "currency": currency,
        # The absolutes, filed and in dollars, so one company reads against another.
        "fcf": fcf,
        "fcf_usd": usd(fcf),
        "net_debt": net_debt,
        "net_debt_usd": usd(net_debt),
        "ebitda": ebitda,
        "ebitda_usd": usd(ebitda),
        # The ratios, which are currency-internal and need no conversion.
        "fcf_margin": _ratio(fcf, val(revenue)),
        # Cash conversion above one means profit is arriving as cash; below it, earnings
        # are running ahead of the money. Undefined on a loss, where the ratio inverts.
        "cash_conversion": (_ratio(fcf, val(net_income))
                            if (val(net_income) or 0) > 0 else None),
        "net_debt_ebitda": _ratio(net_debt, ebitda),
        # What each figure was built from, so a blank names its missing line.
        "inputs": {
            "revenue": val(revenue), "net_income": val(net_income),
            "cash_flow_operating": cfo_value, "capital_expenditure": capex_value,
            "operating_income": operating_value,
            "operating_income_basis": operating_basis,
            "depreciation_amortisation": val(dna),
            "total_debt": val(debt), "cash": cash_value,
            "cash_lines": cash_lines_used,
            "debt_as_of": debt["period_end"] if debt else None,
        },
    }
