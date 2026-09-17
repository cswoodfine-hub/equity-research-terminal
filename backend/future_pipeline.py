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
outside the window, and Novo reads $1.13 on the GLP-1s alone. So each filer's own rate
is blended with the pool at a weight the data sets (credibility, below): the more
launches its decade rests on, the more its own record counts.

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
# R&D a filer spends on businesses that are not medicines, by year, as its segment note
# reports it: Johnson & Johnson's MedTech develops devices, which earn no drug approval.
OUTSIDE_MEDICINES = DATA_DIR / "rd_outside_medicines.csv"
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


def outside_medicines(path=None) -> dict:
    """{ticker: {fiscal_year: (value, unit)}} of R&D spent outside medicines."""
    source = pathlib.Path(path) if path else OUTSIDE_MEDICINES
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            try:
                value = float(row["rd_musd"]) * 1e6
                year = int(row["fiscal_year"])
            except (TypeError, ValueError, KeyError):
                continue
            out.setdefault((row.get("ticker") or "").strip().upper(), {})[year] = (
                value, (row.get("unit") or "USD").strip() or "USD")
    return out


def filer_productivity(conn, company_id: int, rates, name_index, outside=None) -> dict:
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
    # Research, not asset purchases: where a filer expenses acquired in-process R&D inside
    # its R&D line, the year is read net of it (statements, ResearchLessExpensedIprd).
    # A year with no net figure on file reads the line as filed. Keyed on the period end,
    # not the label: Johnson & Johnson's 52-week years ending in early January carry the
    # next year's label, so one label can hold two real years and both belong in the sum.
    by_period: dict = {}
    for row in conn.execute(
            """SELECT period_end, fiscal_year, metric, value, unit FROM financials
                WHERE company_id = ?
                AND metric IN ('ResearchAndDevelopmentExpense', 'ResearchLessExpensedIprd')
                AND period_type = 'FY' AND fiscal_year BETWEEN ? AND ?
                AND value IS NOT NULL
                ORDER BY period_end, metric""",
            (company_id, year - COHORT_YEARS, year - 1)):
        by_period[row["period_end"]] = row    # the net figure sorts after the filed one
    rd, rd_years, rd_years_seen = 0.0, 0, []
    for row in by_period.values():
        value = productivity._usd(row["value"], row["unit"], rates)
        if value:
            rd += value
            rd_years += 1
            rd_years_seen.append(row["fiscal_year"])
    # R&D spent outside medicines buys no drug launches, so it is not in the denominator.
    # Taken out only where the filer reports it for every year of the window: a part of
    # the decade corrected and the rest not would be a rate on no consistent basis.
    ticker = conn.execute("SELECT ticker FROM companies WHERE id = ?",
                          (company_id,)).fetchone()
    reported = (outside_medicines() if outside is None else outside).get(
        (ticker["ticker"] if ticker else "").upper(), {})
    rd_outside, outside_basis = 0.0, None
    if reported:
        if rd_years_seen and all(y in reported for y in rd_years_seen):
            rd_outside = sum(productivity._usd(reported[y][0], reported[y][1], rates) or 0.0
                             for y in rd_years_seen)
            rd -= rd_outside
            outside_basis = (f"R&D outside medicines taken out for all {len(rd_years_seen)} "
                             "years of the window, as the segment note reports it")
        else:
            missing = sorted(y for y in rd_years_seen if y not in reported)
            outside_basis = ("R&D outside medicines is not reported for "
                             + ", ".join(str(y) for y in missing)
                             + ", so the window's R&D is read whole")
    coverage = dated / total if total else 0.0
    rate = fresh / rd if rd else None
    launches.sort(key=lambda r: -r["revenue"])
    return {"rate": rate, "year": year, "revenue": total, "dated_share": coverage,
            "fresh_revenue": fresh, "rd": rd, "rd_years": rd_years,
            "rd_outside_medicines": rd_outside, "rd_outside_basis": outside_basis,
            "launches": launches[:8], "launch_count": len(launches),
            "launch_revenues": [r["revenue"] for r in launches],
            "reason": None if rate is not None else "no R&D on file for the window"}


