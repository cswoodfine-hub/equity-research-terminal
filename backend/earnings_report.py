"""The latest earnings report as one reading: what was filed and how it landed.

A quarter's figures say what happened. They do not say whether it was better than the
price already held, what management changed about the year, or what the market made of
it, and those three are what an analyst opens a report to find. Each of them was
already in the database in a different table, or one request away, and nothing put them
beside the figures they qualify.

This assembles them, and every part of the answer is a fact about a report that has
been filed, so it sits on the financials tab and not the forecast one:

  street     the quarter's EPS against the consensus that stood before it
  guidance   each guided figure against the reading before this report
  day        the first close that could react, against the close before, and a benchmark
  book       this book's value a share before and after
  drivers    the products that made the quarter, against the same quarter a year before
  history    the last four reports, the same way

The verdict is rules, stated below and tested, never a model's reading. Nothing is
filled in: a part with no data is null and carries the reason, and a verdict is built
only from the parts that are there.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import benchmark_series as _bench
import db
import financials_view

# Inside this many per cent either side of consensus a quarter is in line. Nasdaq rounds
# both EPS figures to the cent, so on a consensus of fifty cents one cent of rounding is
# two per cent on its own; a band narrower than that would call rounding a result.
IN_LINE_BAND = 2.0
# A guided figure that moved by less than this share of itself was restated, not changed.
HELD_BAND = 0.0005
# Guidance is read out of the results release, which is filed on the day of the report
# or within a few days of it where the release follows the call.
GUIDANCE_WINDOW_DAYS = 5
# The close a report can move has to be near it. A gap longer than this between the
# report and the next stored close is a hole in the price history, not a reaction.
MAX_SESSION_GAP_DAYS = 5
HISTORY_QUARTERS = 4
DRIVER_ROWS = 6

_NEW_YORK = ZoneInfo("America/New_York")
_CLOSE = dt.time(16, 0)
_OPEN = dt.time(9, 30)

_GUIDED = {"Revenue": "revenue", "RevenueGrowth": "revenue growth",
           "ProductSales": "product sales", "EPS": "EPS"}


# --- the rules -----------------------------------------------------------------------

def result_of(surprise_pct) -> str | None:
    """beat, miss or in line, from the EPS surprise in per cent. None with no figure."""
    if surprise_pct is None:
        return None
    if surprise_pct > IN_LINE_BAND:
        return "beat"
    if surprise_pct < -IN_LINE_BAND:
        return "miss"
    return "in line"


def guidance_of(changes: list) -> str | None:
    """raised, cut, held or mixed, across the guided figures re-read at this report.

    Only figures actually re-read count. One that was not re-read says nothing: the
    scan may have missed it, and "held" claimed from silence would be a reading the
    book never took.
    """
    read = {change["direction"] for change in changes
            if change["direction"] in ("raised", "cut", "held")}
    if not read:
        return None
    if "raised" in read and "cut" in read:
        return "mixed"
    if "raised" in read:
        return "raised"
    if "cut" in read:
        return "cut"
    return "held"


def verdict(surprise_pct, changes: list) -> dict | None:
    """The report in a word, with the direction it points. None when nothing is known.

    Up: a beat that was not followed by a cut, or a raise on a quarter that did not
    miss. Down: the mirror. A beat with a cut, a miss with a raise, and guidance moved
    both ways are mixed, since the two halves of the report disagree and the word
    should not pick one.
    """
    result, guide = result_of(surprise_pct), guidance_of(changes)
    if result is None and guide is None:
        return None
    if guide == "mixed" or (result, guide) in (("beat", "cut"), ("miss", "raised")):
        word, tone = "Mixed", "mixed"
    elif result == "beat":
        word, tone = ("Beat and raise" if guide == "raised" else "Beat"), "up"
    elif result == "miss":
        word, tone = ("Miss and cut" if guide == "cut" else "Miss"), "down"
    elif guide == "raised":
        word, tone = ("In line, raised" if result else "Guidance raised"), "up"
    elif guide == "cut":
        word, tone = ("In line, cut" if result else "Guidance cut"), "down"
    elif result == "in line":
        word, tone = "In line", "flat"
    else:
        word, tone = "Guidance held", "flat"
    return {"word": word, "tone": tone, "result": result, "guidance": guide}


# --- the parts -----------------------------------------------------------------------

def _month(period_end: str) -> str:
    """The month a period closes nearest, as YYYY-MM. A 52 week filer's September
    quarter can end on 1 October, and it is still the September quarter."""
    month, year = financials_view._nearest_month_end(dt.date.fromisoformat(period_end[:10]))
    return f"{year:04d}-{month:02d}"


def _timing(accepted_at: str | None, reported_on: str):
    """Which session a report could first move, and when in the day it landed.

    EDGAR stamps the moment it accepted the filing, in UTC. Before the New York close
    on the report date, that day's close is the first to hold it; after, the next
    session's is. With no stamp the report date is taken and said to be a guess.
    """
    if not accepted_at:
        return reported_on, "time of day not known"
    try:
        moment = dt.datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
    except ValueError:
        return reported_on, "time of day not known"
    local = moment.astimezone(_NEW_YORK)
    if local.date().isoformat() != reported_on:
        # The stamp belongs to a filing made on another day than the announcement.
        return reported_on, "time of day not known"
    if local.time() >= _CLOSE:
        return (local.date() + dt.timedelta(days=1)).isoformat(), "after the close"
    return reported_on, ("before the open" if local.time() < _OPEN else "during the session")


def _closes(conn, company_id: int, start: str, end: str) -> list:
    return [(row["day"], row["close"]) for row in conn.execute(
        """SELECT substr(as_of, 1, 10) AS day, close FROM prices
            WHERE company_id = ? AND interval = '1d' AND close IS NOT NULL
              AND substr(as_of, 1, 10) BETWEEN ? AND ? ORDER BY as_of""",
        (company_id, start, end))]


def day_move(conn, company_id: int, reported_on: str, accepted_at: str | None,
             benchmark: str = None) -> dict | None:
    """The first close that could react to the report against the close before it."""
    benchmark = benchmark or _bench.BENCHMARK
    earliest, timing = _timing(accepted_at, reported_on)
    day = dt.date.fromisoformat(earliest)
    window = _closes(conn, company_id, (day - dt.timedelta(days=10)).isoformat(),
                     (day + dt.timedelta(days=MAX_SESSION_GAP_DAYS)).isoformat())
    before = [bar for bar in window if bar[0] < earliest]
    after = [bar for bar in window if bar[0] >= earliest]
    if not before or not after or not before[-1][1]:
        return None
    (prev_day, prev_close), (session, close) = before[-1], after[0]
    move = close / prev_close - 1
    bench = {row["day"]: row["close"] for row in conn.execute(
        """SELECT substr(as_of, 1, 10) AS day, close FROM benchmark_prices
            WHERE symbol = ? AND substr(as_of, 1, 10) IN (?, ?)""",
        (benchmark, prev_day, session))}
    bench_move = (bench[session] / bench[prev_day] - 1
                  if bench.get(prev_day) and bench.get(session) else None)
    return {"session": session, "previous_session": prev_day, "previous_close": prev_close,
            "close": close, "move": move, "timing": timing, "benchmark": benchmark,
            "benchmark_move": bench_move,
            "abnormal": move - bench_move if bench_move is not None else None}


def guidance_changes(conn, company_id: int, reported_on: str) -> list:
    """Each guided figure at this report against the reading before it."""
    day = dt.date.fromisoformat(reported_on)
    until = (day + dt.timedelta(days=GUIDANCE_WINDOW_DAYS)).isoformat()
    series: dict = {}
    for row in conn.execute(
            """SELECT metric, period, value, low, high, currency, as_of, note
                 FROM consensus_estimates
                WHERE company_id = ? AND source = 'guidance' AND value IS NOT NULL
                ORDER BY as_of""", (company_id,)):
        series.setdefault((row["metric"], row["period"]), []).append(dict(row))
    out = []
    for (metric, period), readings in series.items():
        prior = [r for r in readings if r["as_of"] < reported_on]
        at = [r for r in readings if reported_on <= r["as_of"] <= until]
        if not at and not prior:
            continue
        # A year whose guidance was last read long before this report and never since
        # is a year that has closed, not one left unread.
        if not at and period < f"FY{day.year}":
            continue
        now, before = (at[-1] if at else None), (prior[-1] if prior else None)
        change, direction = None, "not re-read"
        if now and before:
            # A guided growth rate moves in points. Everything else moves in per cent.
            change = (now["value"] - before["value"] if metric == "RevenueGrowth"
                      else now["value"] / before["value"] - 1 if before["value"] else None)
            band = 0.05 if metric == "RevenueGrowth" else HELD_BAND
            direction = ("held" if change is None or abs(change) < band
                         else "raised" if change > 0 else "cut")
        elif now:
            direction = "first reading"
        out.append({"metric": metric, "period": period,
                    "label": f"{period} {_GUIDED.get(metric, metric)}",
                    "value": now["value"] if now else None,
                    "low": now["low"] if now else None, "high": now["high"] if now else None,
                    "as_of": now["as_of"] if now else None,
                    "prior": before["value"] if before else None,
                    "prior_as_of": before["as_of"] if before else None,
                    "currency": (now or before)["currency"], "change": change,
                    "in_points": metric == "RevenueGrowth", "direction": direction,
                    "note": now["note"] if now else None})
    order = list(_GUIDED)
    out.sort(key=lambda g: (g["period"], order.index(g["metric"])
                            if g["metric"] in order else len(order)))
    return out


def book_change(conn, company_id: int, session: str) -> dict:
    """This book's value a share, the last reading before the report and the first after."""
    before = conn.execute(
        """SELECT as_of, equity_per_share FROM valuation_snapshots
            WHERE company_id = ? AND as_of < ? AND equity_per_share IS NOT NULL
            ORDER BY as_of DESC, captured_at DESC LIMIT 1""", (company_id, session)).fetchone()
    after = conn.execute(
        """SELECT as_of, equity_per_share FROM valuation_snapshots
            WHERE company_id = ? AND as_of >= ? AND equity_per_share IS NOT NULL
            ORDER BY as_of, captured_at DESC LIMIT 1""", (company_id, session)).fetchone()
    if not before or not after:
        return {"before": None, "after": None, "change": None,
                "reason": ("no valuation was stored before this report" if not before
                           else "no valuation has been stored since this report")}
    return {"before": {"as_of": before["as_of"], "value": before["equity_per_share"]},
            "after": {"as_of": after["as_of"], "value": after["equity_per_share"]},
            "change": (after["equity_per_share"] / before["equity_per_share"] - 1
                       if before["equity_per_share"] else None), "reason": None}


