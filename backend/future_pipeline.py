"""The launches the modelled book's R&D will buy, valued from what R&D has bought.

A company valued as the sum of today's products is a run-off. Each product fades and
erodes at its loss of exclusivity, while every one of them is charged the company's
R&D ratio for as long as it sells. That charge pays for the next generation of drugs,
and without a line for them the model counts the cost and none of the return: Amgen's
products carry $147 a share of R&D against no future launches at all.

This is that line, and it is built from observation rather than from a view.

Productivity is the revenue a company earns in its latest year from drugs first approved
in the last ten, per dollar of R&D it spent over the ten years before. It is measured per
filer and pooled across the large ones, because one filer's decade is dominated by one
or two launches: Merck reads 4.5 cents because Keytruda's 2014 approval falls a year
outside the window, and Novo reads $1.13 on the GLP-1s alone. The pooled rate is what
the line uses; each filer's own rate is reported beside it.

Each year's R&D in the model buys a cohort of launches that arrives after the lag, earns
the productivity rate on that spend for the exclusivity term, and then erodes on the
curated default. The cohort is costed on the company's own ratios, R&D included, and
that R&D buys the next cohort in turn, so replacement is simulated rather than assumed.
Nothing is risk-adjusted a second time: the rate is measured on what reached market, so
the failures are already in it.

Two biases are stated rather than corrected. The ratio's R&D window sits one year before
the launches rather than a full lag before, and R&D has grown, so the denominator is
larger than the spend that bought the launches and the rate reads low. And launches a
filer bought rather than discovered are in the numerator while the acquisition spend is
not in the denominator, which reads high.
"""

from __future__ import annotations

import csv
import pathlib
import time

import approval_dates
import db
import fx
import productivity

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
DEFAULTS = DATA_DIR / "future_pipeline_defaults.csv"
COHORT_YEARS = 10
_CACHE: dict = {}
_CACHE_SECONDS = 3600


def defaults(path=None) -> dict:
    """{key: {value, source}} from the defaults file."""
    source = pathlib.Path(path) if path else DEFAULTS
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    return {r["key"]: {"value": float(r["value"]), "source": r["source"]}
            for r in csv.DictReader(rows)}


def filer_productivity(conn, company_id: int, rates, name_index) -> dict:
    """One filer's launch productivity, and what it was built from.

    Revenue is the latest full year's, over product lines only, in dollars; a line is
    fresh when its drug's first approval falls in the ten years ending that year. R&D is
    the ten full years before it. Both are converted at the same latest rates, so the
    ratio carries no currency.
    """
    year = conn.execute(
        "SELECT MAX(ar.fiscal_year) FROM asset_revenue ar JOIN assets a"
        "  ON a.id = ar.asset_id WHERE a.owner_company_id = ? AND ar.period = 'FY'",
        (company_id,)).fetchone()[0]
    if year is None:
        return {"rate": None, "reason": "no product revenue on file"}
    cutoff = f"{year - COHORT_YEARS + 1}-01-01"
    total = dated = fresh = 0.0
    launches = []
    for row in conn.execute(
            """SELECT ar.asset_id, ar.value, ar.unit,
                      COALESCE(a.brand_name, a.generic_name) AS name
                 FROM asset_revenue ar JOIN assets a ON a.id = ar.asset_id
                WHERE a.owner_company_id = ? AND ar.fiscal_year = ? AND ar.period = 'FY'
                  AND ar.value IS NOT NULL""", (company_id, year)):
        value = productivity._usd(row["value"], row["unit"], rates)
        if value is None or not approval_dates.is_product_line(row["name"]):
            continue
        total += value
        approved, _route = approval_dates.first_approval(
            conn, row["asset_id"], row["name"], name_index)
        if approved is None:
            continue
        dated += value
        if approved >= cutoff:
            fresh += value
            launches.append({"name": row["name"], "approved": approved[:10],
                             "revenue": value})
    rd, rd_years = 0.0, 0
    for row in conn.execute(
            """SELECT value, unit FROM financials WHERE company_id = ?
                AND metric = 'ResearchAndDevelopmentExpense' AND period_type = 'FY'
                AND fiscal_year BETWEEN ? AND ? AND value IS NOT NULL""",
            (company_id, year - COHORT_YEARS, year - 1)):
        value = productivity._usd(row["value"], row["unit"], rates)
        if value:
            rd += value
            rd_years += 1
    coverage = dated / total if total else 0.0
    rate = fresh / rd if rd else None
    launches.sort(key=lambda r: -r["revenue"])
    return {"rate": rate, "year": year, "revenue": total, "dated_share": coverage,
            "fresh_revenue": fresh, "rd": rd, "rd_years": rd_years,
            "launches": launches[:8],
            "reason": None if rate is not None else "no R&D on file for the window"}


