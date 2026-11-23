"""One way to test whether anything the book notices is worth acting on.

On 2026-11-23 three candidate signals were tested by three hand-built scripts, each with
its own entry rule, its own placebo and its own idea of enough. Two of the three results
could not be compared with each other, one used a column as it stands today for a fact
that was meant to be known beforehand, and none charged a cost. This module is the one
measurement every signal goes through from here, so a result means the same thing
whichever signal it is about.

A signal is registered in ``data/signals.csv`` before it is measured: its rule in words,
the side it claims (the share beats XBI, or lags it), the horizon it is judged at, the
day the rule was written, and whether the rule was written before looking or found by
trying cuts. That file is the ledger of everything tried, kept or dropped, and the count
of rows in it is what a reader weighs a surviving signal against.

What the measurement does, the same for every signal:

- **Entry at the next session's close.** An event dated D is acted on at the close of the
  first trading day after D. Nothing known only on D's evening is used on D.
- **Against XBI**, for the reason ``event_signal`` gives: the book's own universe is a
  benchmark almost anything beats.
- **Against a placebo drawn on the same entry days**, from the other companies in the
  book that traded that day, so a signal has to beat its own week and not its quarter.
- **After costs.** A round trip is charged one full bid-ask spread, estimated from each
  share's own daily highs and lows (Corwin and Schultz, 2012) over the month before
  entry, and a share that traded less than ``MIN_DOLLAR_VOLUME`` a day is left out and
  counted. Borrow cost on a short is not known from free data and is not charged, which
  the result says.
- **Counted by what is independent.** The t statistic is taken over calendar months and
  again over companies, never over events: two events on one company a week apart share
  almost all of their window.
- **In both halves, and with the winners capped.** A result carried by one period or by
  three shares is shown to be.

What counts as passing, and what passing does not mean. A rule written before looking
needs t of ``T_WRITTEN_FIRST`` by month and by company, after costs, at its registered
horizon, with both halves on its side. A rule found by trying cuts needs
``T_SEARCHED``. Passing here is a backtest on the companies the book covers today, which
were chosen with hindsight: the result carries ``survivors_only`` until it has been
repeated on names outside the book, and ``forward`` counts the events that fell after
the rule was written, which is the only part of the record that cannot have been fitted.

Reads only. Nothing here writes to the book.
"""

from __future__ import annotations

import bisect
import csv
import datetime as dt
import math
import pathlib
import random
import statistics

import benchmark_series
import db

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data"
REGISTER = DATA_DIR / "signals.csv"

HORIZONS = (("1 month", 21), ("3 months", 63), ("6 months", 126))
PLACEBO_DRAWS = 60
PLACEBO_SEED = 11
SPREAD_WINDOW = 21                 # trading days before entry the spread is estimated on
MIN_DOLLAR_VOLUME = 1_000_000.0    # median daily value traded over the same window
# The floors every result is also shown at. What a reader can trade depends on the size
# of the position, which the book does not know, so the answer is given at each rather
# than at one: on 2026-11-23 officer purchases read t 2.8 by month with no floor and 1.7
# at a million dollars a day, and the difference is the finding.
FLOORS = (0.0, 250_000.0, 1_000_000.0, 5_000_000.0)
T_WRITTEN_FIRST = 2.0
T_SEARCHED = 3.0
# Below these the answer is that there is not enough to say, whatever the average.
MIN_EVENTS = 30
MIN_MONTHS = 12
MIN_COMPANIES = 10
MIN_FORWARD = 10
CAP_PERCENTILE = 0.95

# Columns that say how a thing stands today and not when it came to be so. An event
# source that reads one is using hindsight: on 2026-11-23 "marketed drugs read out
# positive 88% of the time" was read off assets.is_marketed, which a drug gains because
# its Phase 3 worked. A test reads every source's own text for these.
UNDATED_COLUMNS = ("is_marketed", "overall_status", "marketing_status", "updated_at",
                   "fetched_at", "last_update_posted")

SIDES = {"outperform": 1.0, "underperform": -1.0}
BASES = ("written_first", "searched")
STATUSES = ("registered", "dropped", "passed")


