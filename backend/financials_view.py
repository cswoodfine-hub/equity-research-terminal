"""Assembles the three statements for one company from stored financials.

The fetcher writes reported facts. This module does the two things that need the whole
series in hand:

1. Names the periods. The months a figure covers is a fact in the filing; which fiscal
   quarter that makes it depends on the filer's year end, which is only knowable once
   the annual series is loaded.
2. Computes the subtotals filers leave untagged. Lilly never tags gross profit and
   nobody tags free cash flow. These are exact arithmetic on two reported lines, and
   every value produced this way is flagged ``derived`` so the UI can mark it. A
   subtotal is dropped rather than guessed when either input is missing.

Cash flow columns are cumulative from the year start, because that is how a 10-Q
reports them. A quarterly cash flow column would have to be derived by differencing,
which breaks silently on restatement.
"""

from __future__ import annotations

import datetime as dt

import db
import statements

DEFAULT_PERIODS = 6

# How far back the trend runs, which is as far as the EDGAR pull holds. Four quarters was
# the old limit and four points cannot show anything a trend exists to show: not a cycle,
# not a margin compressing, not a patent cliff arriving. Johnson & Johnson has forty
# quarters on file and seventeen years, and the chart is the one place on the tab with
# room for them.
TREND_QUARTERS = 40
TREND_YEARS = 17

ANNUAL, QUARTERLY = "annual", "quarterly"


def _rows(conn, company_id):
    return conn.execute(
        """
        SELECT metric, period_end, period_type, fiscal_period, value, unit
          FROM financials WHERE company_id = ?
        """,
        (company_id,),
    ).fetchall()


def collapse_adjacent(series: dict) -> dict:
    """One entry per period, where EDGAR carries a period under two nearby dates.

    A filer that restates its period end leaves both in the company facts: Exelixis has
    its June 2016 quarter at 36.3m under 2016-06-30 and again, to the cent, under
    2016-07-01. Two dates a day apart are never two quarters, so the later one wins,
    being the view the more recent filing took.

    This only became visible once the trend drew its whole history, where it plotted the
    same quarter twice side by side.
    """
    out: dict = {}
    for key in sorted(series):
        end, kind = key
        date = dt.date.fromisoformat(end)
        twin = next((k for k in out
                     if k[1] == kind
                     and 0 < (date - dt.date.fromisoformat(k[0])).days <= _SPILL_DAYS),
                    None)
        if twin is not None:
            del out[twin]
        out[key] = series[key]
    return out


def _fiscal_year_end_month(by_metric) -> int:
    """The month the filer's year ends in, from the latest annual revenue period."""
    ends = sorted(end for (end, kind) in by_metric.get("Revenues", {})
                  if kind == statements.FY)
    return int(ends[-1][5:7]) if ends else 12


# How far into a month a period end may fall and still belong to the month before. A
# 52/53 week quarter closes within a few days of the boundary; nothing legitimately ends
# a fiscal quarter on the fifth.
_SPILL_DAYS = 4


def _nearest_month_end(date: dt.date) -> tuple[int, int]:
    """(month, year) the period ends nearest, snapping a few days back over a boundary."""
    if date.day <= _SPILL_DAYS:
        first = date.replace(day=1)
        previous = first - dt.timedelta(days=1)
        return previous.month, previous.year
    return date.month, date.year


