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
or two launches: Novo reads about a dollar on the GLP-1s alone, and Merck's own rate moves
from 2.6 cents to 32 on whether Keytruda's September 2014 approval falls inside the window
or a year outside it. So each filer's own rate
is blended with the pool at a weight the data sets (credibility, below): the more
launches its decade rests on, the more its own record counts.

Each year's R&D in the model buys a cohort of launches that arrives after the lag, earns
the productivity rate on that spend for the exclusivity term, and then erodes on the
curated default. The cohort is costed on the company's own ratios, R&D included, and
that R&D buys the next cohort in turn, so replacement is simulated rather than assumed.
Nothing is risk-adjusted a second time: the rate is measured on what reached market, so
the failures are already in it.

One bias is stated rather than corrected, and it cannot be corrected on free data. The
R&D window sits alongside the launches rather than a full lag before them, and R&D has
grown, so the denominator is larger than the spend that actually bought the launches and
the rate reads low. Shifting it back by the eight-year lag would need R&D from 2006, and
not one of the eighteen filers has it: XBRL starts in 2009 for the Americans, 2015 for
AstraZeneca, Novartis and Novo, and 2016 for GSK and Sanofi. With R&D flat the plain ratio
recovers the rate exactly whatever the window, because the cohorts arriving and leaving
balance, so the bias is the growth in R&D and nothing else.
  How far it can reach is measurable, and ``funded_share`` is the diagnostic. Only 12% of
Keytruda's development sits inside Merck's window, yet its revenue is three quarters of
Merck's fresh total, so Merck's own rate of 0.32 is largely paid for by research the
denominator never saw. The credibility blend is what stands between that and the
valuation, and with fourteen launches Merck earns most of its own weight, so it barely
moderates it: 0.319 own, 0.306 blended.

The bias that ran the other way is corrected. A launch that came with a company the filer
bought was paid for by the purchase price, which is not in the R&D the rate divides by,
so counting its revenue read as research that never happened: Amgen's Otezla came with
Celgene's divestiture, Gilead's Yescarta with Kite, Bristol's Reblozyl with Celgene. Those
launches are named in ``data/acquired_launches.csv`` and left out of the numerator, which
leaves deals where the other-costs charge leaves them (``one_off_cash``): capital
allocation, neither charged nor credited. A molecule licensed in is not bought, because
the development that followed ran through the filer's own R&D line.

The window is the exclusivity term the simulation grants a cohort, not a round number,
so a launch still earning in the model is still counted in the measurement that calibrates
it. The edge is left where it falls. Darzalex, approved on 16 November 2015, misses
Johnson & Johnson's FY2025 window by 46 days and takes $14.4bn of revenue out of its
record, as Keytruda's 2014 approval does for Merck. Moving the edge for one drug would
be choosing the answer; any window drops a launch just outside it, and one just inside
counts in full. The credibility weight is what absorbs it: a record resting on few
launches leans on the pool.
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
# R&D a filer reports for its medicines segment alone, by fiscal year. Johnson & Johnson's
# company R&D also carries MedTech, and until the Kenvue separation consumer health, and
# neither develops drugs that earn an approval.
MEDICINES_RD = DATA_DIR / "rd_medicines_segment.csv"
# New forms of a molecule already sold, which its own patients switch to: EYLEA HD from
# EYLEA, Keytruda Qlex from Keytruda. Dated from the form they replace, not their own
# approval, since their revenue is largely the older form's moving across.
SWITCH_FORMS = DATA_DIR / "switch_forms.csv"
# Launches a collaborator paid to develop, where the filer books that funding as a cut to
# its own R&D line: the revenue is the filer's, the cost is not in its R&D.
PARTNER_FUNDED = DATA_DIR / "partner_funded_launches.csv"
# Launches that came with a company the filer bought. The purchase price is what bought
# them, and it is nowhere in the R&D the rate divides by.
ACQUIRED = DATA_DIR / "acquired_launches.csv"
# How many years of launches the rate is measured over. It is the exclusivity term the
# simulation grants a cohort, not a round number: ``simulate`` has each year's spend earn
# for ``loe_defaults[...]["years_from_launch"]`` years, so a launch eleven years old is
# still earning in the model and its revenue belongs in the measurement that calibrates
# it. At ten the two disagreed, and the disagreement was worth more than any assumption in
# the line: Merck's own rate reads 0.026 over ten years and 0.319 over twelve, because
# Keytruda was approved in September 2014 and a ten-year window from a 2025 anchor starts
# in 2016.
def _cohort_years(default: int = 12) -> int:
    try:
        import assumptions
        found = (assumptions.loe_defaults() or {}).get("unknown", {})
        years = int(found.get("years_from_launch") or default)
        return years if years > 0 else default
    except Exception:
        return default


