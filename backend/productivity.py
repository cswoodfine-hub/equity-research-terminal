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

It is reported for thirteen of the large names and refused for the rest, with the reason
given. Dating a drug is harder than it sounds and is done in approval_dates: an alliance
product is approved to the partner rather than the company booking the revenue, a
biologic is not in drugsfda at all, and a filing often names a franchise or two brands
at once. Royalties, grants and collaboration income leave the base entirely, because
they are revenue and are not product revenue.

What remains is the revenue table's own coverage. Ten large companies disaggregate no
product revenue in the SEC data sets, AbbVie among them, and no rule here can date a
drug whose revenue was never extracted. Those read as "no product revenue on file"
rather than as an aged portfolio.

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

import approval_dates
import db
import franchises
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


def portfolio_verdict(conn, company_id: int, cutoff: str) -> tuple:
    """(all_recent, all_old, brands) for everything the company markets.

    A filing that discloses "Shingles" or "COVID 19" names a franchise rather than a
    drug, and no free source maps a disease to a product: openFDA's label endpoint
    returns 404 for every vaccine, so there is no indication text to match against.

    There is still an answer available for some of them, and it needs no mapping. If
    every product a company markets was first marketed inside the freshness window then
    all of its product revenue is fresh, whatever the rows are labelled, because there is
    nothing older for the revenue to have come from. Moderna markets Spikevax, mNEXSPIKE
    and mRESVIA and nothing else, all after 2024, so its "COVID 19" line is fresh however
    it is worded. The same reasoning runs the other way for a company whose whole
    register predates the window.

    A company whose products straddle the cutoff gets no verdict, which is the honest
    answer: GSK markets vaccines first sold between 2016 and 2026, and its "Meningitis"
    line could be either.
    """
    dates = [r[0] for r in conn.execute(
        "SELECT first_marketed FROM ndc_products"
        "  WHERE company_id = ? AND first_marketed IS NOT NULL", (company_id,))]
    if not dates:
        return False, False, 0
    return (all(d >= cutoff for d in dates), all(d < cutoff for d in dates), len(dates))


def portfolio_freshness(conn, company_id: int, rates, today=None,
                        name_index: dict | None = None) -> dict:
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
                "non_product_revenue": None, "inferred_revenue": None,
                "curated_revenue": None,
                "reason": "no product revenue on file"}

    if name_index is None:
        name_index = approval_dates.build_name_index(conn)

    all_recent, all_old, _brands = portfolio_verdict(conn, company_id, cutoff)
    ticker = (conn.execute("SELECT ticker FROM companies WHERE id = ?",
                           (company_id,)).fetchone() or [""])[0]
    franchise_map = franchises.load()
    total = dated = fresh = non_product = inferred = curated = 0.0
    drugs = identified = 0
    for row in conn.execute(
        """
        SELECT ar.asset_id, ar.value, ar.unit,
               COALESCE(a.brand_name, a.generic_name) AS name
          FROM asset_revenue ar
          JOIN assets a ON a.id = ar.asset_id
         WHERE a.owner_company_id = ? AND ar.fiscal_year = ? AND ar.value IS NOT NULL
        """, (company_id, year)):
        value = _usd(row["value"], row["unit"], rates)
        if value is None:
            continue
        # Royalties, collaboration income and milestone payments are revenue and are
        # not product revenue, so they leave the base entirely rather than sitting in
        # it as undatable drugs. A franchise label like "Shingles" stays: that is a
        # real product whose name the filing did not give, and removing it would
        # flatter the coverage figure instead of reporting the gap.
        if not approval_dates.is_product_line(row["name"]):
            non_product += value
            continue
        drugs += 1
        total += value
        approved, _route = approval_dates.first_approval(
            conn, row["asset_id"], row["name"], name_index)
        if approved is None:
            # A franchise label names a disease rather than a drug. The curated map says
            # which products the franchise covers, and the dates still come from the
            # register, so a line resolves only when every member of it sits on the same
            # side of the cutoff. GSK's meningitis revenue comes from products first
            # marketed in 2016, 2017 and 2025 and stays unresolved.
            franchise_date, _why = franchises.resolve(
                conn, ticker, row["name"], cutoff, franchise_map)
            if franchise_date:
                identified += 1
                dated += value
                if franchise_date >= cutoff:
                    fresh += value
                curated += value
                continue
            # Where every product the company markets falls on the same side of the
            # cutoff, the revenue does too and the label does not need resolving.
            if all_recent or all_old:
                identified += 1
                dated += value
                if all_recent:
                    fresh += value
                inferred += value
            continue
        identified += 1
        dated += value
        if approved >= cutoff:
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
            "non_product_revenue": non_product or None,
            # Revenue placed by the whole-register test rather than by dating its drug,
            # kept visible because it is a weaker claim than the rest.
            "inferred_revenue": inferred or None,
            # Revenue placed through the curated franchise map. Its membership is
            # curated and its dates are not, but a reader should still see how much of
            # the figure rests on a hand-maintained mapping.
            "curated_revenue": curated or None,
            "reason": None if coverage >= MIN_REVENUE_COVERAGE else
                      f"only {coverage:.0%} of product revenue maps to a dated approval"}


