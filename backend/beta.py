"""Beta against the market, computed rather than remembered.

Every seeded beta here says "computed from 261 weekly returns vs S&P 500, Blume-adjusted"
and none could be reproduced, because the index series was never stored. So a company
with a beta had a number nobody could check, and a company without one could not be
forecast at all: AbbVie, Pfizer and Bristol Myers were blocked on a single input that
no filing carries.

Weekly returns over five years is the conventional window and the one the existing
figures were taken on. Weekly rather than daily because daily returns of a large-cap
against an index are dominated by non-synchronous noise; five years rather than two
because a two-year window put Johnson & Johnson at -0.03, which is a real measurement of
nothing anyone would discount a cash flow at.

Blume-adjusted, which is 2/3 of the raw beta plus 1/3 of one. A raw beta is an estimate
with a standard error, and it is known to revert toward the market; the adjustment is the
standard correction and it is what the figures already on file carry.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

import db

SYMBOL = "^GSPC"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NovatalisResearch/0.1)"}
WEEKS = 261                      # five years of weekly observations
BLUME_RAW, BLUME_MARKET = 2.0 / 3.0, 1.0 / 3.0
_TIMEOUT_S = 30


def fetch(symbol: str = SYMBOL, chart_range: str = "10y") -> list[dict]:
    """Daily closes for the index, as [{as_of, close}]."""
    url = (CHART_URL.format(ticker=urllib.parse.quote(symbol))
           + f"?range={chart_range}&interval=1d")
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        payload = json.load(response)
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        raise ValueError(f"no chart data for {symbol}")
    stamps = result[0].get("timestamp") or []
    closes = (((result[0].get("indicators") or {}).get("quote") or [{}])[0]
              .get("close") or [])
    return [{"as_of": dt.datetime.utcfromtimestamp(t).date().isoformat(), "close": c}
            for t, c in zip(stamps, closes) if c is not None]


def store(rows: list[dict], symbol: str = SYMBOL, db_path=None) -> int:
    conn = db.get_connection(db_path)
    try:
        for row in rows:
            conn.execute(
                "INSERT INTO benchmark_prices (symbol, as_of, close) VALUES (?, ?, ?)"
                " ON CONFLICT(symbol, as_of) DO UPDATE SET close = excluded.close",
                (symbol, row["as_of"], row["close"]))
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def _weekly(series: dict) -> dict:
    """The last close of each ISO week, keyed by (year, week)."""
    out: dict = {}
    for as_of in sorted(series):
        year, week, _ = dt.date.fromisoformat(as_of).isocalendar()
        out[(year, week)] = series[as_of]
    return out


def _returns(weekly: dict, weeks: list) -> list:
    return [weekly[b] / weekly[a] - 1.0 for a, b in zip(weeks, weeks[1:])
            if weekly.get(a) and weekly.get(b)]


def compute(conn, ticker: str, symbol: str = SYMBOL, weeks: int = WEEKS):
    """(beta, basis) for one ticker, or (None, None) where there is not enough history.

    Raw beta is the covariance of the two weekly return series over the variance of the
    market's, on the weeks both traded, then Blume-adjusted.
    """
    stock = {r["as_of"]: r["close"] for r in conn.execute(
        """SELECT p.as_of, p.close FROM prices p JOIN companies c ON c.id = p.company_id
            WHERE c.ticker = ? AND p.interval = '1d' AND p.close IS NOT NULL""",
        (ticker,))}
    market = {r["as_of"]: r["close"] for r in conn.execute(
        "SELECT as_of, close FROM benchmark_prices WHERE symbol = ?", (symbol,))}
    if not stock or not market:
        return None, None
    stock_w, market_w = _weekly(stock), _weekly(market)
    shared = sorted(set(stock_w) & set(market_w))[-(weeks + 1):]
    if len(shared) < 60:
        return None, None
    xs, ys = _returns(market_w, shared), _returns(stock_w, shared)
    n = min(len(xs), len(ys))
    xs, ys = xs[:n], ys[:n]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    var = sum((x - mean_x) ** 2 for x in xs)
    if var <= 0:
        return None, None
    raw = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / var
    adjusted = BLUME_RAW * raw + BLUME_MARKET
    start, end = shared[0], shared[-1]
    basis = (f"computed from {n} weekly returns vs S&P 500, "
             f"{start[0]}-W{start[1]:02d} to {end[0]}-W{end[1]:02d}, "
             f"Blume-adjusted ({raw:.2f} raw)")
    return round(adjusted, 2), basis