# --- the register -----------------------------------------------------------------------
def register(path=None) -> list[dict]:
    """Every signal on file, kept or dropped. A row this cannot read is refused rather
    than skipped: a signal measured under a rule nobody can state is not a signal."""
    source = pathlib.Path(path) if path else REGISTER
    if not source.exists():
        return []
    out = []
    with source.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(l for l in handle if not l.lstrip().startswith("#")):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            side, basis = (row.get("side") or "").strip(), (row.get("basis") or "").strip()
            status = (row.get("status") or "registered").strip()
            if side not in SIDES or basis not in BASES or status not in STATUSES:
                raise ValueError(f"signals.csv: {name} has side {side!r}, basis {basis!r}, "
                                 f"status {status!r}")
            written = dt.date.fromisoformat((row.get("written") or "").strip()).isoformat()
            out.append({"name": name, "rule": (row.get("rule") or "").strip(),
                        "side": side, "basis": basis, "written": written,
                        "horizon_days": int(row.get("horizon_days") or 0),
                        "status": status, "note": (row.get("note") or "").strip()})
    return out


# --- prices -----------------------------------------------------------------------------
def load_prices(conn) -> dict:
    """{company_id: {days, close, high, low, volume}} of daily bars, oldest first."""
    out: dict = {}
    for r in conn.execute(
            "SELECT company_id, substr(as_of, 1, 10) AS d, close, high, low, volume"
            "  FROM prices WHERE interval = '1d' AND close IS NOT NULL ORDER BY as_of"):
        s = out.setdefault(r["company_id"], {"days": [], "close": [], "high": [],
                                             "low": [], "volume": []})
        s["days"].append(r["d"])
        s["close"].append(r["close"])
        s["high"].append(r["high"])
        s["low"].append(r["low"])
        s["volume"].append(r["volume"])
    return out


def entry_day(bench_days: list, day: str) -> str | None:
    """The first trading day after ``day``, by the benchmark's own calendar."""
    i = bisect.bisect_right(bench_days, (day or "")[:10])
    return bench_days[i] if i < len(bench_days) else None


def _index(series: dict, day: str) -> int | None:
    i = bisect.bisect_left(series["days"], day)
    return i if i < len(series["days"]) and series["days"][i] == day else None


def forward(series: dict, bench: tuple, entry: str, horizon: int) -> float | None:
    """The share's return over ``horizon`` bars from its close on ``entry``, less XBI's
    over the same bars. None where the share did not trade that day or either series
    ends first."""
    i = _index(series, entry)
    bdays, bclose = bench
    j = bisect.bisect_left(bdays, entry)
    if (i is None or i + horizon >= len(series["days"]) or j >= len(bdays)
            or bdays[j] != entry or j + horizon >= len(bdays)
            or not series["close"][i] or not bclose[j]):
        return None
    return (series["close"][i + horizon] / series["close"][i] - 1) - (
        bclose[j + horizon] / bclose[j] - 1)