def _company(conn, company, rates, today, name_index=None) -> dict:
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

    fresh = portfolio_freshness(conn, company["id"], rates, today, name_index)

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
        # Royalties, grants and collaboration income, kept visible rather than silently
        # dropped: a reader should be able to see how much of the top line was set
        # aside before the share was taken.
        "non_product_revenue": fresh["non_product_revenue"],
        "inferred_revenue": fresh["inferred_revenue"],
        "curated_revenue": fresh["curated_revenue"],
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
        # Built once for the whole pass rather than per company.
        name_index = approval_dates.build_name_index(conn)
        rows = []
        for company in conn.execute(
                "SELECT id, ticker, name FROM companies ORDER BY ticker"):
            if stage_filter and runway.stage(conn, company["id"]) != stage_filter:
                continue
            rows.append(_company(conn, company, rates, today, name_index))
    finally:
        conn.close()
    return sorted(rows, key=lambda r: (r["fresh_share"] is None,
                                       -(r["fresh_share"] or 0)))


# --- the two composite scores ---------------------------------------------------------

# What goes into each axis, and with what weight. Stated as data rather than buried in
# the arithmetic, because a composite is only as honest as its recipe: a reader has to
# be able to see what was combined and disagree with it.
#
# Freshness sits on the research axis rather than the commercial one. It is measured in
# revenue, but what it measures is whether research output reached the market and is
# earning, which is the productivity question. Growth and margin are what the commercial
# organisation did with whatever it was given.
RD_INPUTS = (
    ("fresh_share", 0.5, "share of product revenue from drugs approved in five years"),
    ("approvals_window", 0.3, "approvals in five years"),
    ("late_share", 0.2, "share of the active pipeline in Phase 3"),
)
COMMERCIAL_INPUTS = (
    ("revenue_growth", 0.6, "revenue growth on the prior year"),
    ("net_margin", 0.4, "net margin"),
)

# A z-score past this is clipped. One company three standard deviations out otherwise
# compresses everyone else into a smudge, and the point of the chart is the spread among
# the rest, not the exact distance to the outlier.
Z_CLIP = 3.0

# The revenue a company needs before it belongs on a chart of large-cap productivity.
# Not a view about small companies, a statement about what a composite can compare: a
# 40m-revenue biotech posting 2,900% growth and a 65bn one posting 45% are not on the
# same scale, and standardising them together put Abeona and Autolus above Lilly. Until
# freshness became computable for the small names the missing data was filtering them out
# by accident, which is not a filter.
SCORECARD_MIN_REVENUE = 1e9


def _z_scores(values: dict) -> dict:
    """{key: z} for the values present, or all zeros when they do not vary."""
    present = [v for v in values.values() if v is not None]
    if len(present) < 2:
        return {k: 0.0 for k in values}
    mean = sum(present) / len(present)
    variance = sum((v - mean) ** 2 for v in present) / len(present)
    sd = variance ** 0.5
    # Against a relative tolerance, not against exact zero. Nine values of 0.2 sum to
    # 1.8000000000000003, so the mean is a hair off every one of them and the deviation
    # is around 1e-17 rather than 0. Dividing that by an equally tiny standard deviation
    # produced z-scores near one, which ranked a group of identical companies.
    if sd <= max(abs(mean), 1.0) * 1e-9:
        return {k: 0.0 if v is not None else None for k, v in values.items()}
    return {k: max(-Z_CLIP, min(Z_CLIP, (v - mean) / sd)) if v is not None else None
            for k, v in values.items()}


