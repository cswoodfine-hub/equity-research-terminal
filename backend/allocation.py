"""Where the money went, by year: the things a pharmaceutical company spends on.

Research done, research bought, plant, acquisitions, buybacks and dividends. Every one is
a decision the management took rather than a result that happened to them, and the mix is
the clearest statement of strategy a company makes: Merck spends eighteen billion on
research and one on its own shares, Johnson & Johnson spends twelve on dividends and
fifteen on buying other companies, Lilly buys three billion a year of other people's
molecules outright, and none of those sentences is anywhere else in this repository.

Research is not like the rest, and the view has to say so. It is expensed above the line,
so it is already inside the operating cash flow everything else is spent out of, while
plant, molecules, companies, buybacks and dividends are all paid for from that cash. The
total is what the company spent, not what it did with its free cash flow, and reading it
as the second would count the research twice.

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
    # Molecules bought outright, which for some filers is the whole deal budget. Lilly
    # structures most of its business development as asset acquisitions rather than
    # business combinations: buying a company whose only asset is a compound is an asset
    # purchase under ASC 805, the in-process research is written off at once instead of
    # becoming goodwill, and no line called acquisitions is ever tagged. Three billion a
    # year of Lilly's spending sat in no segment because of it.
    #
    # It does not double count the research above. Where a filer publishes research both
    # ways, the statement layer takes the figure that excludes acquired in-process cost,
    # which is what Lilly's 13.3bn is.
    ("acquired_rd", "AcquiredIprd", "Acquired R&D"),
    # Only drawn where the filer's research figure is known to exclude it: see
    # SEPARABLE_ACQUIRED_RD below.
    ("capex", "CapitalExpenditure", "Plant"),
    ("acquisitions", "AcquisitionsNet", "Acquisitions"),
    ("buybacks", "ShareRepurchases", "Buybacks"),
    ("dividends", "DividendsPaid", "Dividends"),
)

LABELS = {key: label for key, _, label in USES}

# The two that are already inside operating cash flow rather than spent out of it.
ABOVE_THE_LINE = ("rd",)

DEFAULT_YEARS = 10

# Cash paid for in-process research can only be drawn next to research expense where the
# research expense is known not to contain it, and that is only true of a filer that
# publishes the excluding-acquired concept. Lilly, Biogen and Vertex do. Allogene does
# not, and its 2018 research of 152m is 109m of acquired in-process cost with the rest
# spent in the labs, so drawing both would count that 109m twice and overstate what the
# company spent by two thirds. Where the filer is silent the segment is dropped rather
# than guessed, and the money stays inside research where the filer put it.
SEPARABLE_ACQUIRED_RD = "ResearchExcludingAcquiredIprd"


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
        separable = _annual(conn, company["id"], SEPARABLE_ACQUIRED_RD)
        operating = _annual(conn, company["id"], "CashFlowOperating")
        shares = _annual(conn, company["id"], "WeightedAverageDilutedShares")
        currency = conn.execute(
            "SELECT unit FROM financials WHERE company_id = ? AND metric = 'Revenues'"
            "  AND unit IS NOT NULL ORDER BY fiscal_year DESC LIMIT 1",
            (company["id"],)).fetchone()
    finally:
        conn.close()

    # Per year, since a filer can start publishing the excluding concept partway through
    # the window: Lilly's runs from 2021 and the years before it are plain-tag years.
    inside_research = sorted(
        (year for year in series["acquired_rd"] if year not in separable), reverse=True)
    series["acquired_rd"] = {year: value for year, value in series["acquired_rd"].items()
                             if year in separable}

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
    #
    # Acquired research is never named here. Allogene does tag it, so saying the line is
    # not filed would be untrue; it is folded into research instead, and ``inside_research``
    # is how the panel says which years that happened in.
    untagged = [label for key, _, label in USES
                if key != "acquired_rd" and all(row.get(key) is None for row in rows)]
    # Where a use is reported and reported as nothing, so the panel can say so rather
    # than leave a gap that reads like the line above.
    reported_nil = {key: [row["fiscal_year"] for row in rows if row.get(key) == 0]
                    for key, _, _ in USES}
    reported_nil = {key: years for key, years in reported_nil.items() if years}
    drawn = {row["fiscal_year"] for row in rows}
    return {"ticker": ticker, "currency": (currency or {})["unit"] if currency else None,
            "years": rows, "untagged": untagged,
            "inside_research": [year for year in inside_research if year in drawn],
            "reported_nil": {LABELS[key]: years
                             for key, years in reported_nil.items()}}