def drivers(conn, company_id: int, period_end: str) -> list:
    """The quarter's product revenue, largest first, against the same quarter a year on."""
    month = _month(period_end)
    rows = conn.execute(
        """SELECT a.id, COALESCE(a.brand_name, a.generic_name) AS name, r.fiscal_year,
                  r.period, r.value, r.period_end
             FROM asset_revenue r JOIN assets a ON a.id = r.asset_id
            WHERE a.owner_company_id = ? AND r.period LIKE 'Q%' AND r.value IS NOT NULL""",
        (company_id,)).fetchall()
    now = [r for r in rows if r["period_end"] and _month(r["period_end"]) == month]
    year_ago = {(r["id"], r["period"], r["fiscal_year"]): r["value"] for r in rows}
    out = []
    for r in sorted(now, key=lambda r: -r["value"])[:DRIVER_ROWS]:
        prior = year_ago.get((r["id"], r["period"], r["fiscal_year"] - 1))
        out.append({"name": r["name"], "value": r["value"], "prior": prior,
                    "change": r["value"] / prior - 1 if prior else None,
                    "delta": r["value"] - prior if prior is not None else None})
    return out


def _results_filing(conn, company_id: int, reported_on: str | None) -> dict | None:
    """The filing the report was made in: the results 8-K, or a 6-K of the same day."""
    if reported_on:
        rows = conn.execute(
            """SELECT form_type, filed_date, accepted_at, title, url FROM filings
                WHERE company_id = ? AND filed_date = ?
                  AND (title LIKE '%esults of operations%' OR form_type = '6-K')
                ORDER BY (title LIKE '%esults of operations%') DESC, accepted_at""",
            (company_id, reported_on)).fetchall()
    else:
        rows = conn.execute(
            """SELECT form_type, filed_date, accepted_at, title, url FROM filings
                WHERE company_id = ? AND title LIKE '%esults of operations%'
                ORDER BY filed_date DESC LIMIT 1""", (company_id,)).fetchall()
    return dict(rows[0]) if rows else None


