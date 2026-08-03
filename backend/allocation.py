"""Where the money went, by year: the five things a pharmaceutical company spends on.

Research, plant, acquisitions, buybacks and dividends. Every one is a decision the
management took rather than a result that happened to them, and the mix is the clearest
statement of strategy a company makes: Merck spends eighteen billion on research and one
on its own shares, Johnson & Johnson spends twelve on dividends and fifteen on buying
other companies, and neither of those sentences is anywhere else in this repository.

Two of the five are not like the other three, and the view has to say so. Research and
plant are what it costs to run and grow the business, and research is expensed above the
line, so it is already inside the operating cash flow the other spending comes out of.
Acquisitions, buybacks and dividends are what is done with the money afterwards. The
total is what the company spent, not what it did with its free cash flow, and reading it
as the second would double count the research.

Every figure is a tagged annual line. A company that never tags one gets no segment for
it rather than a zero: Biogen pays no dividend and Merck reports no acquisitions in 2024,
and those are different facts from a line the filer does not publish.
"""

from __future__ import annotations

import datetime as dt

import db
from financials_view import _nearest_month_end

# The order they are drawn in, running from what the business costs to run through to
# what is handed back. Each is (key, metric, label).
USES = (
    ("rd", "ResearchAndDevelopmentExpense", "Research"),
    ("capex", "CapitalExpenditure", "Plant"),
    ("acquisitions", "AcquisitionsNet", "Acquisitions"),
    ("buybacks", "ShareRepurchases", "Buybacks"),
    ("dividends", "DividendsPaid", "Dividends"),
)

LABELS = {key: label for key, _, label in USES}

# The two that are already inside operating cash flow rather than spent out of it.
ABOVE_THE_LINE = ("rd",)

DEFAULT_YEARS = 10


def _annual(conn, company_id: int, metric: str) -> dict:
    """{fiscal year: value} for one metric, keyed on the year the period actually closes.

    Not on the stored fiscal_year column. Johnson & Johnson runs a 52/53 week calendar,
    so its fiscal 2020 closed on 3 January 2021 and is filed against 2021, which put
    every year of its spending a year late and left calendar 2020 and 2015 empty because
    no year end fell in them. The same snapping the statement labels use.
    """
    out = {}
    for row in conn.execute(
            "SELECT period_end, value FROM financials"
            "  WHERE company_id = ? AND metric = ? AND period_type = 'FY'"
            "    AND value IS NOT NULL AND period_end IS NOT NULL", (company_id, metric)):
        _, year = _nearest_month_end(dt.date.fromisoformat(row["period_end"]))
        out[year] = row["value"]
    return out


def build(db_path=None, ticker: str = "", years: int = DEFAULT_YEARS) -> dict | None:
    """The spending mix by year, newest first, or None where the ticker is unknown.

    A year with nothing tagged at all is dropped rather than drawn empty, so the chart
    starts where the filer's own disclosure does.
    """
    ticker = ticker.upper()
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()
        if company is None:
            return None
        series = {key: _annual(conn, company["id"], metric) for key, metric, _ in USES}
        operating = _annual(conn, company["id"], "CashFlowOperating")
        shares = _annual(conn, company["id"], "WeightedAverageDilutedShares")
        currency = conn.execute(
            "SELECT unit FROM financials WHERE company_id = ? AND metric = 'Revenues'"
            "  AND unit IS NOT NULL ORDER BY fiscal_year DESC LIMIT 1",
            (company["id"],)).fetchone()
    finally:
        conn.close()

    seen = {year for values in series.values() for year in values}
    rows = []
    for year in sorted(seen, reverse=True)[:years]:
        spend = {key: series[key].get(year) for key, _, _ in USES}
        if not any(value for value in spend.values()):
            continue
        rows.append({"fiscal_year": year, **spend,
                     "operating": operating.get(year),
                     "shares": shares.get(year)})

    # Lines this filer never tags in the window, which is not the same as lines it
    # reports as nothing. Johnson & Johnson tags zero acquisitions for fiscal 2023 and
    # tags it three times, in three consecutive annual reports: it bought nothing that
    # year, having closed Abiomed in the one before. Biogen does not tag a dividend line
    # at all. Neither draws a segment, because neither has a width, and only the second
    # is an absence of disclosure.
    untagged = [label for key, _, label in USES
                if all(row.get(key) is None for row in rows)]
    # Where a use is reported and reported as nothing, so the panel can say so rather
    # than leave a gap that reads like the line above.
    reported_nil = {key: [row["fiscal_year"] for row in rows if row.get(key) == 0]
                    for key, _, _ in USES}
    reported_nil = {key: years for key, years in reported_nil.items() if years}
    return {"ticker": ticker, "currency": (currency or {})["unit"] if currency else None,
            "years": rows, "untagged": untagged,
            "reported_nil": {LABELS[key]: years
                             for key, years in reported_nil.items()}}