def scorecard(db_path=None, today=None, rows=None, comps_rows=None,
              min_revenue: float = SCORECARD_MIN_REVENUE) -> list:
    """Each company placed on a research axis and a commercial one.

    Both are z-scores against the measured group, weighted and summed, so zero is the
    group average on that axis rather than any absolute standard. That is what makes the
    quadrants readable and also what limits them: this says who is ahead of these peers
    this year, not whether any of them is good.

    Only companies with every input are placed. A composite built over whatever happened
    to be present would rank a company on two measures against another ranked on five,
    and the missing ones are listed separately rather than plotted at a default.
    """
    import comps as comps_module

    rows = rows if rows is not None else build(db_path, today=today)
    comps_rows = (comps_rows if comps_rows is not None
                  else comps_module.build_comps(db_path))
    commercial_by_ticker = {c["ticker"]: c for c in comps_rows}

    merged = []
    for row in rows:
        if min_revenue and (row.get("revenue_latest") or 0) < min_revenue:
            continue
        extra = commercial_by_ticker.get(row["ticker"]) or {}
        merged.append({**row,
                       "revenue_growth": extra.get("revenue_growth"),
                       "net_margin": extra.get("net_margin")})

    fields = [f for f, _w, _l in RD_INPUTS + COMMERCIAL_INPUTS]

    # Scored against the companies that will actually be plotted, not against every
    # company the build returned. Standardising over the wider set let a micro-cap
    # posting 2,900% revenue growth set the scale, which pushed Lilly's 45% to the
    # group mean and collapsed the plotted names into a smudge around the origin. Zero
    # on this chart means the average of the peers on it.
    eligible = [r for r in merged
                if all(r.get(f) is not None for f in fields)]
    z = {field: _z_scores({r["ticker"]: r.get(field) for r in eligible})
         for field in fields}

    placed, missing = [], []
    for row in merged:
        gaps = [label for field, _w, label in RD_INPUTS + COMMERCIAL_INPUTS
                if row.get(field) is None]
        if gaps:
            missing.append({"ticker": row["ticker"], "name": row["name"],
                            "missing": gaps})
            continue
        rd = sum(weight * z[field][row["ticker"]] for field, weight, _l in RD_INPUTS)
        commercial = sum(weight * z[field][row["ticker"]]
                         for field, weight, _l in COMMERCIAL_INPUTS)
        placed.append({
            "ticker": row["ticker"], "name": row["name"],
            "rd_score": rd, "commercial_score": commercial,
            # The quadrant, named the way the chart reads it.
            "quadrant": ("Both" if rd >= 0 and commercial >= 0 else
                         "R&D" if rd >= 0 else
                         "Commercial" if commercial >= 0 else "Neither"),
            "fresh_share": row["fresh_share"],
            "approvals_window": row["approvals_window"],
            "late_share": row["late_share"],
            "revenue_growth": row["revenue_growth"],
            "net_margin": row["net_margin"],
        })
    return sorted(placed, key=lambda r: -(r["rd_score"] + r["commercial_score"]))


def scorecard_gaps(db_path=None, today=None,
                   min_revenue: float = SCORECARD_MIN_REVENUE) -> list:
    """The companies a composite cannot place, and what each is missing."""
    import comps as comps_module

    rows = build(db_path, today=today)
    commercial = {c["ticker"]: c for c in comps_module.build_comps(db_path)}
    gaps = []
    for row in rows:
        if min_revenue and (row.get("revenue_latest") or 0) < min_revenue:
            continue
        extra = commercial.get(row["ticker"]) or {}
        merged = {**row, "revenue_growth": extra.get("revenue_growth"),
                  "net_margin": extra.get("net_margin")}
        missing = [label for field, _w, label in RD_INPUTS + COMMERCIAL_INPUTS
                   if merged.get(field) is None]
        if missing:
            gaps.append({"ticker": row["ticker"], "name": row["name"],
                         "missing": missing})
    return gaps
