"""Street consensus from Nasdaq's analyst pages: annual EPS and the price target.

FMP's estimates need a key this checkout does not have, and Yahoo now refuses its
estimate modules without a session it rate-limits. Nasdaq's site reads its analyst
pages from a JSON endpoint that answers without a key or a cookie: the consensus EPS for
each fiscal year with its high, low and number of estimates, and the consensus price
target with its low, high and the buy, hold and sell count. It carries no revenue
consensus, so the street's revenue stays empty rather than being backed out of EPS.

The endpoint is unofficial, like the Yahoo chart the price fetcher reads. It can change
or refuse without notice, so a failure is a soft, reported error, never a crash. Figures
are per share of the US listing, the ADR where the company has one, in dollars.

Revisions are kept the way the FMP fetcher keeps them: a row is written only when a
figure differs from the newest one stored, dated the day it was read.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "consensus_nasdaq"
TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_S = 30
BASE_URL = "https://api.nasdaq.com/api/analyst/{symbol}/{kind}"
# The endpoint answers a browser's request and not a bare one.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def fiscal_period(fiscal_end: str) -> str | None:
    """'Dec 2026' -> 'FY2026'. A year ending before July is labelled by the year before,
    the way the financials table labels a fiscal year."""
    parts = (fiscal_end or "").split()
    if len(parts) != 2 or parts[0][:3] not in _MONTHS or not parts[1].isdigit():
        return None
    year = int(parts[1])
    return f"FY{year if _MONTHS[parts[0][:3]] >= 7 else year - 1}"


def _get(symbol: str, kind: str) -> dict:
    request = urllib.request.Request(BASE_URL.format(symbol=symbol, kind=kind),
                                     headers=HEADERS)
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse(company_id: int, forecast: dict | None, target: dict | None) -> list[dict]:
    """Table rows from the two payloads. Pure. A missing figure is no row, never a zero."""
    rows = []
    yearly = (((forecast or {}).get("data") or {}).get("yearlyForecast") or {}).get("rows")
    for record in yearly or []:
        period = fiscal_period(record.get("fiscalEnd"))
        value = record.get("consensusEPSForecast")
        if period is None or value is None:
            continue
        count = record.get("noOfEstimates")
        rows.append({"company_id": company_id, "metric": "EPS", "period": period,
                     "value": float(value), "low": record.get("lowEPSForecast"),
                     "high": record.get("highEPSForecast"), "currency": "USD",
                     "note": (f"{count} estimates, per US-listed share" if count
                              else "per US-listed share")})
    overview = ((target or {}).get("data") or {}).get("consensusOverview") or {}
    if overview.get("priceTarget") is not None:
        ratings = ", ".join(f"{overview[k]} {k}" for k in ("buy", "hold", "sell")
                            if overview.get(k) is not None)
        rows.append({"company_id": company_id, "metric": "PriceTarget", "period": "12M",
                     "value": float(overview["priceTarget"]),
                     "low": overview.get("lowPriceTarget"),
                     "high": overview.get("highPriceTarget"), "currency": "USD",
                     "note": (f"{ratings}; " if ratings else "") + "per US-listed share"})
    return rows


class ConsensusNasdaqFetcher(BaseFetcher):
    """One symbol's annual EPS consensus and price target, revisions kept."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            company = conn.execute(
                "SELECT id, ticker, us_adr_ticker FROM companies WHERE ticker = ?",
                (self.ticker,)).fetchone()
        finally:
            conn.close()
        if not company:
            raise ValueError(f"no company {self.ticker}")
        symbol = company["us_adr_ticker"] or company["ticker"]
        return {"company": dict(company), "forecast": _get(symbol, "earnings-forecast"),
                "target": _get(symbol, "targetprice")}

    def normalise(self, raw) -> list[dict]:
        return parse(raw["company"]["id"], raw.get("forecast"), raw.get("target"))

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"estimates": len(rows), "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                """SELECT COUNT(*) FROM consensus_estimates e
                     JOIN companies c ON c.id = e.company_id
                    WHERE c.ticker = ? AND e.source = 'nasdaq'""",
                (self.ticker,)).fetchone()[0]
        finally:
            conn.close()
        self._write_snapshot({"estimates": n, "fetch_kind": "cache"})

    def _write_snapshot(self, payload) -> None:
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'company', ?, ?, ?)",
                (SOURCE, self.entity_key, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        today = dt.date.today().isoformat()
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                current = conn.execute(
                    """SELECT value, low, high FROM consensus_estimates
                        WHERE company_id = ? AND metric = ? AND period = ?
                          AND source = 'nasdaq'
                        ORDER BY as_of DESC LIMIT 1""",
                    (row["company_id"], row["metric"], row["period"])).fetchone()
                if current is not None and (current["value"], current["low"],
                                            current["high"]) == (row["value"], row["low"],
                                                                 row["high"]):
                    continue
                # The table's key has no source in it, so a figure another source wrote
                # for the same metric, period and day is left alone rather than replaced.
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO consensus_estimates
                           (company_id, metric, period, value, low, high, currency,
                            source, as_of, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'nasdaq', ?, ?)""",
                    (row["company_id"], row["metric"], row["period"], row["value"],
                     row["low"], row["high"], row["currency"], today, row["note"]))
                written += cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        notes = [f"{self.ticker}: {written} estimate revisions"] if written else []
        return RefreshResult(SOURCE, written, notes=notes)
