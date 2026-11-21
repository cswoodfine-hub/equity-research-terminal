"""Each quarter's EPS against the street's expectation, from Nasdaq's surprise table.

The consensus fetcher reads Nasdaq's annual EPS estimates. This reads the page beside
it: the last four quarters a company reported, each with the EPS the street counts, the
consensus that stood before the report, the surprise between them and the date of the
announcement. It answers without a key or a cookie.

Three things the figures are not. They are not filed: the EPS is the street's, usually
the company's adjusted number, and it differs from the diluted EPS in the 10-Q. They are
not revenue: Nasdaq prints no revenue consensus here, so a revenue surprise stays empty
rather than being backed out of anything. And they are per share of the US listing, the
ADR where the company has one, in dollars.

The endpoint is unofficial, like the consensus one. It can change or refuse without
notice, so a failure is a soft, reported error, never a crash.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult
from fetchers.consensus_nasdaq import HEADERS

SOURCE = "earnings_nasdaq"
TTL_SECONDS = 24 * 60 * 60
_TIMEOUT_S = 30
URL = "https://api.nasdaq.com/api/company/{symbol}/earnings-surprise"
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}


def quarter_end(label: str) -> str | None:
    """'Sep 2026' -> '2026-09'. None for anything that is not a month and a year."""
    parts = (label or "").split()
    if len(parts) != 2 or parts[0][:3] not in _MONTHS or not parts[1].isdigit():
        return None
    return f"{int(parts[1]):04d}-{_MONTHS[parts[0][:3]]:02d}"


def reported_on(text: str) -> str | None:
    """'10/29/2026' -> '2026-10-29'. Nasdaq prints the date the American way."""
    try:
        return dt.datetime.strptime((text or "").strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def _number(value) -> float | None:
    """A figure Nasdaq prints as a number or as a string. 'N/A' and '' are no figure."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def parse(company_id: int, payload: dict | None) -> list[dict]:
    """Table rows from the payload. Pure. A missing figure is null, never a zero.

    A row needs its quarter and both EPS figures, since a surprise is the two of them:
    a quarter with a reported EPS and no consensus says nothing about how it landed.
    The surprise is Nasdaq's own where it prints one. Where it does not, it is the same
    arithmetic, against the size of the consensus so a narrower loss reads as a beat,
    and left null against a consensus of zero.
    """
    table = ((payload or {}).get("data") or {}).get("earningsSurpriseTable") or {}
    rows = []
    for record in table.get("rows") or []:
        quarter = quarter_end(record.get("fiscalQtrEnd"))
        eps = _number(record.get("eps"))
        consensus = _number(record.get("consensusForecast"))
        if quarter is None or eps is None or consensus is None:
            continue
        surprise = _number(record.get("percentageSurprise"))
        if surprise is None and consensus:
            surprise = round((eps - consensus) / abs(consensus) * 100, 2)
        rows.append({"company_id": company_id, "quarter_end": quarter,
                     "reported_on": reported_on(record.get("dateReported")),
                     "eps": eps, "consensus_eps": consensus, "surprise_pct": surprise})
    return rows


def _get(symbol: str) -> dict:
    request = urllib.request.Request(URL.format(symbol=symbol), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


class EarningsNasdaqFetcher(BaseFetcher):
    """One symbol's last four reported quarters against the street."""

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
        return {"company": dict(company), "surprise": _get(symbol)}

    def normalise(self, raw) -> list[dict]:
        return parse(raw["company"]["id"], raw.get("surprise"))

    def snapshot(self, rows: list[dict]) -> None:
        self._write_snapshot({"quarters": len(rows), "fetch_kind": "live"})

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                """SELECT COUNT(*) FROM earnings_surprises s
                     JOIN companies c ON c.id = s.company_id
                    WHERE c.ticker = ?""", (self.ticker,)).fetchone()[0]
        finally:
            conn.close()
        self._write_snapshot({"quarters": n, "fetch_kind": "cache"})

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
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                current = conn.execute(
                    """SELECT reported_on, eps, consensus_eps, surprise_pct
                         FROM earnings_surprises
                        WHERE company_id = ? AND quarter_end = ?""",
                    (row["company_id"], row["quarter_end"])).fetchone()
                figures = (row["reported_on"], row["eps"], row["consensus_eps"],
                           row["surprise_pct"])
                if current is not None and tuple(current) == figures:
                    continue
                conn.execute(
                    """INSERT INTO earnings_surprises
                           (company_id, quarter_end, reported_on, eps, consensus_eps,
                            surprise_pct, source, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, 'nasdaq', datetime('now'))
                       ON CONFLICT(company_id, quarter_end) DO UPDATE SET
                           reported_on = excluded.reported_on, eps = excluded.eps,
                           consensus_eps = excluded.consensus_eps,
                           surprise_pct = excluded.surprise_pct,
                           fetched_at = datetime('now')""",
                    (row["company_id"], row["quarter_end"], *figures))
                written += 1
            conn.commit()
        finally:
            conn.close()
        notes = [f"{self.ticker}: {written} quarters read or restated"] if written else []
        return RefreshResult(SOURCE, written, notes=notes)