def _sentence(result, surprise, snapshot, matches, changes, day) -> list:
    """The reading as short sentences, each from one figure. Built, not written."""
    parts = []
    if result == "in line":
        parts.append("EPS was in line with the street.")
    elif result:
        parts.append(f"EPS {'beat' if result == 'beat' else 'missed'} the street by "
                     f"{abs(surprise):.0f}%.")
    growth = (snapshot or {}).get("revenue_growth") if matches else None
    if growth is not None:
        parts.append(f"Revenue {'grew' if growth >= 0 else 'fell'} "
                     f"{abs(growth) * 100:.1f}% on a year.")
    for change in changes:
        if change["direction"] not in ("raised", "cut", "held"):
            continue
        subject = f"{change['label']} guidance"
        if change["direction"] == "held":
            parts.append(f"{subject} was held.")
            continue
        size = (f"{abs(change['change']):.1f} points" if change["in_points"]
                else f"{abs(change['change']) * 100:.1f}%")
        parts.append(f"{subject} {'went up' if change['direction'] == 'raised' else 'was cut'} "
                     f"{size}.")
    if day:
        parts.append(f"The shares {'rose' if day['move'] >= 0 else 'fell'} "
                     f"{abs(day['move']) * 100:.1f}% on the day.")
    return parts


