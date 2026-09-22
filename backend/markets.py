"""The standing market level, read out of what the refresh already stores.

Three sources feed the discount rate and the reported top line, and until now every
one of them was write-mostly. ``market_rates`` holds four FRED series with one reader,
``forecast_view`` asking for expected inflation. ``fx_rates`` holds the ECB set with
one reader, the universe revenue view. ``benchmark_prices`` holds ten years of the S&P
500 and of XLV, refreshed daily by ``fetchers/benchmarks.py``. This assembles the three into one
payload so a reader can see the level a valuation was struck against, and see which
day each part of it was published on.

Two rules run through it.

A date per cell, never a date per strip. The indexed Treasury series lags two days,
the ECB publishes on TARGET days and the S&P on NYSE days, so any single date over the
lot would be wrong for most of them. Every cell carries its own ``as_of``.

A change is refused rather than guessed. A window with fewer than two observations of
a series gets ``change: None`` and a reason, because one point is a level and not a
move, and a gap is a day the source suppressed rather than a day the number held.
"""

from __future__ import annotations

import db
import fx
from fetchers import rates_fred

# The order the strip reads in: the risk-free rate first, because it is the one the
# whole book discounts at, then what it decomposes into, then the cost of debt.
RATE_SERIES = ("DGS10", "DFII10", "T10YIE", "BAMLC0A3CAEY")

# Read internally to set a discount rate, and shown with its owner named. ICE does not
# licence redistribution through FRED, so this level is displayed and never exported.
RESTRICTED = {"BAMLC0A3CAEY": "ICE Data Indices, LLC"}

# The window a change is measured over. Rates are kept for KEEP_DAYS, so asking for
# more than that buys a shorter answer with a longer label.
DEFAULT_DAYS = 90


def _window_start(days: int, newest: str | None) -> str | None:
    """The first date of the window, counted back from the newest observation.

    Counted from the data rather than from today, so a run on a Monday reports the
    same window as the Friday refresh that filled it.
    """
    if not newest:
        return None
    import datetime as dt

    try:
        end = dt.date.fromisoformat(newest[:10])
    except ValueError:
        return None
    return (end - dt.timedelta(days=days)).isoformat()


# FRED publishes these series to two decimals of a percent, so a difference of two
# of them is exact to a basis point. Rounding past that only removes the noise binary
# floating point adds, which is why a 36bp move was arriving as 35.99999999999992.
_BP_DP, _PCT_DP = 2, 8


def _move(points: list[dict], field: str) -> tuple:
    """(first, last, reason). A window under two observations yields no move."""
    if len(points) < 2:
        return None, None, "one observation in the window"
    return points[0][field], points[-1][field], None


def rates(db_path=None, days: int = DEFAULT_DAYS, conn=None) -> list[dict]:
    """The four series a discount rate is built from, newest value and the move."""
    out = []
    newest = rates_fred.latest(db_path, conn=conn)
    for series in RATE_SERIES:
        now = newest.get(series) or {}
        cell = {"series": series,
                "description": rates_fred.SERIES.get(series, ""),
                "value": now.get("value"),
                "as_of": now.get("as_of"),
                "change_bp": None,
                "change_from": None,
                "no_change_reason": None,
                "restricted_to": RESTRICTED.get(series)}
        if now.get("as_of"):
            since = _window_start(days, now["as_of"])
            points = rates_fred.history(db_path, series, since, conn=conn)
            first, last, reason = _move(points, "value")
            if reason:
                cell["no_change_reason"] = reason
            else:
                cell["change_bp"] = round((last - first) * 10_000.0, _BP_DP)
                cell["change_from"] = points[0]["as_of"]
        else:
            cell["no_change_reason"] = "series not fetched"
        out.append(cell)
    return out