def credibility(filers: list) -> dict:
    """How far a filer's own rate can be trusted against the pool, from the data.

    Buhlmann-Straub credibility (Buhlmann and Straub, 1970), the method insurers use to
    weigh one risk's own experience against the book's. Each launch is an observation:
    scaled so that a filer's launches average to its own rate, their spread inside a
    filer is the noise in that rate (sigma2), and the spread of the rates across
    filers, less what that noise alone would produce, is how much filers really differ
    (tau2). A filer with n launches earns weight n / (n + sigma2 / tau2) on its own rate
    and the rest on the pool. A decade resting on one blockbuster earns little; one
    resting on sixteen launches earns most.

    ``filers`` are the pooled filers, each {rate, launch_revenues, rd}. Returns
    {k, sigma2, tau2, mean}; k is None where the filers do not differ by more than
    their noise, and every filer then takes the pool.
    """
    usable = [f for f in filers if f.get("launch_revenues")]
    total = sum(len(f["launch_revenues"]) for f in usable)
    if len(usable) < 2 or not total:
        return {"k": None, "sigma2": None, "tau2": None, "mean": None}
    mean = sum(len(f["launch_revenues"]) * f["rate"] for f in usable) / total
    within, dof = 0.0, 0
    for f in usable:
        n = len(f["launch_revenues"])
        if n < 2:
            continue
        xs = [n * r / f["rd"] for r in f["launch_revenues"]]
        within += sum((x - f["rate"]) ** 2 for x in xs)
        dof += n - 1
    if not dof:
        return {"k": None, "sigma2": None, "tau2": None, "mean": mean}
    sigma2 = within / dof
    between = sum(len(f["launch_revenues"]) * (f["rate"] - mean) ** 2 for f in usable)
    spread = total - sum(len(f["launch_revenues"]) ** 2 for f in usable) / total
    tau2 = (between - (len(usable) - 1) * sigma2) / spread if spread else 0.0
    return {"k": sigma2 / tau2 if tau2 > 0 else None, "sigma2": sigma2, "tau2": tau2,
            "mean": mean}


def blend(own: float | None, launches: int, pool_rate: float, k: float | None) -> tuple:
    """(rate, weight on own). The own rate at its credibility, the pool for the rest."""
    if own is None or k is None or launches <= 0:
        return pool_rate, 0.0
    weight = launches / (launches + k)
    return weight * own + (1.0 - weight) * pool_rate, weight


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
                           "revenue": got["revenue"], "rd": got["rd"],
                           "launch_count": got["launch_count"],
                           "launch_revenues": got["launch_revenues"]})
            if counted:
                fresh += got["fresh_revenue"]
                rd += got["rd"]
    finally:
        conn.close()
    rate = fresh / rd if rd else None
    weights = credibility([f for f in filers if f["counted"]])
    for f in filers:
        f["blended"], f["credibility"] = (blend(f["rate"], f["launch_count"], rate,
                                                weights["k"])
                                          if rate is not None else (None, 0.0))
    out = {"rate": rate, "filers": filers, "credibility": weights,
           "n": sum(1 for f in filers if f["counted"])}
    _CACHE[key] = (time.time(), out)
    return out


def renewal(rate: float, rd_ratio: float, life: int, erosion_year1: float,
            erosion_decay: float) -> float:
    """What one generation of launches buys of the next, per dollar of its revenue.

    A dollar of launch revenue a year funds rd_ratio of R&D a year, which buys rate of
    revenue a year for ``life`` years and then an eroding tail worth (1 - year-one drop)
    / decay years more. Above one the franchise compounds, below one it runs down."""
    tail = (1.0 - erosion_year1) / erosion_decay if erosion_decay > 0 else 0.0
    return rate * rd_ratio * (life + tail)


def simulate(book_rd: dict, rate: float, lag: int, life: int, erosion_year1: float,
             erosion_decay: float, ratios: dict, discount: float, base_year: int,
             horizon: int, long_run_growth: float | None = None) -> dict:
    """The launches bought by the book's R&D and by the launches' own R&D, valued.

    ``book_rd`` is {year: R&D the modelled book charges that year}. A cohort bought in
    year s earns ``rate`` times that spend from s + lag for ``life`` years, then drops
    by ``erosion_year1`` and decays by ``erosion_decay``. Its revenue is costed on
    ``ratios`` (cogs, sga, rd, other, tax, each a share of revenue), and its R&D buys
    the next cohort. Cash flows are discounted mid-year from the end of ``base_year``,
    the same convention as the engine. Pure.

    ``long_run_growth`` caps the renewal. Where one generation would buy more than the
    growth allows over a generation's length, only the share of its R&D that holds the
    franchise to that growth is credited with launches; the rest is still charged. The
    book's own products fade to their long-run rate, and a franchise compounding past
    it is a claim the book does not make: Vertex, spending 32% of revenue on R&D at a
    0.51 rate, compounded 6.6% a year for sixty years and put most of its value after
    2055. None means uncapped.
    """
    years = list(range(base_year + 1, base_year + 1 + horizon))
    spend = {y: book_rd.get(y, 0.0) for y in years}
    generation = renewal(rate, ratios["rd"], life, erosion_year1, erosion_decay)
    credited = 1.0
    if long_run_growth is not None and generation > 0:
        allowed = (1.0 + long_run_growth) ** (lag + life / 2.0)
        credited = min(1.0, allowed / generation)
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
            spend[y] += earned * ratios["rd"] * credited
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
            "renewal": generation, "credited_share": credited,
            # R&D the launches go on to fund across the horizon, against the R&D the
            # book funds. Undiscounted, so it describes scale rather than value.
            "replacement": (sum(spend.values()) - book_total) / book_total
            if book_total else None}