def _period_label(period_end: str, period_type: str, months: str | None,
                  fy_end_month: int) -> str:
    """A column heading: FY25, Q1 26, 6M 25, or Mar 26 for a balance sheet date."""
    date = dt.date.fromisoformat(period_end)
    # Every label reads the month the period ends nearest, not the one the date falls
    # in. Johnson & Johnson's fiscal 2011 ended on 1 January 2012 and its fiscal 2016 on
    # 1 January 2017, so a label taken from the calendar year put both a year late and
    # collided each with the year that followed it.
    month, year = _nearest_month_end(date)
    short_year = f"{year % 100:02d}"
    if period_type == statements.FY:
        return f"FY{short_year}"
    if period_type == statements.INSTANT:
        return f"{dt.date(year, month, 1).strftime('%b')} {short_year}"
    # Months into the fiscal year, 1 through 12, so the quarter number holds for a
    # filer whose year does not end in December.
    #
    # The month is the one the period ends nearest, not the one the date falls in. A
    # filer on a 52 or 53 week calendar ends its quarters on a Sunday, so the date
    # wanders either side of the month boundary: Johnson & Johnson's third quarter of
    # 2017 ended on 1 October and its second of 2018 on 1 July. Read by calendar month
    # both land a quarter late, which is how the same chart came to carry two columns
    # headed Q4 17 and a growth figure comparing a quarter against itself.
    into_year = (month - fy_end_month - 1) % 12 + 1
    fiscal_year = year + (1 if month > fy_end_month else 0)
    if period_type == statements.Q:
        return f"Q{-(-into_year // 3)} {fiscal_year % 100:02d}"
    return f"{months or ''} {fiscal_year % 100:02d}".strip()


def fourth_quarters(keys_present: set, months_by_key: dict) -> dict[tuple, tuple]:
    """Fourth quarters, as {q4_key: (full_year_key, nine_month_key)}.

    A fourth quarter is never tagged. Filers report Q1 to Q3 on 10-Qs and then the full
    year on the 10-K, so a quarterly series read straight from EDGAR jumps from Q3 to
    the next Q1 with a hole where Q4 belongs. The missing quarter is the reported year
    minus the reported nine months, which is exact arithmetic on two published figures
    rather than an estimate, and it is flagged derived like any other subtotal.
    """
    nine_months = {k for k in keys_present
                   if k[1] == statements.YTD and months_by_key.get(k) == "9M"}
    out = {}
    for fy_key in (k for k in keys_present if k[1] == statements.FY):
        fy_end = dt.date.fromisoformat(fy_key[0])
        for ytd_key in nine_months:
            gap = (fy_end - dt.date.fromisoformat(ytd_key[0])).days
            if 80 <= gap <= 100:      # the nine months ending a quarter before year end
                out[(fy_key[0], statements.Q)] = (fy_key, ytd_key)
                break
    return out


def _periods_for(statement: str, basis: str, keys_present: set,
                 fy_end_month: int, limit: int) -> list[tuple]:
    """Which columns this statement gets, most recent first.

    Cash flow under the quarterly basis is a year-to-date progression rather than a set
    of discrete quarters: a first quarter is both, and after that only the cumulative
    figure is reported. Preferring the cumulative figure where a date has both keeps one
    basis per column, and the full year is the twelve month point of the same
    progression, which is why it belongs in this view too.
    """
    if statement == "balance":
        wanted = [k for k in keys_present if k[1] == statements.INSTANT]
        if basis == ANNUAL:
            wanted = [k for k in wanted if int(k[0][5:7]) == fy_end_month]
            # The year end, not every balance date the filer tagged in that month. Legend
            # Biotech carries 16 December alongside 31 December, from a cover page share
            # count, and both are headed "Dec 22".
            latest: dict = {}
            for key in wanted:
                year = key[0][:4]
                if year not in latest or key[0] > latest[year][0]:
                    latest[year] = key
            wanted = list(latest.values())
    elif basis == ANNUAL:
        wanted = [k for k in keys_present if k[1] == statements.FY]
    elif statement == "cashflow":
        by_end: dict[str, tuple] = {}
        rank = {statements.Q: 0, statements.FY: 1, statements.YTD: 2}
        for key in keys_present:
            if key[1] not in rank:
                continue
            current = by_end.get(key[0])
            if current is None or rank[key[1]] > rank[current[1]]:
                by_end[key[0]] = key
        wanted = list(by_end.values())
    else:
        wanted = [k for k in keys_present if k[1] == statements.Q]
    return sorted(wanted, reverse=True)[:limit]


def _derive(key: str, values: dict, period) -> float | None:
    line = statements.LINES_BY_KEY[key]
    if not line.derived:
        return None
    left, _, right = line.derived
    a = values.get(left, {}).get(period)
    b = values.get(right, {}).get(period)
    if a is None or b is None:
        return None
    return a - b