def reporting_currencies(db_path=None, conn=None) -> list[str]:
    """The non-USD currencies the covered companies report in, alphabetical.

    Read from the universe rather than listed here, so a company added to the seed
    brings its currency onto the strip without a second edit.
    """
    own = conn is None
    c = db.get_connection(db_path) if own else conn
    try:
        rows = c.execute(
            "SELECT DISTINCT reporting_currency FROM companies"
            " WHERE reporting_currency IS NOT NULL"
            "   AND reporting_currency <> 'USD' ORDER BY reporting_currency").fetchall()
    finally:
        if own:
            c.close()
    return [r[0] for r in rows]


def crosses(db_path=None, days: int = DEFAULT_DAYS, conn=None) -> list[dict]:
    """USD per one unit of each reporting currency, and the move over the window.

    A percentage rather than basis points: the strip is answering how much a krone of
    Novo's revenue is worth in dollars today against the window, which is a ratio.
    """
    out = []
    for base in reporting_currencies(db_path, conn=conn):
        points = fx.history(db_path, base, conn=conn)
        cell = {"base": base, "quote": "USD", "rate": None, "as_of": None,
                "change_pct": None, "change_from": None, "no_change_reason": None}
        if not points:
            cell["no_change_reason"] = "no rate stored"
            out.append(cell)
            continue
        cell["rate"], cell["as_of"] = points[-1]["rate"], points[-1]["as_of"]
        since = _window_start(days, points[-1]["as_of"])
        window = [p for p in points if not since or p["as_of"] >= since]
        first, last, reason = _move(window, "rate")
        if reason:
            cell["no_change_reason"] = reason
        else:
            cell["change_pct"] = round(last / first - 1.0, _PCT_DP) if first else None
            cell["change_from"] = window[0]["as_of"]
        out.append(cell)
    return out


def benchmarks(db_path=None, days: int = DEFAULT_DAYS, conn=None) -> list[dict]:
    """Whatever index closes are stored, newest close and the move over the window.

    The date rides on the cell because the calendars differ: the ECB keeps TARGET days
    and the exchanges keep their own, so a benchmark and a rate beside it are rarely
    dated the same day. It used to be worse. This table was filled once by ``beta`` and
    was in no refresh, so its newest close sat weeks behind everything around it;
    ``fetchers/benchmarks.py`` now refreshes it daily.
    """
    own = conn is None
    c = db.get_connection(db_path) if own else conn
    try:
        symbols = [r[0] for r in c.execute(
            "SELECT DISTINCT symbol FROM benchmark_prices ORDER BY symbol")]
        out = []
        for symbol in symbols:
            rows = [dict(r) for r in c.execute(
                "SELECT as_of, close FROM benchmark_prices WHERE symbol = ?"
                " ORDER BY as_of", (symbol,))]
            cell = {"symbol": symbol, "close": None, "as_of": None,
                    "change_pct": None, "change_from": None,
                    "no_change_reason": None}
            if not rows:
                cell["no_change_reason"] = "no closes stored"
                out.append(cell)
                continue
            cell["close"], cell["as_of"] = rows[-1]["close"], rows[-1]["as_of"]
            since = _window_start(days, rows[-1]["as_of"])
            window = [r for r in rows if not since or r["as_of"] >= since]
            first, last, reason = _move(window, "close")
            if reason:
                cell["no_change_reason"] = reason
            else:
                cell["change_pct"] = (round(last / first - 1.0, _PCT_DP)
                                      if first else None)
                cell["change_from"] = window[0]["as_of"]
            out.append(cell)
    finally:
        if own:
            c.close()
    return out


def build(db_path=None, days: int = DEFAULT_DAYS) -> dict:
    """The whole strip. One connection, lent to every reader.

    Lending matters: opening SQLite is 88% of the cost of a cached rate read, and this
    payload makes about a dozen of them.
    """
    days = max(5, min(int(days or DEFAULT_DAYS), rates_fred.KEEP_DAYS))
    conn = db.get_connection(db_path)
    try:
        return {"days": days,
                "rates": rates(db_path, days, conn=conn),
                "fx": crosses(db_path, days, conn=conn),
                "benchmarks": benchmarks(db_path, days, conn=conn)}
    finally:
        conn.close()