def build(db_path=None, ticker: str = "") -> dict | None:
    """The latest report for one company, or None when the ticker is unknown."""
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id, ticker FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
        if not company:
            return None
        company_id = company["id"]
        statements = financials_view.build_statements(db_path, ticker, limit=1) or {}
        snapshot = statements.get("snapshot")
        surprises = [dict(r) for r in conn.execute(
            """SELECT quarter_end, reported_on, eps, consensus_eps, surprise_pct
                 FROM earnings_surprises WHERE company_id = ?
                ORDER BY quarter_end DESC LIMIT ?""", (company_id, HISTORY_QUARTERS))]
        latest = surprises[0] if surprises else None
        reported_on = latest["reported_on"] if latest else None
        filing = _results_filing(conn, company_id, reported_on)
        if reported_on is None and filing:
            reported_on = filing["filed_date"]
        if reported_on is None:
            return {"ticker": company["ticker"], "report": None,
                    "reason": "no results announcement is on file for this company"}

        quarter = latest["quarter_end"] if latest else (
            _month(snapshot["period_end"]) if snapshot else None)
        # The filed figures are this report's only when they are for its quarter. A
        # 20-F filer tags no quarters, so its latest filed period is a year and the
        # report is a quarter the book cannot read.
        matches = bool(snapshot and quarter and _month(snapshot["period_end"]) == quarter)
        accepted_at = (filing or {}).get("accepted_at")
        day = day_move(conn, company_id, reported_on, accepted_at)
        changes = guidance_changes(conn, company_id, reported_on)
        surprise = latest["surprise_pct"] if latest else None
        call = verdict(surprise, changes)
        history = []
        for row in surprises:
            past = (_results_filing(conn, company_id, row["reported_on"])
                    if row["reported_on"] else None)
            moved = (day_move(conn, company_id, row["reported_on"],
                              (past or {}).get("accepted_at"))
                     if row["reported_on"] else None)
            history.append(dict(row, result=result_of(row["surprise_pct"]),
                                move=moved["move"] if moved else None))
        return {
            "ticker": company["ticker"],
            "report": {"reported_on": reported_on, "quarter_end": quarter,
                       "label": snapshot["label"] if matches else None,
                       "filing": filing},
            "filed": snapshot, "filed_matches": matches,
            "street": (dict(latest, result=result_of(surprise),
                            basis="EPS as the street counts it, per US-listed share")
                       if latest else None),
            "guidance": changes,
            "day": day,
            "book": book_change(conn, company_id, day["session"] if day else reported_on),
            "drivers": (drivers(conn, company_id, snapshot["period_end"])
                        if matches else []),
            "history": history,
            "verdict": call,
            "sentence": _sentence((call or {}).get("result"), surprise, snapshot, matches,
                                  changes, day),
            "rules": {"in_line_band_pct": IN_LINE_BAND},
        }
    finally:
        conn.close()