# What a derived fourth quarter may be, as a multiple of the year's other quarters, and
# how alike those quarters must be before the test means anything.
#
# The subtraction is exact arithmetic on two published figures and stays exact only while
# both describe the same company. Johnson & Johnson's fiscal 2021 is on file twice over:
# the full year restated for the Kenvue separation at 78.74bn, and the nine months as
# originally reported, consumer health still in it, at 68.97bn. Subtracting one from the
# other gives a fourth quarter of 9.77bn against three quarters averaging 23.0bn. The
# real figure was 24.8bn, and the twelve billion the subtraction lost is the consumer
# business leaving the numerator only.
#
# Nothing in the facts says which year is restated, so the tell has to be the answer
# itself. But an answer is only surprising against an expectation, and most of this
# universe has none: a developer whose revenue is milestone payments can book nothing for
# three quarters and forty million in the fourth, and Moderna's fourth quarter of 2020 was
# seven times its average because that is when the vaccine shipped. Judging those on the
# same rule deletes the most interesting quarter each company has.
#
# So the test runs only where the three quarters already reported are close enough
# together to predict a fourth from. That is true of a major with a marketed portfolio
# and false of everyone whose revenue arrives in lumps, which is the correct place for
# the line: the first is where a restatement hides, and the second is where it cannot be
# told from the business.
# Only the low side is refused, and only above a size. A restatement removes a business
# from the year and not from the nine months, so it always makes the fourth quarter too
# small: Johnson & Johnson comes out at 0.42 and Merck at 0.35. Every quarter that came
# out high turned out to be the business, not the arithmetic. Beam's fourth quarter of
# 2023 is fifteen times its average because a licence fee landed in it, Moderna's of 2020
# is seven times because that is when the vaccine shipped, and refusing those deletes the
# most consequential quarter each company has.
Q4_PLAUSIBLE_LOW = 0.5
Q4_STEADY_SPREAD = 1.6          # the widest max-over-min that still counts as steady
# Below this a quarter's revenue is milestones and licence fees rather than a book of
# products, and a year that looks unlike its quarters is the business rather than a
# restatement of it.
Q4_JUDGED_ABOVE = 250e6


def _quarters_within(series: dict, nine_months, full_year) -> list:
    """The reported quarters inside a nine month window, by date."""
    opens = dt.date.fromisoformat(full_year[0]) - dt.timedelta(days=370)
    closes = dt.date.fromisoformat(nine_months[0])
    return [value for (end, kind), value in series.items()
            if kind == statements.Q and value is not None
            and opens < dt.date.fromisoformat(end) <= closes]