COHORT_YEARS = _cohort_years()
_CACHE: dict = {}
_CACHE_SECONDS = 3600


def defaults(path=None) -> dict:
    """{key: {value, source}} from the defaults file."""
    source = pathlib.Path(path) if path else DEFAULTS
    with source.open(newline="", encoding="utf-8") as handle:
        rows = [line for line in handle if not line.lstrip().startswith("#")]
    return {r["key"]: {"value": float(r["value"]), "source": r["source"]}
            for r in csv.DictReader(rows)}


def medicines_rd(path=None) -> dict:
    """{ticker: {fiscal_year: (value, unit)}} of R&D reported for the medicines segment."""
    source = pathlib.Path(path) if path else MEDICINES_RD
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


def rd_history(conn, company_id: int, first: int, last: int, segment=None) -> dict:
    """{fiscal_year: R&D in millions of the reporting currency} for ``first`` to ``last``,
    read the way the productivity window reads it: net of expensed acquired IPR&D where
    that figure is on file, the medicines segment's where the filer reports it for the
    year, and keyed on the period end so a 52-week year lands in the year it covers. A
    year not on file is absent, never a zero."""
    ticker_row = conn.execute("SELECT ticker FROM companies WHERE id = ?",
                              (company_id,)).fetchone()
    ticker = (ticker_row["ticker"] if ticker_row else "").upper()
    reported = (medicines_rd() if segment is None else segment).get(ticker, {})
    by_period: dict = {}
    for row in conn.execute(
            """SELECT period_end, metric, value FROM financials
                WHERE company_id = ?
                AND metric IN ('ResearchAndDevelopmentExpense', 'ResearchLessExpensedIprd')
                AND period_type = 'FY' AND fiscal_year BETWEEN ? AND ?
                AND value IS NOT NULL
                ORDER BY period_end, metric""", (company_id, first - 1, last + 1)):
        by_period[row["period_end"]] = row    # the net figure sorts after the filed one
    out: dict = {}
    for period_end in sorted(by_period):
        year = _fiscal_year_of(period_end)
        if first <= year <= last:
            out[year] = by_period[period_end]["value"] / 1e6
    for year, (value, _unit) in reported.items():
        if year in out:
            out[year] = value / 1e6
    return out


def switch_forms(path=None) -> dict:
    """{(ticker, product): parent product} for new forms of a molecule already sold."""
    source = pathlib.Path(path) if path else SWITCH_FORMS
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            ticker = (row.get("ticker") or "").strip().upper()
            product, parent = (row.get("product") or "").strip(), (row.get("parent") or "").strip()
            if ticker and product and parent:
                out[(ticker, product.lower())] = parent
    return out


def partner_funded(path=None) -> dict:
    """{(ticker, product): partner} for launches a collaborator funded outside the
    filer's R&D line."""
    source = pathlib.Path(path) if path else PARTNER_FUNDED
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            ticker = (row.get("ticker") or "").strip().upper()
            product, partner = (row.get("product") or "").strip(), (row.get("partner") or "").strip()
            if ticker and product and partner:
                out[(ticker, product.lower())] = partner
    return out


def acquired_launches(path=None) -> dict:
    """{(ticker, product): the company it came with} for launches a filer bought."""
    source = pathlib.Path(path) if path else ACQUIRED
    out: dict = {}
    if not source.exists():
        return out
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(line for line in handle if not line.lstrip().startswith("#")):
            ticker = (row.get("ticker") or "").strip().upper()
            product = (row.get("product") or "").strip()
            came_with = (row.get("acquired_from") or "").strip()
            if ticker and product and came_with:
                out[(ticker, product.lower())] = came_with
    return out


def _fiscal_year_of(period_end: str) -> int:
    """The year a period mostly falls in: Johnson & Johnson's 52-week year ending on 3
    January 2016 is its 2015, whatever label the filing gave it. Any other end is its own
    year."""
    year, month = int(period_end[:4]), int(period_end[5:7])
    return year - 1 if month == 1 else year


def _lag_years(default: int = 8) -> int:
    """Years from the spend to the launch it buys, from the defaults file."""
    try:
        found = defaults().get("lag_years") or {}
        return int(float(found.get("value") or default)) or default
    except Exception:
        return default


