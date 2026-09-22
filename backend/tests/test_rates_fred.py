"""The market rates every discount rate is built on."""

import json

import pytest

import db
from fetchers import rates_fred


CSV = """observation_date,DGS10
2026-09-14,4.97
2026-09-15,.
2026-09-16,5.01
"""


def test_a_suppressed_day_is_dropped_not_carried_forward():
    got = rates_fred.parse("DGS10", CSV)
    assert [r["as_of"] for r in got] == ["2026-09-14", "2026-09-16"]
    assert got[-1]["value"] == pytest.approx(0.0501)      # a rate, not a percentage


def test_the_latest_observation_of_each_series_is_what_a_valuation_reads(tmp_path):
    path = str(tmp_path / "r.db")
    db.init(path)
    conn = db.get_connection(path)
    for series, as_of, value in (("DGS10", "2026-09-15", 0.0497), ("DGS10", "2026-09-16", 0.0501),
                                 ("T10YIE", "2026-09-17", 0.0233)):
        conn.execute("INSERT INTO market_rates (series, as_of, value, source) VALUES (?, ?, ?, 'fred')",
                     (series, as_of, value))
    conn.commit()
    conn.close()
    got = rates_fred.latest(path)
    assert got["DGS10"]["value"] == pytest.approx(0.0501) and got["DGS10"]["as_of"] == "2026-09-16"
    assert rates_fred.latest(path, "T10YIE")["value"] == pytest.approx(0.0233)
    assert rates_fred.latest(path, "NOPE") == {}


def test_a_fetched_series_is_stored_once_per_day(tmp_path):
    path = str(tmp_path / "r2.db")
    db.init(path)
    fetcher = rates_fred.RatesFredFetcher(db_path=path)
    rows = rates_fred.parse("DGS10", CSV)
    assert fetcher.upsert(rows).rows_fetched == 2
    fetcher.upsert(rows)                                  # same day again, no duplicate
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM market_rates").fetchone()[0] == 2
    conn.close()


def test_a_live_snapshot_says_so_and_starts_the_ttl(tmp_path):
    """The TTL is read off a snapshot that claims a live fetch. Without the claim the
    12-hour TTL never applies and the four series are refetched on every run."""
    path = str(tmp_path / "r3.db")
    db.init(path)
    fetcher = rates_fred.RatesFredFetcher(db_path=path)
    assert fetcher._last_live_fetch_at() is None
    assert fetcher._within_ttl() is False

    fetcher.snapshot(rates_fred.parse("DGS10", CSV))
    assert fetcher._last_live_fetch_at() is not None
    assert fetcher._within_ttl() is True

    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'fred'").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "live"
    # The flag sits beside the series, never among them.
    assert payload["series"]["DGS10"]["as_of"] == "2026-09-16"
    assert "fetch_kind" not in payload["series"]


def test_a_cache_snapshot_does_not_start_the_ttl(tmp_path):
    """A fetch that failed falls back to the stored rates. That snapshot keeps the
    history unbroken, and must not be mistaken for a fetch that reached FRED."""
    path = str(tmp_path / "r4.db")
    db.init(path)
    fetcher = rates_fred.RatesFredFetcher(db_path=path)
    fetcher._snapshot_cache()
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'fred'").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "cache"
    assert fetcher._last_live_fetch_at() is None
    assert fetcher._within_ttl() is False