def spread(series: dict, i: int, window: int = SPREAD_WINDOW) -> float | None:
    """The share's proportional bid-ask spread at bar ``i``, from the highs and lows of
    the ``window`` bars up to and including it. Corwin and Schultz (2012): a day's
    high is a buy and its low a sell, so the two-day range carries the spread once and
    the variance twice. A two-day estimate below nought is set to nought, as they do.
    None where fewer than half the pairs can be formed."""
    k = 3 - 2 * math.sqrt(2)
    got = []
    for t in range(max(1, i - window + 1), i + 1):
        h0, l0, h1, l1 = (series["high"][t - 1], series["low"][t - 1],
                          series["high"][t], series["low"][t])
        if not (h0 and l0 and h1 and l1) or l0 <= 0 or l1 <= 0 or h0 < l0 or h1 < l1:
            continue
        beta = math.log(h0 / l0) ** 2 + math.log(h1 / l1) ** 2
        gamma = math.log(max(h0, h1) / min(l0, l1)) ** 2
        alpha = (math.sqrt(2 * beta) - math.sqrt(beta)) / k - math.sqrt(gamma / k)
        got.append(max(0.0, 2 * (math.exp(alpha) - 1) / (1 + math.exp(alpha))))
    if len(got) < max(2, window // 2):
        return None
    return sum(got) / len(got)


def dollar_volume(series: dict, i: int, window: int = SPREAD_WINDOW) -> float | None:
    """Median daily value traded over the ``window`` bars up to and including ``i``."""
    got = [c * v for c, v in zip(series["close"][max(0, i - window + 1):i + 1],
                                 series["volume"][max(0, i - window + 1):i + 1])
           if c is not None and v is not None]
    return statistics.median(got) if got else None


# --- the measurement --------------------------------------------------------------------
def _t(values: list) -> float | None:
    if len(values) < 3:
        return None
    sd = statistics.stdev(values)
    return statistics.mean(values) / (sd / math.sqrt(len(values))) if sd else None


def _summary(rows: list, key: str) -> dict:
    """One set of events described on one return: ``key`` is the per-event excess over
    the placebo on the signal's side, before or after costs."""
    if not rows:
        return {"n": 0}
    values = [r[key] for r in rows]
    months: dict = {}
    companies: dict = {}
    for r in rows:
        months.setdefault(r["entry"][:7], []).append(r[key])
        companies.setdefault(r["company_id"], []).append(r[key])
    by_month = [statistics.mean(v) for v in months.values()]
    by_company = [statistics.mean(v) for v in companies.values()]
    return {"n": len(rows), "companies": len(companies), "months": len(months),
            "mean": statistics.mean(values), "median": statistics.median(values),
            "t_by_month": _t(by_month), "t_by_company": _t(by_company),
            "companies_ahead": sum(1 for v in by_company if v > 0)}


def measure(prices: dict, bench: tuple, events: list, *, side: str = "outperform",
            horizon: int = 126, basis: str = "written_first", written: str | None = None,
            seed: int = PLACEBO_SEED, draws: int = PLACEBO_DRAWS,
            min_dollar_volume: float = MIN_DOLLAR_VOLUME) -> dict:
    """Measure one signal at one horizon. ``events`` are {company_id, day}; the day is
    when the fact became public. Pure: the same events and prices give the same answer.
    """
    sign = SIDES[side]
    rng = random.Random(seed)
    pool = sorted(prices)
    # no_spread is an entry with too few bars behind it to estimate one from, which in
    # practice is an event in the first weeks of the stored series.
    rows, dropped = [], {"no_entry_day": 0, "no_price_at_entry": 0, "window_not_over": 0,
                         "too_thin_to_trade": 0, "no_spread": 0, "no_placebo": 0}
    for e in sorted(events, key=lambda e: (e["day"], e["company_id"])):
        entry = entry_day(bench[0], e["day"])
        if entry is None:
            dropped["no_entry_day"] += 1
            continue
        series = prices.get(e["company_id"])
        i = _index(series, entry) if series else None
        if i is None:
            dropped["no_price_at_entry"] += 1
            continue
        raw = forward(series, bench, entry, horizon)
        if raw is None:
            dropped["window_not_over"] += 1
            continue
        traded = dollar_volume(series, i)
        if traded is None or traded < min_dollar_volume:
            dropped["too_thin_to_trade"] += 1
            continue
        cost = spread(series, i)
        if cost is None:
            dropped["no_spread"] += 1
            continue
        others = [c for c in pool if c != e["company_id"]]
        placebo = []
        for c in rng.sample(others, min(draws, len(others))):
            v = forward(prices[c], bench, entry, horizon)
            if v is not None:
                placebo.append(v)
        if not placebo:
            dropped["no_placebo"] += 1
            continue
        mean_placebo = statistics.mean(placebo)
        rows.append({"company_id": e["company_id"], "day": e["day"], "entry": entry,
                     "abnormal": raw, "on_side": sign * raw, "cost": cost,
                     "placebo": mean_placebo,
                     "placebo_ahead": sum(1 for v in placebo if sign * v > 0) / len(placebo),
                     "excess": sign * (raw - mean_placebo),
                     "excess_net": sign * (raw - mean_placebo) - cost})

    out = {"side": side, "horizon_days": horizon, "basis": basis, "events": len(events),
           "measured": len(rows), "dropped": {k: v for k, v in dropped.items() if v},
           "survivors_only": True,
           "costs": "one full spread a round trip, estimated from daily highs and lows"
                    + ("; borrow cost on the short is not charged" if sign < 0 else "")}
    if not rows:
        out["verdict"] = "nothing to measure"
        return out

    on_side = [r["on_side"] for r in rows]
    out.update({
        "first": rows[0]["entry"], "last": rows[-1]["entry"],
        "median_against_xbi": statistics.median(r["abnormal"] for r in rows),
        "mean_against_xbi": statistics.mean(r["abnormal"] for r in rows),
        "on_side_of_xbi": sum(1 for v in on_side if v > 0) / len(on_side),
        "placebo_on_side_of_xbi": statistics.mean(r["placebo_ahead"] for r in rows),
        "median_spread": statistics.median(r["cost"] for r in rows),
        "over_placebo": _summary(rows, "excess"),
        "over_placebo_net": _summary(rows, "excess_net"),
    })
    half = len(rows) // 2
    out["halves"] = [dict(_summary(part, "excess_net"),
                          first=part[0]["entry"], last=part[-1]["entry"])
                     for part in (rows[:half], rows[half:]) if part]
    cap = sorted(on_side)[min(len(on_side) - 1, int(CAP_PERCENTILE * len(on_side)))]
    capped = [dict(r, excess_net=r["excess_net"] - max(0.0, r["on_side"] - cap))
              for r in rows]
    out["winners_capped"] = dict(_summary(capped, "excess_net"), cap=cap)
    if written:
        after = [r for r in rows if r["entry"] > written]
        out["forward"] = dict(_summary(after, "excess_net"), since=written)

    need = T_WRITTEN_FIRST if basis == "written_first" else T_SEARCHED
    net = out["over_placebo_net"]
    enough = (net["n"] >= MIN_EVENTS and net["months"] >= MIN_MONTHS
              and net["companies"] >= MIN_COMPANIES)
    passes = (enough and (net["t_by_month"] or 0) >= need
              and (net["t_by_company"] or 0) >= need
              and all((h.get("mean") or 0) > 0 for h in out["halves"]))
    out["t_needed"] = need
    out["passes_backtest"] = bool(passes)
    forward_n = (out.get("forward") or {}).get("n", 0)
    if not enough:
        out["verdict"] = (f"too few to say: {net['n']} events over {net['months']} months "
                          f"and {net['companies']} companies, against "
                          f"{MIN_EVENTS}, {MIN_MONTHS} and {MIN_COMPANIES}")
    elif not passes:
        out["verdict"] = "does not pass: " + "; ".join(
            reason for reason, bad in (
                (f"t by month {net['t_by_month']:.2f} is under {need:.0f}"
                 if net["t_by_month"] is not None else "t by month cannot be computed",
                 (net["t_by_month"] or 0) < need),
                (f"t by company {net['t_by_company']:.2f} is under {need:.0f}"
                 if net["t_by_company"] is not None else "t by company cannot be computed",
                 (net["t_by_company"] or 0) < need),
                ("one half is not on its side",
                 not all((h.get("mean") or 0) > 0 for h in out["halves"]))) if bad)
    else:
        out["verdict"] = ("passes the backtest on the book's own names. Not proven: it "
                          "has not been repeated outside the book, and "
                          + (f"{forward_n} events have fallen since the rule was written"
                             if forward_n >= MIN_FORWARD else
                             f"only {forward_n} events have fallen since the rule was "
                             f"written, against the {MIN_FORWARD} a forward check needs"))
    return out


# --- where each signal's events come from -------------------------------------------------
def first_in(rows: list, gap_days: int = 30) -> list:
    """One event a company a cluster: the first day with none in the ``gap_days`` before
    it. ``rows`` are {company_id, day}."""
    out, last = [], {}
    for r in sorted(rows, key=lambda r: (r["company_id"], r["day"])):
        day = dt.date.fromisoformat(r["day"][:10])
        prev = last.get(r["company_id"])
        if prev is None or (day - prev).days > gap_days:
            out.append({"company_id": r["company_id"], "day": r["day"][:10]})
        last[r["company_id"]] = day
    return out


def officer_purchases(conn) -> list:
    """Open-market purchases of the shares themselves on a Form 4 naming an officer and
    no ten percent holder, dated by the day EDGAR lists the filing under. An amendment is
    left out: the form it corrects is already here under its own date."""
    rows = [{"company_id": r["company_id"], "day": r["filed_date"]} for r in conn.execute(
        """SELECT company_id, filed_date FROM insider_transactions
            WHERE transaction_code = 'P' AND is_derivative = 0 AND acquired_disposed = 'A'
              AND form_type = '4' AND is_officer = 1
              AND COALESCE(is_ten_percent_owner, 0) = 0
              AND shares > 0 AND price_per_share > 0 AND filed_date IS NOT NULL""")]
    return first_in(rows, 30)


_PARTIALS = ("3M", "6M", "9M", "12M")


def short_runway(conn, months: float = 12.0) -> list:
    """A balance sheet that shows under ``months`` of cash at the trailing twelve month
    operating burn, dated 60 days after a quarter end and 90 after a year end, which is
    when the figures can be taken as public. One event a company a balance sheet."""
    cash: dict = {}
    for r in conn.execute(
            "SELECT company_id, period_end, value FROM financials WHERE metric IN"
            " ('CashAndEquivalents','ShortTermInvestments','LongTermInvestments')"
            "  AND value IS NOT NULL"):
        key = (r["company_id"], r["period_end"])
        cash[key] = cash.get(key, 0.0) + r["value"]
    has_cash = {(r["company_id"], r["period_end"]) for r in conn.execute(
        "SELECT company_id, period_end FROM financials"
        " WHERE metric = 'CashAndEquivalents' AND value IS NOT NULL")}
    flows: dict = {}
    for r in conn.execute(
            "SELECT company_id, fiscal_year, fiscal_period, period_end, value"
            "  FROM financials WHERE metric = 'CashFlowOperating' AND value IS NOT NULL"
            "   AND fiscal_year IS NOT NULL"):
        fp = "12M" if r["fiscal_period"] in ("12M", "FY") else r["fiscal_period"]
        if fp in _PARTIALS:
            flows.setdefault(r["company_id"], {}).setdefault(r["fiscal_year"], {})[fp] = (
                r["period_end"], r["value"])
    out = []
    for cid, years in flows.items():
        for fy, parts in years.items():
            for fp, (period_end, value) in parts.items():
                if fp == "12M":
                    burn = value
                else:
                    prior = years.get(fy - 1, {})
                    if "12M" not in prior or fp not in prior:
                        continue
                    burn = prior["12M"][1] - prior[fp][1] + value
                total = cash.get((cid, period_end))
                if (cid, period_end) not in has_cash or not total or total <= 0 or burn >= 0:
                    continue
                if total / (-burn / 12.0) < months:
                    known = dt.date.fromisoformat(period_end) + dt.timedelta(
                        days=90 if fp == "12M" else 60)
                    out.append({"company_id": cid, "day": known.isoformat()})
    return sorted(out, key=lambda e: (e["day"], e["company_id"]))


SOURCES = {"officer_purchase": officer_purchases, "short_runway": short_runway}


def build(db_path=None, register_path=None) -> dict:
    """Every registered signal measured at its own horizon, and at the others for
    context. A signal with no source here is listed with the reason."""
    conn = db.get_connection(db_path)
    try:
        prices = load_prices(conn)
        bars = benchmark_series.series(conn)
        bench = ([d for d, _ in bars], [c for _, c in bars])
        signals = []
        for entry in register(register_path):
            row = dict(entry)
            source = SOURCES.get(entry["name"])
            if source is None:
                row["verdict"] = "registered; no event source is built for it yet"
            elif not bench[0]:
                row["verdict"] = "no XBI series on file to measure against"
            else:
                events = source(conn)
                row["result"] = measure(prices, bench, events, side=entry["side"],
                                        horizon=entry["horizon_days"], basis=entry["basis"],
                                        written=entry["written"])
                row["verdict"] = row["result"]["verdict"]
                row["by_liquidity_floor"] = [
                    dict({k: v for k, v in measure(
                        prices, bench, events, side=entry["side"],
                        horizon=entry["horizon_days"], basis=entry["basis"],
                        written=entry["written"], min_dollar_volume=floor).items()
                        if k in ("measured", "median_against_xbi", "on_side_of_xbi",
                                 "placebo_on_side_of_xbi", "over_placebo_net",
                                 "passes_backtest")}, floor=floor)
                    for floor in FLOORS]
                row["other_horizons"] = {
                    label: {k: v for k, v in measure(
                        prices, bench, events, side=entry["side"], horizon=days,
                        basis=entry["basis"], written=entry["written"]).items()
                        if k in ("measured", "median_against_xbi", "on_side_of_xbi",
                                 "placebo_on_side_of_xbi", "over_placebo_net")}
                    for label, days in HORIZONS if days != entry["horizon_days"]}
            signals.append(row)
    finally:
        conn.close()
    return {
        "benchmark": benchmark_series.BENCHMARK, "signals": signals,
        "tried": len(signals),
        "dropped": sum(1 for s in signals if s["status"] == "dropped"),
        "standard": {
            "entry": "the close of the first trading day after the event",
            "t_written_first": T_WRITTEN_FIRST, "t_searched": T_SEARCHED,
            "min_events": MIN_EVENTS, "min_months": MIN_MONTHS,
            "min_companies": MIN_COMPANIES,
            "min_dollar_volume": MIN_DOLLAR_VOLUME,
            "reading": ("a signal passes the backtest when its excess over a same-day "
                        "placebo, after one spread a round trip, has that t by month and "
                        "by company at its registered horizon with both halves on its "
                        "side. Every result is on the companies the book covers today "
                        "(survivors only) and is proven only when it also holds outside "
                        "the book and on events after the rule was written")},
    }