def funded_share(approved: str, rd_first_year: int, rd_last_year: int, lag: int) -> float:
    """How much of a launch's development the R&D window actually paid for, from nil to
    one.

    A drug approved in year a was developed over roughly the ``lag`` years before it, so
    the spend that bought it runs from a - lag to a. Only the part of that overlapping the
    denominator's own years was counted in the denominator, and only that part of the
    launch's revenue belongs in the numerator. The module already applies this rule
    discretely to launches an acquisition or a partner paid for; this applies it by degree
    to launches the window paid for in part.

    NOT APPLIED to the rate, and the reason is worth keeping. Weighting the numerator this
    way and leaving the denominator whole biases the rate down: the window's R&D also
    bought launches that have not arrived yet, so taking revenue out for spend that
    happened earlier while leaving in spend whose output is still to come charges the same
    lag twice. With R&D flat the plain ratio recovers the rate exactly at any window up to
    the earning life, because the cohorts arriving and the cohorts leaving balance. The
    lag only bites where R&D is growing, which is the bias the module docstring states.
    This stays as a diagnostic: it is how to see that Merck's rate rests on a drug the
    window did not pay for.
    """
    if not approved or lag <= 0:
        return 1.0
    try:
        year = int(str(approved)[:4])
    except ValueError:
        return 1.0
    start, end = year - lag, year
    overlap = min(end, rd_last_year + 1) - max(start, rd_first_year)
    return max(0.0, min(1.0, overlap / float(lag)))


