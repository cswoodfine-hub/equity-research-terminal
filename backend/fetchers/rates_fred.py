"""The market rates every discount rate is built on, from FRED.

Each product's discount rate starts from a risk-free rate, a cost of debt and, for the
launch franchise, expected inflation. All three were read by hand on a day and written
into every seed, so they aged: the 10-year Treasury was 4.66% when the book was built
and 5.00% seven weeks later, which is 1.2% of the book's value sitting in a number
nobody refreshed.

FRED publishes each series as a CSV with no key and no cookie, one row per business day.
This stores them, and ``latest`` gives the most recent observation of each with its date,
so a valuation can say which day's rate it used rather than which day's rate it was
written on. A day with no observation (a holiday, or the two-day lag on the indexed
series) is skipped rather than carried forward.

The series:
  DGS10        10-year Treasury constant maturity, the risk-free rate.
  DFII10       10-year Treasury inflation-indexed, the real rate.
  T10YIE       10-year breakeven inflation, DGS10 less DFII10, which is the franchise's
               long-run growth (future_pipeline_defaults.csv).
  BAMLC0A3CAEY ICE BofA single-A US corporate effective yield, the cost of debt.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import urllib.request

import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "fred"
TTL_SECONDS = 12 * 60 * 60
_TIMEOUT_S = 60
URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
# Sent bare, with no headers of our own. The endpoint answers a plain request in a
# tenth of a second and hangs until it times out on one carrying a Connection header,
# which is what a browser-shaped set of headers brings with it. Accept and
# Accept-Encoding are fine; the whole set is not, so nothing is sent.
HEADERS: dict = {}
SERIES = {
    "DGS10": "10-year Treasury constant maturity",
    "DFII10": "10-year Treasury inflation-indexed",
    "T10YIE": "10-year breakeven inflation",
    "BAMLC0A3CAEY": "ICE BofA A-rated US corporate effective yield",
}
# Enough history to read a series that has paused, and short enough to stay small.
KEEP_DAYS = 400


def parse(series: str, text: str) -> list[dict]:
    """[{series, as_of, value}] from a FRED CSV. A suppressed day reads "." and is
    dropped, never carried forward. Pure."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        date = (row.get("observation_date") or row.get("DATE") or "").strip()
        raw = (row.get(series) or "").strip()
        if not date or raw in ("", "."):
            continue
        try:
            out.append({"series": series, "as_of": date, "value": float(raw) / 100.0})
        except ValueError:
            continue
    return out


class RatesFredFetcher(BaseFetcher):
    """The four market rates the valuation reads, daily."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    @property
    def entity_key(self) -> str:
        return "rates"

    def fetch(self) -> dict:
        out = {}
        for series in SERIES:
            request = urllib.request.Request(URL.format(series=series),
                                             headers=HEADERS)
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
                out[series] = resp.read().decode("utf-8")
        return out

    def normalise(self, raw: dict) -> list[dict]:
        cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
        rows = []
        for series, text in raw.items():
            rows += [r for r in parse(series, text) if r["as_of"] >= cutoff]
        return rows

    def snapshot(self, rows: list[dict]) -> None:
        latest = {}
        for row in rows:
            if row["as_of"] > latest.get(row["series"], {"as_of": ""})["as_of"]:
                latest[row["series"]] = row
        self._snapshot_payload({s: {"as_of": r["as_of"], "value": r["value"]}
                                for s, r in latest.items()})

    def _snapshot_cache(self) -> None:
        """The rates already stored, when the fetch fails: a valuation still says which
        day it read, and the gap is visible in the snapshot history."""
        self._snapshot_payload({s: {"as_of": r["as_of"], "value": r["value"]}
                                for s, r in latest(self.db_path).items()})

    def _snapshot_payload(self, payload) -> None:
        import json
        conn = db.get_connection(self.db_path)
        try:
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
                " refresh_run_id) VALUES (?, 'market', 'rates', ?, ?)",
                (SOURCE, json.dumps(payload), self.refresh_run_id))
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        written = 0
        try:
            for row in rows:
                cursor = conn.execute(
                    """INSERT INTO market_rates (series, as_of, value, source)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(series, as_of) DO UPDATE SET value = excluded.value""",
                    (row["series"], row["as_of"], row["value"], SOURCE))
                written += cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        return RefreshResult(SOURCE, written, notes=[f"{written} rate observations"])


def latest(db_path=None, series: str | None = None) -> dict:
    """{series: {value, as_of, description}} at the most recent observation of each."""
    conn = db.get_connection(db_path)
    try:
        rows = conn.execute(
            """SELECT series, value, as_of FROM market_rates m
                WHERE as_of = (SELECT MAX(as_of) FROM market_rates
                                WHERE series = m.series)""").fetchall()
    finally:
        conn.close()
    out = {r["series"]: {"value": r["value"], "as_of": r["as_of"],
                         "description": SERIES.get(r["series"], "")} for r in rows}
    return out.get(series, {}) if series else out