def _q4_reconciles(by_metric: dict, full_year, nine_months) -> bool:
    """Whether a year and its nine months are the same basis, judged on revenue.

    Judged once for the pair rather than per line, because a restatement moves every line
    together: if the year excludes a business the nine months included, no figure in it is
    comparable, not the revenue and not the tax charge.

    Anything the test cannot speak to is derived as before. Never refuse on a guess.
    """
    revenue = by_metric.get("Revenues", {})
    year, ytd = revenue.get(full_year), revenue.get(nine_months)
    if year is None or ytd is None or ytd <= 0:
        return True

    # No company sells a negative amount in a quarter. Whatever produced it, the two
    # figures are not the same basis, and this holds at any size.
    if year - ytd < 0:
        return False

    quarters = _quarters_within(revenue, nine_months, full_year)
    if len(quarters) < 3 or min(quarters) <= 0:
        return True                      # nothing to form an expectation from
    if max(quarters) / min(quarters) > Q4_STEADY_SPREAD:
        return True                      # lumpy by nature, so a wide fourth says nothing

    typical = sorted(quarters)[len(quarters) // 2]
    if typical < Q4_JUDGED_ABOVE:
        return True                      # too small for the test to mean anything
    return (year - ytd) / typical >= Q4_PLAUSIBLE_LOW


def _fill_fourth_quarters(by_metric: dict, q4_map: dict):
    """A copy of the series with fourth quarters filled, plus which cells were filled.

    A pair that does not reconcile is left alone, so the quarter reads as the gap it is
    rather than as a collapse the company never had.
    """
    values = {key: dict(series) for key, series in by_metric.items()}
    filled: set[tuple[str, tuple]] = set()
    q4_map = {period: pair for period, pair in q4_map.items()
              if _q4_reconciles(by_metric, *pair)}
    for period, (full_year, nine_months) in q4_map.items():
        for key, series in by_metric.items():
            line = statements.LINES_BY_KEY.get(key)
            if line is None or not line.additive:
                continue          # EPS and average share counts do not subtract
            year, ytd = series.get(full_year), series.get(nine_months)
            if year is not None and ytd is not None and period not in series:
                values[key][period] = year - ytd
                filled.add((key, period))
    return values, filled


def _prior_period(series: dict, key: tuple, tolerance_days: int = 14):
    """The same period one year earlier, or None.

    A 52/53 week filer moves its period end by a day or two each year, so an exact date
    match drops the comparison for JNJ every time. The nearest same-kind period inside a
    fortnight is the same period; anything further away is a different one.
    """
    end, kind = key
    try:
        target = dt.date.fromisoformat(end).replace(year=int(end[:4]) - 1)
    except ValueError:            # 29 February has no counterpart in a common year
        return None
    exact = (target.isoformat(), kind)
    if exact in series:
        return exact
    near = sorted(
        (k for k in series
         if k[1] == kind
         and abs((dt.date.fromisoformat(k[0]) - target).days) <= tolerance_days),
        key=lambda k: abs((dt.date.fromisoformat(k[0]) - target).days))
    return near[0] if near else None


def build_trend(values: dict, months_by_key: dict, fy_end_month: int,
                basis: str = QUARTERLY, limit: int = TREND_QUARTERS) -> list[dict]:
    """Revenue growth and net margin per period, oldest first.

    The two are returned together and on the same scale because the question they answer
    is one question: whether the growth is reaching the bottom line. Both are shares, so
    they share a percentage axis and can be read against each other directly rather than
    through two y-scales that could be slid to tell any story.
    """
    revenue = values.get("Revenues", {})
    income = values.get("NetIncomeLoss", {})
    kind = statements.Q if basis == QUARTERLY else statements.FY

    points = []
    for key in sorted(k for k in revenue if k[1] == kind)[-limit:]:
        sales = revenue.get(key)
        if not sales:
            continue              # a zero or missing base has no margin and no growth
        prior = _prior_period(revenue, key)
        earlier = revenue.get(prior) if prior else None
        net = income.get(key)
        points.append({
            "label": _period_label(key[0], kind, months_by_key.get(key), fy_end_month),
            "period_end": key[0],
            "revenue_growth": (sales / earlier - 1) if earlier else None,
            "net_margin": (net / sales) if net is not None else None,
        })
    return points


def build_statements(db_path=None, ticker: str = "", basis: str = QUARTERLY,
                     limit: int = DEFAULT_PERIODS):
    """The three statements for one company, or None when the ticker is unknown."""
    ticker = ticker.upper()
    basis = basis if basis in (ANNUAL, QUARTERLY) else QUARTERLY
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id, name, is_sec_filer FROM companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if company is None:
            return None
        rows = _rows(conn, company["id"])
    finally:
        conn.close()

    by_metric: dict[str, dict] = {}
    months_by_key: dict[tuple, str] = {}
    units: dict[str, str] = {}
    for row in rows:
        key = (row["period_end"], row["period_type"])
        by_metric.setdefault(row["metric"], {})[key] = row["value"]
        if row["fiscal_period"]:
            months_by_key[key] = row["fiscal_period"]
        if row["unit"]:
            units.setdefault(row["metric"], row["unit"])

    # Collapsed before anything reads a series, so the trend, the statements and the
    # snapshot all see one entry per period rather than two.
    by_metric = {metric: collapse_adjacent(series)
                 for metric, series in by_metric.items()}

    fy_end_month = _fiscal_year_end_month(by_metric)
    currency = units.get("Revenues") or units.get("NetIncomeLoss")

    # Fourth quarters are filled once, before anything reads the series, so a derived
    # gross profit can be built on a derived Q4 revenue rather than reading blank in a
    # column where both of its inputs resolve, and so the trend has no hole every fourth
    # point. They are only ever selected as columns on the quarterly income statement.
    income_keys = {key for line in statements.lines_for("income")
                   for key in by_metric.get(line.key, {})}
    q4_map = fourth_quarters(income_keys, months_by_key)
    values, filled = _fill_fourth_quarters(by_metric, q4_map)

    out = {}
    for statement in statements.STATEMENTS:
        keys_present = {key for line in statements.lines_for(statement)
                        for key in by_metric.get(line.key, {})}
        # Discrete quarters only. The cash flow view is cumulative, so a fourth quarter
        # there would mean differencing, and the balance sheet has no durations at all.
        q4 = {} if statement != "income" or basis == ANNUAL else q4_map
        periods = _periods_for(statement, basis, keys_present | set(q4),
                               fy_end_month, limit)

        lines = []
        for line in statements.lines_for(statement):
            reported = values.get(line.key, {})
            cells = []
            for period in periods:
                value = reported.get(period)
                derived = (line.key, period) in filled
                if value is None:
                    value = _derive(line.key, values, period)
                    derived = value is not None
                cells.append({"value": value, "derived": derived})
            if any(cell["value"] is not None for cell in cells):
                lines.append({
                    "key": line.key, "label": line.label, "role": line.role,
                    "note": line.note, "unit": units.get(line.key, currency),
                    "cells": cells,
                })
        base_key = statements.COMMON_SIZE_BASE[statement]
        out[statement] = {
            "base": {
                "key": base_key,
                "label": statements.LINES_BY_KEY[base_key].label,
                "values": [values.get(base_key, {}).get(period) for period in periods],
            },
            "periods": [{
                "period_end": end, "period_type": kind,
                "months": months_by_key.get((end, kind)),
                "label": _period_label(end, kind, months_by_key.get((end, kind)),
                                       fy_end_month),
            } for end, kind in periods],
            "lines": lines,
        }

    return {
        "ticker": ticker, "name": company["name"], "currency": currency,
        "basis": basis, "is_sec_filer": bool(company["is_sec_filer"]),
        "has_interim": any(kind in (statements.Q, statements.YTD)
                           for periods in by_metric.values() for _, kind in periods),
        "statements": out,
        "snapshot": _snapshot(by_metric, months_by_key, fy_end_month, currency),
        # Annual shows DEFAULT_PERIODS years; the extra stored year is not shown, it is the
        # base the oldest shown year's growth divides by, so both lines start together.
        "trend": build_trend(values, months_by_key, fy_end_month, basis,
                             limit=TREND_YEARS if basis == ANNUAL else TREND_QUARTERS),
    }


def _latest(series: dict, kinds) -> tuple | None:
    keys = sorted((k for k in series if k[1] in kinds), reverse=True)
    return keys[0] if keys else None


def _snapshot(by_metric, months_by_key, fy_end_month, currency) -> dict | None:
    """The most recent reported period, with the same period a year earlier.

    Growth compares like with like: a quarter against the same quarter of the prior
    year, never against the quarter before it, so seasonality is not read as a trend.
    """
    revenue = by_metric.get("Revenues", {})
    period = _latest(revenue, (statements.Q, statements.FY))
    if period is None:
        return None
    end, kind = period
    prior = _prior_period(revenue, period)

    def value(key, at):
        return by_metric.get(key, {}).get(at) if at else None

    def growth(key):
        now, before = value(key, period), value(key, prior)
        if now is None or not before:
            return None
        return now / before - 1

    net_income = value("NetIncomeLoss", period)
    revenue_now = value("Revenues", period)
    return {
        "period_end": end,
        "period_type": kind,
        "label": _period_label(end, kind, months_by_key.get(period), fy_end_month),
        "currency": currency,
        "revenue": revenue_now,
        "revenue_growth": growth("Revenues"),
        "net_income": net_income,
        "net_income_growth": growth("NetIncomeLoss"),
        "eps_diluted": value("EarningsPerShareDiluted", period),
        "rd_expense": value("ResearchAndDevelopmentExpense", period),
        "net_margin": (net_income / revenue_now
                       if net_income is not None and revenue_now else None),
        "rd_intensity": (value("ResearchAndDevelopmentExpense", period) / revenue_now
                         if value("ResearchAndDevelopmentExpense", period) is not None
                         and revenue_now else None),
    }
