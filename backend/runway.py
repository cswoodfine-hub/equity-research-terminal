"""How long a company that sells nothing can keep going.

For a commercial pharma the question is revenue durability: what comes off patent, what
replaces it. None of that machinery means anything for a clinical-stage biotech. It has
no product revenue, no exclusivity to lose and no margin to defend, and 52 of the 70
companies in this universe have no exclusivity row at all. What it has instead is a pile
of cash, a rate of spending it, and a set of dates it has to reach before the pile runs
out. Runway is the number every other question hangs off: it sets dilution risk, it sets
negotiating position in a partnering talk, and it decides whether a readout eighteen
months away is financeable.

Three things this is careful about.

Cash is not the cash line. A biotech parks its runway in marketable securities, so
short-term investments are added where the filer tags them. Reading the cash line alone
understated Intellia by roughly half. Where a filer does not tag short-term investments
the figure is cash only, and the row says so rather than quietly reporting a shorter
runway than the company has.

Burn is trailing, not annualised. EDGAR reports cash flow cumulatively from the start of
the year, so a Q3 filing carries nine months and a Q1 filing three. Annualising whichever
partial arrived last turns one heavy quarter into a year of it. The trailing twelve
months is reconstructed instead, from the last full year plus the current partial minus
the same partial a year earlier.

And it is a rate, not a forecast. Runway here is months at the current burn, which is
what the filings support. It is not a prediction: companies raise, cut, and partner, and
the number moves the day they do. Nothing here models that.
"""

from __future__ import annotations

import datetime as dt

import db

# What marks a company that sells something. A firm that manufactures and sells a drug
# carries inventory and reports a cost of revenue; a clinical-stage one does neither.
# Both are read rather than either alone, because a filer can tag one and not the other.
#
# The obvious alternative, "does it have product revenue rows", is a fact about our own
# extraction rather than about the company, and it put AbbVie in the clinical bucket.
_COMMERCIAL_METRICS = ("Inventory", "CostOfRevenue")

COMMERCIAL = "commercial"
CLINICAL = "clinical"
UNKNOWN = "unknown"

# Cumulative periods, in months, as EDGAR labels them.
_PARTIALS = {"3M": 3, "6M": 6, "9M": 9}

# Below this share of R&D spend, a trailing cash burn is being offset by a receipt
# rather than describing what the company costs to run. Half is the line: a normal
# biotech burns somewhat less cash than its accrued R&D, because of working capital and
# collaboration income, and the companies here sit between 0.5 and 0.9. Arrowhead sits
# at 0.06.
BURN_VS_RD = 0.5


def stage(conn, company_id: int) -> str:
    """Whether a company sells a product, on the evidence of its own filings.

    Returns "unknown" rather than "clinical" when there are no financials at all. Roche
    and Bayer are not SEC registrants, and reading their silence as a company with no
    product would be badly wrong about two of the largest drugmakers alive.
    """
    any_financials = conn.execute(
        "SELECT 1 FROM financials WHERE company_id = ? LIMIT 1", (company_id,)).fetchone()
    if not any_financials:
        return UNKNOWN
    marks = ",".join("?" * len(_COMMERCIAL_METRICS))
    sells = conn.execute(
        f"SELECT 1 FROM financials WHERE company_id = ? AND metric IN ({marks})"
        "  AND value > 0 LIMIT 1", (company_id, *_COMMERCIAL_METRICS)).fetchone()
    return COMMERCIAL if sells else CLINICAL


def liquidity(conn, company_id: int) -> dict:
    """Cash plus short-term investments at the most recent balance sheet date.

    Both are read at the same date, so the total is a balance sheet rather than two
    dates added together.
    """
    cash_row = conn.execute(
        "SELECT period_end, value FROM financials"
        "  WHERE company_id = ? AND metric = 'CashAndEquivalents' AND value IS NOT NULL"
        "  ORDER BY period_end DESC LIMIT 1", (company_id,)).fetchone()
    if cash_row is None:
        return {"cash": None, "as_of": None, "includes_investments": False,
                "short_term": None, "long_term": None, "cash_only": None}
    as_of = cash_row["period_end"]
    # Both maturities, because that is what a company's own runway guidance counts when
    # it says "cash, cash equivalents and marketable securities sufficient to fund
    # operations into". Long-term securities are reachable and routinely liquidated; the
    # split is kept in the row so a reader can be more conservative if they want to be.
    parts = {}
    for metric in ("ShortTermInvestments", "LongTermInvestments"):
        row = conn.execute(
            "SELECT value FROM financials WHERE company_id = ? AND metric = ?"
            "  AND period_end = ?", (company_id, metric, as_of)).fetchone()
        if row and row["value"]:
            parts[metric] = row["value"]
    total = cash_row["value"] + sum(parts.values())
    return {"cash": total, "as_of": as_of,
            "includes_investments": bool(parts),
            "short_term": parts.get("ShortTermInvestments"),
            "long_term": parts.get("LongTermInvestments"),
            "cash_only": cash_row["value"]}


