"""Street consensus from Financial Modeling Prep, the one sanctioned paid dataset.

CLAUDE.md calls FMP's consensus EPS and revenue "the one genuinely useful cheap
dataset", and this fetcher is written for the day a key lands in ``FMP_API_KEY``. Until
then it does not run at all: the refresh registry gates on the key, so an unkeyed
checkout never spends seventy fetchers reporting that they have nothing to read.

Revisions are the point of the table's shape. A row is written only when the figure
differs from the newest one stored, with the fetch date as ``as_of``, so the table
accumulates the street's changes of mind rather than a daily copy of the same number.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "consensus_fmp"
TTL_SECONDS = 24 * 60 * 60          # the PRD's cadence for estimates: daily
_TIMEOUT_S = 30
BASE_URL = "https://financialmodelingprep.com/stable/analyst-estimates"

# What an FMP record calls things, and what the table calls them.
FIELDS = (
    ("Revenue", "revenueAvg", "revenueLow", "revenueHigh", "numAnalystsRevenue"),
    ("EPS", "epsAvg", "epsLow", "epsHigh", "numAnalystsEps"),
)


def api_key() -> str:
    return (os.getenv("FMP_API_KEY") or "").strip()


class ConsensusFmpFetcher(BaseFetcher):
    """One symbol's annual analyst estimates, revisions kept."""

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
        key = api_key()
        if not key:
            # Belt beside the registry's braces: the fetcher should not be running
            # without a key, and if it somehow is, it reports rather than crashes.
            return {"company": dict(company), "records": None}
        symbol = company["us_adr_ticker"] or company["ticker"]
        query = urllib.parse.urlencode(
            {"symbol": symbol, "period": "annual", "apikey": key})
        request = urllib.request.Request(
            f"{BASE_URL}?{query}",
            headers={"User-Agent": "NovatalisResearch/0.1"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            records = json.loads(resp.read().decode("utf-8"))
        return {"company": dict(company), "records": records}

    def normalise(self, raw) -> list[dict]:
        company = raw["company"]
        self.no_key = raw["records"] is None
        if self.no_key:
            return []
        rows = []
        for record in raw["records"] or []:
            date = str(record.get("date") or "")[:10]
            if len(date) != 10:
                continue
            period = f"FY{date[:4]}"
            for metric, avg, low, high, analysts in FIELDS:
                value = record.get(avg)
                if value is None:
                    continue
                count = record.get(analysts)
                rows.append({
                    "company_id": company["id"], "metric": metric,
                    "period": period, "value": float(value),
                    "low": record.get(low), "high": record.get(high),
                    "currency": "USD", "source": "fmp",
                    "note": f"{count} analysts" if count else None,
                })
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"estimates": len(rows), "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                """SELECT COUNT(*) FROM consensus_estimates e
                     JOIN companies c ON c.id = e.company_id
                    WHERE c.ticker = ? AND e.source = 'fmp'""",
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
        if getattr(self, "no_key", False):
            return RefreshResult(SOURCE, 0, notes=[f"{self.ticker}: no FMP key set"])
        today = dt.date.today().isoformat()
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                # A revision is a change of mind; the same number again is not. Only a
                # figure that differs from the newest stored one earns a row, so the
                # table holds the street's history rather than a daily photocopy.
                current = conn.execute(
                    """SELECT value FROM consensus_estimates
                        WHERE company_id = ? AND metric = ? AND period = ?
                          AND source = 'fmp'
                        ORDER BY as_of DESC LIMIT 1""",
                    (row["company_id"], row["metric"], row["period"])).fetchone()
                if current is not None and current["value"] == row["value"]:
                    continue
                conn.execute(
                    """INSERT OR IGNORE INTO consensus_estimates
                           (company_id, metric, period, value, low, high, currency,
                            source, as_of, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'fmp', ?, ?)""",
                    (row["company_id"], row["metric"], row["period"], row["value"],
                     row["low"], row["high"], row["currency"], today, row["note"]))
                written += 1
            conn.commit()
        finally:
            conn.close()
        notes = []
        if written:
            notes.append(f"{self.ticker}: {written} estimate revisions")
        return RefreshResult(SOURCE, written, notes=notes)
