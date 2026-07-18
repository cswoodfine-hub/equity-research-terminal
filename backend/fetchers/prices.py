"""Prices fetcher: daily close history and the latest quote from Yahoo's chart JSON.

Endpoint (unofficial, verified working): query1.finance.yahoo.com/v8/finance/chart.
Market cap is not carried by this endpoint, so it is stored null this phase and shown
as "no free data" in the UI, per the no-fabrication rule.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "prices"
INTRADAY_SOURCE = "prices_intraday"
YAHOO_SOURCE = "yahoo_chart"
TTL_SECONDS = 15 * 60

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
# Five years of daily closes, about 1,250 sessions per company. The chart offers
# timeframes up to 5Y and cannot show history that was never fetched. Cost is one
# request either way, since Yahoo returns the whole range in a single response, and
# the upsert is keyed on (company_id, as_of) so a wider pull backfills rather than
# duplicates.
CHART_RANGE = "5y"
CHART_INTERVAL = "1d"
# Yahoo serves this endpoint anonymously with a browser-like User-Agent.
_USER_AGENT = "Mozilla/5.0 (compatible; NovatalisResearch/0.1)"
_TIMEOUT_S = 30


def parse_chart(payload: dict, ticker: str, interval: str = "1d") -> tuple[list[dict], dict]:
    """Turn a Yahoo chart payload into price rows plus quote meta. Pure.

    Rows are one per bar with a non-null close; bars with a null close (holidays,
    gaps, pre-open) are dropped rather than filled. Raises ValueError if Yahoo
    reports an error or returns no result.

    Intraday bars keep their time. Stamping them with a bare date would collapse a
    day of 15 minute bars onto one key, and the unique constraint would silently keep
    only the last of them.
    """
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise ValueError(f"yahoo chart error for {ticker}: {chart['error']}")
    results = chart.get("result")
    if not results:
        raise ValueError(f"yahoo chart returned no result for {ticker}")

    result = results[0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    volumes = quote.get("volume") or []
    offset = int(meta.get("gmtoffset") or 0)

    def at(seq, i):
        return seq[i] if i < len(seq) else None

    rows: list[dict] = []
    for i, ts in enumerate(timestamps):
        close = at(closes, i)
        if close is None:  # never fabricate a missing close
            continue
        stamp = dt.datetime.utcfromtimestamp(ts + offset)
        as_of = stamp.strftime("%Y-%m-%d" if interval == "1d" else "%Y-%m-%d %H:%M")
        vol = at(volumes, i)
        rows.append(
            {
                "ticker": ticker,
                "as_of": as_of,
                "interval": interval,
                "close": float(close),
                "open": float(at(opens, i)) if at(opens, i) is not None else None,
                "high": float(at(highs, i)) if at(highs, i) is not None else None,
                "low": float(at(lows, i)) if at(lows, i) is not None else None,
                "volume": int(vol) if vol is not None else None,
            }
        )

    meta_out = {
        "currency": meta.get("currency"),
        "regular_market_price": meta.get("regularMarketPrice"),
    }
    return rows, meta_out


class PricesFetcher(BaseFetcher):
    source = SOURCE
    ttl_seconds = TTL_SECONDS
    chart_range = CHART_RANGE
    chart_interval = CHART_INTERVAL

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()
        self._meta: dict = {}

    @property
    def entity_key(self) -> str:
        return self.ticker

    def _yahoo_symbol(self) -> str:
        """The tradable US symbol to quote: the US ADR ticker if set, else the ticker.

        Foreign names must be quoted by their US ADR (ROG -> RHHBY Roche, BAYN -> BAYRY
        Bayer), not their home-exchange ticker, which either 404s or, worse, resolves to
        an unrelated US company (bare ROG is Rogers Corporation)."""
        conn = db.get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT us_adr_ticker FROM companies WHERE ticker = ?", (self.ticker,)
            ).fetchone()
        finally:
            conn.close()
        adr = (row["us_adr_ticker"] or "").strip() if row else ""
        return adr or self.ticker

    def fetch(self) -> dict:
        symbol = self._yahoo_symbol()
        query = urllib.parse.urlencode({"range": self.chart_range,
                                        "interval": self.chart_interval})
        url = f"{CHART_URL.format(ticker=urllib.parse.quote(symbol))}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def normalise(self, raw) -> list[dict]:
        rows, self._meta = parse_chart(raw, self.ticker, self.chart_interval)
        return rows

    # --- snapshots --------------------------------------------------------
    def _company_id(self, conn) -> int | None:
        row = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (self.ticker,)
        ).fetchone()
        return row[0] if row else None

    def _write_snapshot(self, conn, payload: dict) -> None:
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload, refresh_run_id)
            VALUES (?, 'company', ?, ?, ?)
            """,
            (self.source, self.ticker, json.dumps(payload), self.refresh_run_id),
        )

    def snapshot(self, rows: list[dict]) -> None:
        if not rows:
            return
        latest = rows[-1]
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(
                conn,
                {
                    "ticker": self.ticker,
                    "as_of": latest["as_of"],
                    "close": latest["close"],
                    "market_cap": None,
                    "currency": self._meta.get("currency"),
                    "source": YAHOO_SOURCE,
                    "fetch_kind": "live",
                },
            )
            conn.commit()
        finally:
            conn.close()

    def _snapshot_cache(self) -> None:
        """Snapshot the current latest price without fetching, for gap-free history."""
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return
            row = conn.execute(
                """
                SELECT as_of, close, market_cap FROM prices
                 WHERE company_id = ? AND interval = ?
                 ORDER BY as_of DESC LIMIT 1
                """,
                (company_id, self.chart_interval),
            ).fetchone()
            if row is None:  # nothing known yet, nothing to carry forward
                return
            # No fetch happened, so carry the last known currency forward rather than
            # writing null (which would blank the price label and the comps currency).
            prior = conn.execute(
                """
                SELECT payload FROM snapshots
                 WHERE source = 'prices' AND entity_key = ?
                   AND json_extract(payload, '$.currency') IS NOT NULL
                 ORDER BY captured_at DESC LIMIT 1
                """,
                (self.ticker,),
            ).fetchone()
            currency = json.loads(prior["payload"])["currency"] if prior else None
            self._write_snapshot(
                conn,
                {
                    "ticker": self.ticker,
                    "as_of": row["as_of"],
                    "close": row["close"],
                    "market_cap": row["market_cap"],
                    "currency": currency,
                    "source": YAHOO_SOURCE,
                    "fetch_kind": "cache",
                },
            )
            conn.commit()
        finally:
            conn.close()

    # --- current-state table ---------------------------------------------
    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            company_id = self._company_id(conn)
            if company_id is None:
                return RefreshResult(
                    self.source, 0, [f"unknown ticker {self.ticker}"], False, 0
                )
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO prices
                        (company_id, as_of, close, open, high, low, volume, source,
                         interval)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(company_id, as_of) DO UPDATE SET
                        close=excluded.close, open=excluded.open, high=excluded.high,
                        low=excluded.low, volume=excluded.volume, source=excluded.source,
                        interval=excluded.interval
                    """,
                    (
                        company_id,
                        row["as_of"],
                        row["close"],
                        row["open"],
                        row["high"],
                        row["low"],
                        row["volume"],
                        YAHOO_SOURCE,
                        row.get("interval", self.chart_interval),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(self.source, len(rows), [], False, 0)


class IntradayPricesFetcher(PricesFetcher):
    """Fifteen minute bars over the last five sessions, for the briefing sparkline.

    Yahoo caps intraday history, so this is a rolling window rather than a record: old
    bars fall out of range and stop being refreshed.

    It carries its own source name, which is not cosmetic. The TTL is tracked per
    (source, entity_key), so sharing "prices" with the daily fetcher would give the two
    a single slot: whichever ran first would mark it fresh and the other would be
    skipped as within TTL, every time.
    """

    source = INTRADAY_SOURCE
    chart_range = "5d"
    chart_interval = "15m"
