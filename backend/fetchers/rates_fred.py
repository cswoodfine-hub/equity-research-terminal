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
        newest = {}
        for row in rows:
            if row["as_of"] > newest.get(row["series"], {"as_of": ""})["as_of"]:
                newest[row["series"]] = row
        self._snapshot_payload({s: {"as_of": r["as_of"], "value": r["value"]}
                                for s, r in newest.items()}, "live")

    def _snapshot_cache(self) -> None:
        """The rates already stored, when the fetch fails: a valuation still says which
        day it read, and the gap is visible in the snapshot history."""
        self._snapshot_payload({s: {"as_of": r["as_of"], "value": r["value"]}
                                for s, r in latest(self.db_path).items()}, "cache")

    def _snapshot_payload(self, series_payload, fetch_kind: str) -> None:
        """Write the snapshot, saying whether the numbers in it were just fetched.

        ``fetch_kind`` is not decoration. ``BaseFetcher._last_live_fetch_at`` looks for
        a snapshot whose payload carries ``fetch_kind = 'live'`` and finds the TTL's
        starting point there, so a fetcher that never writes the key has no last live
        fetch and ``_within_ttl`` is always false. This one wrote none, and four series
        were therefore refetched on every run for the life of the fetcher, TTL or no
        TTL. The series sit under their own key so the flag cannot be read as a series.
        """
        import json
        payload = {"series": series_payload, "fetch_kind": fetch_kind}
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
        clear_cache()
        return RefreshResult(SOURCE, written, notes=[f"{written} rate observations"])


# The newest observation of each series, per database, behind a version stamp.
#
# ``latest`` was reading the table through a correlated subquery on every call, and a
# single break-points build for Lilly called it 508 times: 0.61s of a 2.8s build spent
# re-reading one number. Caching it needs care, because build 3 puts the discount rate
# on this path, and a cache keyed on the day would let a refresh land mid-session and
# leave the page quoting one date while the valuation used another.
#
# So the key is a stamp over the table itself rather than a clock: row count, highest
# rowid, newest date and the total of every value. An insert moves the first three and
# a revision in place, which keeps its rowid, moves the last. Two different tables
# agreeing on all four is not a case this data can produce. ``upsert`` also clears the
# cache outright, which covers a refresh in this process; the stamp covers one in
# another.
_CACHE: dict = {}


class _Borrowed:
    """Use a caller's connection, or open one and close it again.

    Opening a connection is 88% of the cost of a cached read: 508 reads in one
    break-points build spend 0.34s opening SQLite and 0.05s asking it anything. A
    caller that already holds a connection should hand it over rather than pay that.
    """

    def __init__(self, db_path, conn):
        self._own = conn is None
        self.conn = db.get_connection(db_path) if self._own else conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        if self._own:
            self.conn.close()
        return False


def _stamp(conn) -> tuple:
    """A cheap value that changes whenever anything in market_rates changes."""
    return tuple(conn.execute(
        "SELECT COUNT(*), MAX(rowid), MAX(as_of), TOTAL(value)"
        "  FROM market_rates").fetchone())


def clear_cache() -> None:
    """Drop the cached reads. Called on write, and by tests that write behind us."""
    _CACHE.clear()


def latest(db_path=None, series: str | None = None, conn=None) -> dict:
    """{series: {value, as_of, description}} at the most recent observation of each."""
    with _Borrowed(db_path, conn) as c:
        stamp = _stamp(c)
        hit = _CACHE.get(db_path)
        if hit and hit[0] == stamp:
            out = hit[1]
        else:
            rows = c.execute(
                """SELECT series, value, as_of FROM market_rates m
                    WHERE as_of = (SELECT MAX(as_of) FROM market_rates
                                    WHERE series = m.series)""").fetchall()
            out = {r["series"]: {"value": r["value"], "as_of": r["as_of"],
                                 "description": SERIES.get(r["series"], "")}
                   for r in rows}
            _CACHE[db_path] = (stamp, out)
    return out.get(series, {}) if series else out


def rates_on(db_path, on_date: str, series: str | None = None, conn=None) -> dict:
    """The rates as the market last quoted them on or before ``on_date``.

    ``latest`` answers what the ten-year is now, which is the right question for a
    valuation struck today and the wrong one for a snapshot struck in March. Each
    series is read on its own date, because a holiday or the two-day lag on the indexed
    series drops one and not the others, and carrying a neighbour's date forward would
    date a number to a day it was never published on.

    Returns {} where the history does not reach back. The table keeps KEEP_DAYS of
    observations, so a date older than that has no honest answer and is told so rather
    than quietly given today's rate.
    """
    if not on_date:
        return {}
    day = on_date[:10]
    with _Borrowed(db_path, conn) as c:
        rows = c.execute(
            """SELECT series, value, as_of FROM market_rates m
                WHERE as_of = (SELECT MAX(as_of) FROM market_rates
                                WHERE series = m.series AND as_of <= ?)""",
            (day,)).fetchall()
    out = {r["series"]: {"value": r["value"], "as_of": r["as_of"],
                         "description": SERIES.get(r["series"], "")} for r in rows}
    return out.get(series, {}) if series else out


def history(db_path, series: str, since: str | None = None, conn=None) -> list[dict]:
    """[{as_of, value}] for one series, oldest first, from ``since`` if given.

    Days the source suppressed are absent rather than carried, so a caller reading two
    series together must intersect the dates before it compares them.
    """
    sql = "SELECT as_of, value FROM market_rates WHERE series = ?"
    args: list = [series]
    if since:
        sql += " AND as_of >= ?"
        args.append(since[:10])
    with _Borrowed(db_path, conn) as c:
        rows = c.execute(sql + " ORDER BY as_of", args).fetchall()
    return [{"as_of": r["as_of"], "value": r["value"]} for r in rows]
