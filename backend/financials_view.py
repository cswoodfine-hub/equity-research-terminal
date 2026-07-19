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

ANNUAL, QUARTERLY = "annual", "quarterly"


def _rows(conn, company_id):
    return conn.execute(
        """
        SELECT metric, period_end, period_type, fiscal_period, value, unit
          FROM financials WHERE company_id = ?
        """,
        (company_id,),
    ).fetchall()


def _fiscal_year_end_month(by_metric) -> int:
    """The month the filer's year ends in, from the latest annual revenue period."""
    ends = sorted(end for (end, kind) in by_metric.get("Revenues", {})
                  if kind == statements.FY)
    return int(ends[-1][5:7]) if ends else 12


def _period_label(period_end: str, period_type: str, months: str | None,
                  fy_end_month: int) -> str:
    """A column heading: FY25, Q1 26, 6M 25, or Mar 26 for a balance sheet date."""
    date = dt.date.fromisoformat(period_end)
    short_year = f"{date.year % 100:02d}"
    if period_type == statements.FY:
        return f"FY{short_year}"
    if period_type == statements.INSTANT:
        return f"{date.strftime('%b')} {short_year}"
    # Months into the fiscal year, 1 through 12, so the quarter number holds for a
    # filer whose year does not end in December.
    into_year = (date.month - fy_end_month - 1) % 12 + 1
    fiscal_year = date.year + (1 if date.month > fy_end_month else 0)
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


def _fill_fourth_quarters(by_metric: dict, q4_map: dict):
    """A copy of the series with fourth quarters filled, plus which cells were filled."""
    values = {key: dict(series) for key, series in by_metric.items()}
    filled: set[tuple[str, tuple]] = set()
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
                basis: str = QUARTERLY, limit: int = 9) -> list[dict]:
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
        "trend": build_trend(values, months_by_key, fy_end_month, basis),
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