def filer_productivity(conn, company_id: int, rates, name_index, segment=None,
                        switches=None, funded=None, bought=None) -> dict:
    """One filer's launch productivity, and what it was built from.

    Revenue is the latest full year's, over product lines only, in dollars; a line is
    fresh when its drug's first approval falls in the ten years ending that year. A new
    form of a molecule already sold (``data/switch_forms.csv``) is dated from the form it
    replaces, so a franchise moving to its new form is not counted as a launch. A launch a
    collaborator paid to develop outside the filer's R&D line
    (``data/partner_funded_launches.csv``), or one that came with a company the filer
    bought (``data/acquired_launches.csv``), is not counted either: neither was paid for
    by the R&D in the denominator. R&D is
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
    launches, switched, partnered, purchased = [], [], [], []
    ticker_row = conn.execute("SELECT ticker FROM companies WHERE id = ?",
                              (company_id,)).fetchone()
    ticker = (ticker_row["ticker"] if ticker_row else "").upper()
    forms = switch_forms() if switches is None else switches
    partners = partner_funded() if funded is None else funded
    acquired = acquired_launches() if bought is None else bought
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
        parent = forms.get((ticker, (row["name"] or "").lower()))
        if parent:
            found = conn.execute(
                """SELECT id FROM assets WHERE owner_company_id = ?
                    AND LOWER(COALESCE(brand_name, generic_name)) = LOWER(?) LIMIT 1""",
                (company_id, parent)).fetchone()
            older, _ = (approval_dates.first_approval(conn, found["id"], parent, name_index)
                        if found else (None, None))
            if older and (approved is None or older < approved):
                switched.append({"name": row["name"], "approved": (approved or "")[:10],
                                 "dated_from": parent, "parent_approved": older[:10]})
                approved = older
        if approved is None:
            continue
        dated += value
        partner = partners.get((ticker, (row["name"] or "").lower()))
        came_with = acquired.get((ticker, (row["name"] or "").lower()))
        if approved >= cutoff and came_with:
            purchased.append({"name": row["name"], "approved": approved[:10],
                              "revenue": value, "acquired_from": came_with})
        elif approved >= cutoff and partner:
            partnered.append({"name": row["name"], "approved": approved[:10],
                              "revenue": value, "partner": partner})
        elif approved >= cutoff:
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
    rd, rd_years, years_seen = 0.0, 0, []
    for row in by_period.values():
        value = productivity._usd(row["value"], row["unit"], rates)
        if value:
            rd += value
            rd_years += 1
            years_seen.append(_fiscal_year_of(row["period_end"]))
    # Where the filer reports R&D for its medicines segment in every year of the window,
    # that is the denominator: R&D on devices or consumer products buys no drug approvals.
    # Only for a whole window, since a decade part medicines and part company is a rate on
    # no consistent basis.
    reported = (medicines_rd() if segment is None else segment).get(ticker, {})
    rd_basis = None
    if reported:
        missing = sorted({y for y in years_seen if y not in reported})
        if years_seen and not missing and len(set(years_seen)) == len(years_seen):
            company_rd = rd
            rd = sum(productivity._usd(reported[y][0], reported[y][1], rates) or 0.0
                     for y in years_seen)
            rd_basis = (f"the medicines segment's R&D for all {len(years_seen)} years of the "
                        f"window, {rd / 1e9:,.1f}bn against {company_rd / 1e9:,.1f}bn for the "
                        "company")
        else:
            rd_basis = ("the medicines segment's R&D is not reported for "
                        + (", ".join(str(y) for y in missing) or "every year once")
                        + ", so the window reads the company's R&D")
    coverage = dated / total if total else 0.0
    # A filer whose R&D history is shorter than the window must not be handed a smaller
    # denominator for it. Sanofi's XBRL starts in 2016 and AstraZeneca's in 2015, so a
    # twelve-year window adds their later launches to the numerator while the denominator
    # stops at nine or ten years, and the rate rises for no reason but a missing filing.
    # The years on file are carried to the full window at their own average. R&D has
    # grown, so scaling a later average back over earlier years overstates what was spent
    # then and the rate reads low, which is the safe direction.
    scaled_rd, rd_scaled = rd, False
    if rd and 0 < rd_years < COHORT_YEARS:
        scaled_rd = rd / rd_years * COHORT_YEARS
        rd_scaled = True
    rate = fresh / scaled_rd if scaled_rd else None
    launches.sort(key=lambda r: -r["revenue"])
    return {"rate": rate, "year": year, "revenue": total, "dated_share": coverage,
            "fresh_revenue": fresh, "rd": scaled_rd, "rd_filed": rd,
            "rd_scaled": rd_scaled, "rd_years": rd_years,
            "rd_basis": rd_basis, "switch_forms": switched,
            "partner_funded": partnered, "acquired": purchased,
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


def book_revenue(parts: list, years: list, erosion_year1: float,
                 erosion_decay: float) -> dict:
    """{year: revenue} for the modelled book across ``years``, each part carried past its
    own forecast the way its terminal value carries it (forecast.terminal_multiple): flat
    at its long-run growth where no loss of exclusivity lies ahead or the cliff is already
    in the base, decaying where its final year is already eroding, and flat to its LOE,
    then the year-one drop and decay, where the LOE falls after the forecast ends. The
    erosion shape past the forecast is the curated default, not each product's own.

    ``parts`` are {"revenue": {year: value}, "loe_year", "loe_in_base", "growth"}. Pure."""
    out = {y: 0.0 for y in years}
    for part in parts:
        series = {y: v for y, v in (part.get("revenue") or {}).items() if v is not None}
        if not series:
            continue
        last = max(series)
        final = series[last]
        loe, in_base = part.get("loe_year"), part.get("loe_in_base")
        growth = part.get("growth") or 0.0
        for y in years:
            if y in series:
                out[y] += series[y]
                continue
            if y < last:
                continue
            k = y - last
            if loe is None or in_base:
                out[y] += final * (1.0 + growth) ** k
            elif last >= loe:
                out[y] += final * (1.0 - erosion_decay) ** k
            elif y <= loe:
                out[y] += final * (1.0 + growth) ** k
            else:
                out[y] += (final * (1.0 + growth) ** (loe - last) * (1.0 - erosion_year1)
                           * (1.0 - erosion_decay) ** (y - loe - 1))
    return out


def room(book: dict, long_run_growth: float = 0.0) -> tuple[dict, float, int | None]:
    """({year: revenue the launches may add}, the book's peak, its year). The book plus its
    launches is held to the book's own best year, grown from then at the long-run rate."""
    if not book or max(book.values()) <= 0:
        return {}, 0.0, None
    peak_year = max(book, key=lambda y: (book[y], -y))
    peak = book[peak_year]
    g = long_run_growth or 0.0
    return ({y: max(0.0, peak * (1.0 + g) ** max(0, y - peak_year) - book[y]) for y in book},
            peak, peak_year)


def simulate(book_rd: dict, rate: float, lag: int, life: int, erosion_year1: float,
             erosion_decay: float, ratios: dict, discount: float, base_year: int,
             horizon: int, long_run_growth: float | None = None,
             room: dict | None = None, history_rd: dict | None = None,
             named: dict | None = None, growth_investment: float = 0.0) -> dict:
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

    ``room`` caps the first generation too: {year: revenue the launches may add}. The
    renewal cap holds the launches' own R&D to the long-run rate, but the book's R&D
    buys launches at the rate on every dollar, so a book spending 41% of revenue on R&D
    (Regeneron) bought launches that took the company to 1.61 times its revenue by 2045.
    The book's own products fade to their long-run rate, and so does the company they
    make up: launches replace what the book loses and no more. Revenue past the room is
    not earned and its R&D buys nothing, while the book's R&D stays charged. None means
    uncapped.

    ``history_rd`` is {year: R&D the company has already spent}, for the years up to
    ``base_year``. The book's R&D starts buying launches in its first forecast year, so
    they arrive only after the lag, and the launches of the years before that were
    bought by spend already made. A year of it within ``lag`` of the base year buys a
    cohort the same way. ``named`` is {year: expected revenue of launches the book
    already models by name}, which those cohorts would otherwise count twice: it comes
    off what the cohorts earn before the room is applied.

    ``growth_investment`` is the share of the revenue each year adds that goes into plant
    and working capital, charged the way the book's own products are charged it
    (``growth_investment``): a franchise that grows for sixty years builds the capacity
    to make what it sells.
    """
    years = list(range(base_year + 1, base_year + 1 + horizon))
    spend = {y: book_rd.get(y, 0.0) for y in years}
    generation = renewal(rate, ratios["rd"], life, erosion_year1, erosion_decay)
    credited = 1.0
    if long_run_growth is not None and generation > 0:
        allowed = (1.0 + long_run_growth) ** (lag + life / 2.0)
        credited = min(1.0, allowed / generation)
    bought = {y: 0.0 for y in years}       # what the forecast's cohorts would earn
    spent = {y: 0.0 for y in years}        # what the cohorts of R&D already spent would
    revenue = {y: 0.0 for y in years}      # what they may earn, net of named, within room
    cohorts = history_cohorts = 0

    def buy(into: dict, level: float, launch: int) -> None:
        for i, y in enumerate(range(launch, years[-1] + 1)):
            if i < life:
                earned = level
            else:
                earned = level * (1.0 - erosion_year1) * (1.0 - erosion_decay) ** (i - life)
            into[y] += earned

    history = {y: v for y, v in (history_rd or {}).items()
               if y <= base_year and y + lag >= years[0] and v and v > 0}
    for s in sorted(history):
        if s + lag > years[-1]:
            continue
        history_cohorts += 1
        buy(spent, rate * history[s], s + lag)
    capped_from = None
    offered = overlap = 0.0
    for s in years:
        # A year's revenue and spend are final once reached: every cohort earning in it
        # was bought at least ``lag`` years before. A launch the book names was bought by
        # R&D already spent, so it comes off those cohorts and not the forecast's.
        own = (named or {}).get(s, 0.0)
        overlap += min(spent[s], own)
        available = max(0.0, spent[s] - own) + bought[s]
        offered += available
        revenue[s] = (available if room is None
                      else min(available, max(0.0, room.get(s, 0.0))))
        if capped_from is None and available - revenue[s] > 1e-9:
            capped_from = s
        spend[s] += revenue[s] * ratios["rd"] * credited
        if spend[s] <= 0:
            continue
        launch = s + lag
        if launch > years[-1]:
            continue
        cohorts += 1
        buy(bought, rate * spend[s], launch)
    margin = 1.0 - ratios["cogs"] - ratios["sga"] - ratios["rd"] - ratios["other"]
    pv, flows = 0.0, []
    previous = 0.0
    for y in years:
        ebit = revenue[y] * margin
        invested = (growth_investment or 0.0) * max(0.0, revenue[y] - previous)
        previous = revenue[y]
        fcff = ebit - max(0.0, ebit * ratios["tax"]) - invested
        pv += fcff / (1.0 + discount) ** ((y - base_year) - 0.5)
        flows.append({"year": y, "revenue": revenue[y], "fcff": fcff,
                      "growth_investment": invested})
    first = next((f["year"] for f in flows if f["revenue"] > 0), None)
    book_total = sum(book_rd.values())
    return {"value": pv, "flows": flows, "first_launch_year": first, "cohorts": cohorts,
            "history_cohorts": history_cohorts, "named_overlap": overlap,
            "renewal": generation, "credited_share": credited,
            "capped_from": capped_from,
            "capped_share": (1.0 - sum(revenue.values()) / offered if offered else 0.0),
            # R&D the launches go on to fund across the horizon, against the R&D the
            # book funds. Undiscounted, so it describes scale rather than value.
            "replacement": (sum(spend.values()) - book_total) / book_total
            if book_total else None}
