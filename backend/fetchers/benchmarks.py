"""Index and sector closes, so a beta is regressed against a series that is current.

``benchmark_prices`` held 2,513 rows of the S&P written once by ``beta.py`` as a one-off
and never refreshed, ending 2026-09-02 while company prices ran to 2026-09-21. A beta
regressed against that pairs three weeks of company returns with nothing, and the stale
end quietly biases every discount rate built on it.

Two series, and the second is the point of storing an adjusted close. XLV's close ten
years ago was 73.34 against an adjusted close of 62.04, an 18.2% gap, which is the
dividend stream the sector has paid since. The index has the two identical at 2177.18,
because an index pays nothing. Both columns are stored and a caller compares like with
like: a relative figure on closes would charge the whole of the sector's dividends to
the sector as underperformance.

Nothing here goes in ``prices``. Its ``company_id`` is NOT NULL, and migration 048 says
what a pseudo-company row would do to the treemap, the comps table and the coverage
counts.

Licence position. Yahoo's terms do not permit automated collection, so this series is an
internal input to a computed beta and a relative figure. It is never exported and never
shown as a price. When the endpoint breaks, a stored beta stays in use and a fresh one
is not invented: the fetcher reports a soft error and the valuation is unchanged.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "benchmark"
ENTITY_KEY = "benchmarks"
# A day. The book is valued on closes, so a fifteen-minute window would buy nothing and
# multiply exposure to the one unofficial endpoint in this feature.
TTL_SECONDS = 24 * 60 * 60

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
CHART_RANGE = "10y"
CHART_INTERVAL = "1d"
# query1, which prices.py and beta.py already point at, and this exact string. A bare
# request and a full browser string both draw 429s from this endpoint; the repo's own
# string does not. Defined here rather than imported, because a fetcher does not import
# another fetcher.
_USER_AGENT = "Mozilla/5.0 (compatible; NovatalisResearch/0.1)"
_TIMEOUT_S = 30

# What each series is for, so a reader knows why it is stored rather than guessing.
SYMBOLS = {
    "^GSPC": "S&P 500, the market a beta is measured against",
    "XLV": "Health Care Select Sector SPDR, the sector a pharma book is read against",
}


def parse_chart(payload: dict, symbol: str) -> list[dict]:
    """[{symbol, as_of, close, adjclose}] from a Yahoo chart payload. Pure.

    A bar with a null close is dropped rather than carried forward: a holiday is a day
    the market did not trade, and filling it would put a return of nil into a
    regression that should not see that week at all.

    ``adjclose`` is absent for an index and present for an ETF. Where it is missing it
    is stored as the close, which for an index is not an assumption: the two are the
    same number because nothing was paid out.
    """
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"yahoo chart error for {symbol}: {chart['error']}")
    results = chart.get("result")
    if not results:
        raise ValueError(f"yahoo chart returned no result for {symbol}")
    result = results[0]
    stamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    closes = ((indicators.get("quote") or [{}])[0].get("close")) or []
    adjusted = ((indicators.get("adjclose") or [{}])[0].get("adjclose")) or []

    rows = []
    for i, stamp in enumerate(stamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        adj = adjusted[i] if i < len(adjusted) else None
        rows.append({"symbol": symbol,
                     "as_of": dt.datetime.utcfromtimestamp(stamp).date().isoformat(),
                     "close": close,
                     "adjclose": adj if adj is not None else close})
    return rows


class BenchmarksFetcher(BaseFetcher):
    """The index and sector closes a beta and a relative figure are read against."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return ENTITY_KEY

    def fetch(self) -> dict:
        out: dict = {}
        self._soft: list[str] = []
        for symbol in SYMBOLS:
            url = (CHART_URL.format(symbol=urllib.parse.quote(symbol))
                   + f"?range={CHART_RANGE}&interval={CHART_INTERVAL}")
            request = urllib.request.Request(
                url, headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
                    out[symbol] = json.load(response)
            except urllib.error.HTTPError as exc:
                # A rate limit is the expected failure on an unofficial endpoint. One
                # symbol failing must not lose the other, and neither must stop the
                # refresh: a stale benchmark is better than no benchmark, and a beta
                # built on it is refused rather than guessed.
                self._soft.append(f"{symbol}: HTTP {exc.code}")
            except (urllib.error.URLError, OSError, ValueError) as exc:
                self._soft.append(f"{symbol}: {type(exc).__name__}")
        return out

    def normalise(self, raw: dict) -> list[dict]:
        rows = []
        for symbol, payload in (raw or {}).items():
            try:
                rows += parse_chart(payload, symbol)
            except ValueError as exc:
                self._soft.append(str(exc))
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        newest: dict = {}
        for row in rows:
            if row["as_of"] > newest.get(row["symbol"], {"as_of": ""})["as_of"]:
                newest[row["symbol"]] = row
        self._write({s: {"as_of": r["as_of"], "close": r["close"],
                         "adjclose": r["adjclose"]}
                     for s, r in newest.items()}, "live")

    def _snapshot_cache(self) -> None:
        """What is stored, when the endpoint refused. The history keeps no gap and the
        snapshot does not claim a fetch that did not happen."""
        self._write(latest(self.db_path), "cache")

    def _write(self, symbols: dict, fetch_kind: str) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'market', ?, ?, ?)",
                (SOURCE, ENTITY_KEY,
                 json.dumps({"symbols": symbols, "fetch_kind": fetch_kind}),
                 self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                conn.execute(
                    """INSERT INTO benchmark_prices (symbol, as_of, close, adjclose,
                                                     source)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(symbol, as_of) DO UPDATE SET
                           close = excluded.close,
                           adjclose = excluded.adjclose,
                           fetched_at = datetime('now')""",
                    (row["symbol"], row["as_of"], row["close"], row["adjclose"],
                     "yahoo_chart"))
                written += 1
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(SOURCE, written, errors=list(getattr(self, "_soft", [])),
                             notes=[f"{written} benchmark closes"])


def latest(db_path=None) -> dict:
    """{symbol: {as_of, close, adjclose}} at the newest stored bar of each."""
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT symbol, as_of, close, adjclose FROM benchmark_prices b
                WHERE as_of = (SELECT MAX(as_of) FROM benchmark_prices
                                WHERE symbol = b.symbol)""").fetchall()
    finally:
        conn.close()
    return {r["symbol"]: {"as_of": r["as_of"], "close": r["close"],
                          "adjclose": r["adjclose"]} for r in rows}


def history(db_path, symbol: str, since: str | None = None, conn=None) -> list[dict]:
    """[{as_of, close, adjclose}] for one symbol, oldest first.

    Days the market did not trade are absent rather than carried, so a caller reading a
    company against a benchmark must intersect the dates before it compares them.
    """
    sql = ("SELECT as_of, close, adjclose FROM benchmark_prices WHERE symbol = ?")
    args: list = [symbol]
    if since:
        sql += " AND as_of >= ?"
        args.append(since[:10])
    own = conn is None
    c = db.get_connection(db_path) if own else conn
    try:
        rows = c.execute(sql + " ORDER BY as_of", args).fetchall()
    finally:
        if own:
            c.close()
    return [{"as_of": r["as_of"], "close": r["close"], "adjclose": r["adjclose"]}
            for r in rows]