def trailing_burn(conn, company_id: int) -> dict:
    """Operating cash flow over the trailing twelve months, and how it was built.

    EDGAR states cash flow from the start of the fiscal year, so the latest filing is a
    3, 6, 9 or 12 month figure. Twelve months is reconstructed as the last full year plus
    the current partial minus the same partial a year earlier. When the newest figure is
    itself a full year, that is used unchanged.
    """
    latest = conn.execute(
        "SELECT period_end, period_type, fiscal_year, fiscal_period, value"
        "  FROM financials WHERE company_id = ? AND metric = 'CashFlowOperating'"
        "    AND value IS NOT NULL AND period_type IN ('Q', 'YTD', 'FY')"
        "  ORDER BY period_end DESC LIMIT 1", (company_id,)).fetchone()
    if latest is None:
        return {"burn": None, "basis": None, "as_of": None}

    if latest["period_type"] == "FY" or latest["fiscal_period"] == "12M":
        return {"burn": latest["value"], "basis": "last full year",
                "as_of": latest["period_end"]}

    months = _PARTIALS.get(latest["fiscal_period"] or "")
    prior_fy = conn.execute(
        "SELECT value FROM financials WHERE company_id = ?"
        "  AND metric = 'CashFlowOperating' AND period_type = 'FY'"
        "  AND fiscal_year = ? AND value IS NOT NULL LIMIT 1",
        (company_id, (latest["fiscal_year"] or 0) - 1)).fetchone()
    prior_partial = conn.execute(
        "SELECT value FROM financials WHERE company_id = ?"
        "  AND metric = 'CashFlowOperating' AND fiscal_year = ?"
        "  AND fiscal_period = ? AND value IS NOT NULL LIMIT 1",
        (company_id, (latest["fiscal_year"] or 0) - 1, latest["fiscal_period"])).fetchone()

    if prior_fy and prior_partial:
        return {"burn": prior_fy["value"] - prior_partial["value"] + latest["value"],
                "basis": f"trailing twelve months to {latest['period_end']}",
                "as_of": latest["period_end"]}
    if prior_fy:
        # No matching partial a year back, so the full year is the honest answer. It is
        # staler than a trailing figure and is labelled as such rather than patched with
        # an annualised quarter, which would read one heavy quarter as a whole year.
        return {"burn": prior_fy["value"], "basis": "last full year",
                "as_of": latest["period_end"]}
    if months:
        return {"burn": latest["value"] * 12 / months,
                "basis": f"{months} months annualised, no prior year to compare",
                "as_of": latest["period_end"]}
    return {"burn": None, "basis": None, "as_of": latest["period_end"]}


def for_company(db_path=None, ticker: str = "", today=None) -> dict | None:
    """Runway and its inputs for one company, or None when the ticker is unknown."""
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id, ticker, name FROM companies WHERE ticker = ?",
            (ticker.upper(),)).fetchone()
        if company is None:
            return None
        return _row(conn, company, today)
    finally:
        conn.close()


def _row(conn, company, today) -> dict:
    money = liquidity(conn, company["id"])
    burn = trailing_burn(conn, company["id"])
    months = None
    # Only a company spending cash has a runway. A cash generative one is not months
    # from anything, and dividing by a positive number would print a negative figure
    # that reads like an emergency.
    if money["cash"] and burn["burn"] is not None and burn["burn"] < 0:
        months = money["cash"] / (abs(burn["burn"]) / 12)

    catalysts = []
    if months:
        horizon = (today + dt.timedelta(days=int(months * 30.4))).isoformat()
        catalysts = [dict(r) for r in conn.execute(
            "SELECT title, expected_date, catalyst_type FROM catalysts"
            "  WHERE company_id = ? AND expected_date IS NOT NULL"
            "    AND expected_date >= ? AND expected_date <= ?"
            "  ORDER BY expected_date", (company["id"], today.isoformat(), horizon))]

    rd = conn.execute(
        "SELECT value FROM financials WHERE company_id = ?"
        "  AND metric = 'ResearchAndDevelopmentExpense' AND period_type = 'FY'"
        "  ORDER BY period_end DESC LIMIT 1", (company["id"],)).fetchone()
    rd_value = rd["value"] if rd else None

    return {
        "ticker": company["ticker"], "name": company["name"],
        "stage": stage(conn, company["id"]),
        "cash": money["cash"], "cash_as_of": money["as_of"],
        "includes_investments": money["includes_investments"],
        "cash_only": money["cash_only"],
        "short_term": money.get("short_term"), "long_term": money.get("long_term"),
        "burn_annual": burn["burn"], "burn_basis": burn["basis"],
        "runway_months": months,
        # What the money is being spent on. R&D running at most of the burn is a company
        # spending on science; well under it is one spending on everything else.
        "rd_annual": rd_value,
        # Cash burn well below R&D spend means a receipt is paying for the research: an
        # upfront licence payment, a milestone, an equity partner's share. Arrowhead
        # burned 36m against 607m of R&D after a large licensing deal, which prints a
        # runway of 49 years. The number is what the filings say and is left standing;
        # the flag says not to read it as the underlying rate.
        "burn_flattered": (rd_value is not None and burn["burn"] is not None
                           and burn["burn"] < 0
                           and abs(burn["burn"]) < BURN_VS_RD * rd_value),
        "catalysts_in_runway": catalysts,
        "catalyst_count": len(catalysts),
    }


def build(db_path=None, today=None, stage_filter: str | None = CLINICAL) -> list:
    """Every company, or every clinical-stage one, ranked by how little runway is left.

    Shortest first, because that is the order the risk sits in.
    """
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        rows = []
        for company in conn.execute("SELECT id, ticker, name FROM companies"):
            row = _row(conn, company, today)
            if stage_filter and row["stage"] != stage_filter:
                continue
            rows.append(row)
    finally:
        conn.close()
    # A company with no runway figure sorts last rather than first: absence of data is
    # not urgency, and putting it at the top of a risk-ordered list would read as such.
    return sorted(rows, key=lambda r: (r["runway_months"] is None,
                                       r["runway_months"] or 0))
