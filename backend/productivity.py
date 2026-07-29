"""R&D productivity for the commercial-stage names, on the free data.

Spend per approval is the metric everyone quotes and it answers almost nothing. It
divides one year's research budget by an output that budget did not buy, since the drugs
approved this year were paid for a decade ago, and it says nothing about whether the
approvals are worth having. The interesting question is not how much a company spends
per approval, it is whether the portfolio is renewing itself.

So the headline here is portfolio freshness: the share of a company's product revenue
that comes from drugs approved in the last five years. It is a productivity measure that
lands on the income statement rather than in a count, and it separates the universe
sharply. Lilly earns 73% of its identified product revenue from drugs approved since
2021, Novo 35%, Merck 6% and Bristol Myers 3%.

It is reported for eight of the large names and refused for the rest, with the reason
given. The limit is the revenue table rather than the idea: it stores what a filing
disaggregates, and a filing disaggregates more than products, so for Pfizer only 28% of
those rows map to a drug with a known approval date. A share computed on the remainder
would say more about the extractor than about the company.

What this deliberately does not do, because the data will not carry it:

Trends over a decade. The trials table holds studies that are still running, so
programmes started in 2016 have completed and left it while 2025's are all present. The
start dates run 20 trials in 2016 against 736 in 2025, which is survivorship and not a
pipeline boom, and reporting it as one would invert the finding.

Development timelines. First-in-human to approval needs the early trial of an approved
drug, and those studies finished years ago and are gone from the active table. Only 65
of 1,262 approved assets still have an early-phase trial on file.

Market access. Coverage rates and prior-authorisation burden come from payer claims,
which is a paid dataset. There is no free route and nothing here estimates one.

Probability of technical success. A real PTRS follows a cohort of candidates forward
through the phases. This holds one cross-section, so the phase mix below describes the
pipeline's shape today and must not be read as a transition rate.
"""

from __future__ import annotations

import datetime as dt

import db
import fx
import runway

# How recent an approval has to be to count as renewing the portfolio. Five years is the
# window the industry uses for a launch cohort, and it is long enough that a drug has
# reached most of its markets and short enough to exclude the last cycle's winners.
FRESH_YEARS = 5

# The window for counting approvals and the research that ran alongside them. Both are
# taken over the same span so the ratio compares like with like, even though the spend
# in it did not buy the approvals in it: that mismatch is the reason the ratio is
# reported as context rather than as the headline.
WINDOW_YEARS = 5

LATE_PHASES = ("Phase 3", "Phase 2/3")

# How much of a company's product revenue has to map to a dated approval before the
# freshness share means anything. Below this the answer is dominated by whatever the
# extractor failed to identify, so it is refused and the reason is given instead. Half
# is the line: at that point the majority of the revenue behind the number is real.
MIN_REVENUE_COVERAGE = 0.5


def _usd(value, currency, rates) -> float | None:
    if value is None:
        return None
    if not currency or currency == "USD":
        return value
    return fx.to_usd(value, currency, rates)


def _fy_sum(conn, company_id: int, metric: str, since_year: int, rates) -> float | None:
    """A metric summed over the recent full years, in USD, or None when nothing is on
    file. Summed rather than averaged so a missing year understates rather than
    silently rescaling the total."""
    total = None
    for row in conn.execute(
        "SELECT value, unit, fiscal_year FROM financials"
        "  WHERE company_id = ? AND metric = ? AND period_type = 'FY'"
        "    AND fiscal_year >= ? AND value IS NOT NULL",
            (company_id, metric, since_year)):
        value = _usd(row["value"], row["unit"], rates)
        if value is not None:
            total = (total or 0) + value
    return total


def _latest_fy(conn, company_id: int, metric: str, rates) -> float | None:
    row = conn.execute(
        "SELECT value, unit FROM financials WHERE company_id = ? AND metric = ?"
        "  AND period_type = 'FY' AND value IS NOT NULL"
        "  ORDER BY fiscal_year DESC LIMIT 1", (company_id, metric)).fetchone()
    return _usd(row["value"], row["unit"], rates) if row else None