def pooled(db_path=None, refresh: bool = False) -> dict:
    """The universe rate: fresh revenue over R&D, summed across the large filers whose
    R&D window and dated revenue are complete enough to count. Cached for an hour,
    since it walks every revenue line in the database."""
    key = str(db_path)
    hit = _CACHE.get(key)
    if hit and not refresh and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    bounds = defaults()
    min_years = int(bounds["min_rd_years"]["value"])
    min_revenue = bounds["min_revenue_musd"]["value"] * 1e6
    conn = db.get_connection(db_path)
    try:
        rates = fx.latest_usd_rates(db_path)
        index = approval_dates.build_name_index(conn)
        filers, fresh, rd = [], 0.0, 0.0
        for company in conn.execute("SELECT id, ticker FROM companies ORDER BY ticker"):
            got = filer_productivity(conn, company["id"], rates, index)
            if got.get("rate") is None:
                continue
            counted = (got["rd_years"] >= min_years and got["revenue"] >= min_revenue
                       and got["dated_share"] >= productivity.MIN_REVENUE_COVERAGE)
            filers.append({"ticker": company["ticker"], "rate": got["rate"],
                           "counted": counted, "rd_years": got["rd_years"],
                           "revenue": got["revenue"]})
            if counted:
                fresh += got["fresh_revenue"]
                rd += got["rd"]
    finally:
        conn.close()
    out = {"rate": fresh / rd if rd else None,
           "filers": filers, "n": sum(1 for f in filers if f["counted"])}
    _CACHE[key] = (time.time(), out)
    return out


def simulate(book_rd: dict, rate: float, lag: int, life: int, erosion_year1: float,
             erosion_decay: float, ratios: dict, discount: float, base_year: int,
             horizon: int) -> dict:
    """The launches bought by the book's R&D and by the launches' own R&D, valued.

    ``book_rd`` is {year: R&D the modelled book charges that year}. A cohort bought in
    year s earns ``rate`` times that spend from s + lag for ``life`` years, then drops
    by ``erosion_year1`` and decays by ``erosion_decay``. Its revenue is costed on
    ``ratios`` (cogs, sga, rd, other, tax, each a share of revenue), and its R&D buys
    the next cohort. Cash flows are discounted mid-year from the end of ``base_year``,
    the same convention as the engine. Pure.
    """
    years = list(range(base_year + 1, base_year + 1 + horizon))
    spend = {y: book_rd.get(y, 0.0) for y in years}
    revenue = {y: 0.0 for y in years}
    cohorts = 0
    for s in years:                        # a year's spend is final once reached
        if spend[s] <= 0:
            continue
        launch = s + lag
        if launch > years[-1]:
            continue
        cohorts += 1
        level = rate * spend[s]
        for i, y in enumerate(range(launch, years[-1] + 1)):
            if i < life:
                earned = level
            else:
                earned = level * (1.0 - erosion_year1) * (1.0 - erosion_decay) ** (i - life)
            revenue[y] += earned
            spend[y] += earned * ratios["rd"]
    margin = 1.0 - ratios["cogs"] - ratios["sga"] - ratios["rd"] - ratios["other"]
    pv, flows = 0.0, []
    for y in years:
        ebit = revenue[y] * margin
        fcff = ebit - max(0.0, ebit * ratios["tax"])
        pv += fcff / (1.0 + discount) ** ((y - base_year) - 0.5)
        flows.append({"year": y, "revenue": revenue[y], "fcff": fcff})
    first = next((f["year"] for f in flows if f["revenue"] > 0), None)
    book_total = sum(book_rd.values())
    return {"value": pv, "flows": flows, "first_launch_year": first, "cohorts": cohorts,
            # R&D the launches go on to fund across the horizon, against the R&D the
            # book funds. Undiscounted, so it describes scale rather than value.
            "replacement": (sum(spend.values()) - book_total) / book_total
            if book_total else None}