def portfolio_freshness(conn, company_id: int, rates, today=None) -> dict:
    """Share of product revenue earned by drugs approved in the last five years.

    Computed on the most recent year that has any, over the revenue belonging to drugs
    whose first approval date is known, and refused when too little of the total does.
    Coverage travels with the number so a reader can see how much of the company it
    actually describes.
    """
    today = today or dt.date.today()
    cutoff = today.replace(year=today.year - FRESH_YEARS).isoformat()
    year = conn.execute(
        "SELECT MAX(ar.fiscal_year) FROM asset_revenue ar JOIN assets a"
        "  ON a.id = ar.asset_id WHERE a.owner_company_id = ?", (company_id,)).fetchone()[0]
    if year is None:
        return {"fresh_share": None, "revenue": None, "dated_revenue": None,
                "coverage": 0.0, "year": None, "drugs": 0, "identified": 0,
                "reason": "no product revenue on file"}

    total = dated = fresh = 0.0
    drugs = identified = 0
    for row in conn.execute(
        """
        SELECT ar.value, ar.unit, ap.first_approval
          FROM asset_revenue ar
          JOIN assets a ON a.id = ar.asset_id
          LEFT JOIN (SELECT asset_id, MIN(approval_date) AS first_approval
                       FROM approvals GROUP BY asset_id) ap ON ap.asset_id = ar.asset_id
         WHERE a.owner_company_id = ? AND ar.fiscal_year = ? AND ar.value IS NOT NULL
        """, (company_id, year)):
        value = _usd(row["value"], row["unit"], rates)
        if value is None:
            continue
        drugs += 1
        total += value
        if row["first_approval"] is None:
            continue
        identified += 1
        dated += value
        if row["first_approval"] >= cutoff:
            fresh += value

    # The share is taken over revenue that belongs to an identified, dated drug, not
    # over the whole line. The revenue table holds what the filing disaggregates, and a
    # filing disaggregates more than products: Moderna's rows are "COVID 19", "Grant",
    # "License And Royalty" and "Collaboration Arrangement", none of which is a drug and
    # none of which can ever carry an approval date. Dividing by the full total counted
    # those as old product and reported Moderna, whose entire business post-dates 2021,
    # as earning nothing from recent approvals.
    coverage = (dated / total) if total else 0.0
    share = (fresh / dated) if dated else None
    return {"fresh_share": share if coverage >= MIN_REVENUE_COVERAGE else None,
            "revenue": total or None, "dated_revenue": dated or None,
            "coverage": coverage, "year": year,
            "drugs": drugs, "identified": identified,
            "reason": None if coverage >= MIN_REVENUE_COVERAGE else
                      f"only {coverage:.0%} of product revenue maps to a dated approval"}


def _company(conn, company, rates, today) -> dict:
    since = today.year - WINDOW_YEARS
    cutoff = today.replace(year=today.year - WINDOW_YEARS).isoformat()

    approvals = conn.execute(
        "SELECT COUNT(DISTINCT ap.asset_id) FROM approvals ap"
        "  JOIN assets a ON a.id = ap.asset_id"
        " WHERE a.owner_company_id = ? AND ap.approval_date >= ?",
        (company["id"], cutoff)).fetchone()[0]

    rd_window = _fy_sum(conn, company["id"], "ResearchAndDevelopmentExpense",
                        since, rates)
    rd_latest = _latest_fy(conn, company["id"], "ResearchAndDevelopmentExpense", rates)
    revenue_latest = _latest_fy(conn, company["id"], "Revenues", rates)

    phases = {r["phase"]: r["n"] for r in conn.execute(
        "SELECT phase, COUNT(*) n FROM trials WHERE sponsor_company_id = ?"
        "  AND phase IS NOT NULL GROUP BY phase", (company["id"],))}
    active = sum(phases.values())
    late = sum(n for p, n in phases.items() if p in LATE_PHASES)

    fresh = portfolio_freshness(conn, company["id"], rates, today)

    return {
        "ticker": company["ticker"], "name": company["name"],
        "rd_latest": rd_latest,
        "revenue_latest": revenue_latest,
        # What share of the top line goes back into research. The one input measure
        # every company reports on the same basis.
        "rd_intensity": (rd_latest / revenue_latest)
                        if rd_latest and revenue_latest else None,
        "rd_window": rd_window,
        "approvals_window": approvals,
        # The metric the industry quotes. Reported because it is the reference point,
        # not because it is the answer: the spend in the window did not buy the
        # approvals in the window, and a count says nothing about what they are worth.
        "rd_per_approval": (rd_window / approvals) if rd_window and approvals else None,
        "fresh_share": fresh["fresh_share"],
        "fresh_revenue_year": fresh["year"],
        "fresh_drugs": fresh["drugs"],
        "fresh_identified": fresh["identified"],
        "fresh_coverage": fresh["coverage"],
        "fresh_reason": fresh["reason"],
        "dated_revenue": fresh["dated_revenue"],
        "trials_active": active,
        "late_share": (late / active) if active else None,
    }


def build(db_path=None, today=None, stage_filter: str | None = runway.COMMERCIAL) -> list:
    """One row per commercial-stage company, ordered by portfolio freshness.

    Clinical-stage names are excluded by default: with no product revenue there is no
    freshness to measure and no approvals to divide by, and the runway view is where
    those companies are read.
    """
    today = today or dt.date.today()
    conn = db.get_connection(db_path)
    try:
        rates = fx.latest_usd_rates(db_path)
        rows = []
        for company in conn.execute(
                "SELECT id, ticker, name FROM companies ORDER BY ticker"):
            if stage_filter and runway.stage(conn, company["id"]) != stage_filter:
                continue
            rows.append(_company(conn, company, rates, today))
    finally:
        conn.close()
    return sorted(rows, key=lambda r: (r["fresh_share"] is None,
                                       -(r["fresh_share"] or 0)))
