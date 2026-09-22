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


def _seed(path):
    db.init(path)
    conn = db.get_connection(path)
    for series, as_of, value in (
            ("DGS10", "2026-09-15", 0.0497), ("DGS10", "2026-09-16", 0.0501),
            ("DGS10", "2026-09-18", 0.0499),
            # The indexed series lags by two days, so its newest date is not DGS10's.
            ("DFII10", "2026-09-16", 0.0268),
            ("T10YIE", "2026-09-18", 0.0233)):
        conn.execute("INSERT INTO market_rates (series, as_of, value, source)"
                     " VALUES (?, ?, ?, 'fred')", (series, as_of, value))
    conn.commit()
    conn.close()
    rates_fred.clear_cache()


def test_each_series_is_read_on_its_own_date_not_a_neighbours(tmp_path):
    """A holiday or the two-day lag on the indexed series drops one series and not the
    others. Carrying a neighbour's date across would date a rate to a day it was never
    published on."""
    path = str(tmp_path / "on.db")
    _seed(path)
    got = rates_fred.rates_on(path, "2026-09-17")
    assert got["DGS10"]["as_of"] == "2026-09-16"
    assert got["DGS10"]["value"] == pytest.approx(0.0501)
    assert got["DFII10"]["as_of"] == "2026-09-16"
    # Published on the 18th, so on the 17th it did not exist yet.
    assert "T10YIE" not in got
    assert rates_fred.rates_on(path, "2026-09-17", "DGS10")["value"] == pytest.approx(0.0501)


def test_a_date_the_record_does_not_reach_gets_nothing_not_todays_rate(tmp_path):
    path = str(tmp_path / "on2.db")
    _seed(path)
    assert rates_fred.rates_on(path, "2019-01-01") == {}
    assert rates_fred.rates_on(path, "") == {}


def test_history_is_oldest_first_and_leaves_the_gaps_where_they_are(tmp_path):
    path = str(tmp_path / "h.db")
    _seed(path)
    got = rates_fred.history(path, "DGS10")
    assert [r["as_of"] for r in got] == ["2026-09-15", "2026-09-16", "2026-09-18"]
    assert [r["as_of"] for r in rates_fred.history(path, "DGS10", "2026-09-16")] == [
        "2026-09-16", "2026-09-18"]
    assert rates_fred.history(path, "NOPE") == []


def test_the_cache_does_not_outlive_a_write_it_did_not_make(tmp_path):
    """The reason the key is a stamp over the table and not the day: a refresh landing
    mid-session must not leave the page quoting one date while a valuation uses
    another."""
    path = str(tmp_path / "c.db")
    _seed(path)
    assert rates_fred.latest(path, "DGS10")["as_of"] == "2026-09-18"

    conn = db.get_connection(path)
    conn.execute("INSERT INTO market_rates (series, as_of, value, source)"
                 " VALUES ('DGS10', '2026-09-21', 0.0505, 'fred')")
    conn.commit()
    conn.close()
    assert rates_fred.latest(path, "DGS10")["as_of"] == "2026-09-21"

    # A revision in place keeps its rowid, so the stamp has to see the value itself.
    conn = db.get_connection(path)
    conn.execute("UPDATE market_rates SET value = 0.0512"
                 " WHERE series = 'DGS10' AND as_of = '2026-09-21'")
    conn.commit()
    conn.close()
    assert rates_fred.latest(path, "DGS10")["value"] == pytest.approx(0.0512)


def test_a_lent_connection_is_used_and_left_open(tmp_path):
    path = str(tmp_path / "lend.db")
    _seed(path)
    conn = db.get_connection(path)
    assert rates_fred.latest(path, "DGS10", conn=conn)["as_of"] == "2026-09-18"
    assert rates_fred.rates_on(path, "2026-09-16", "DGS10", conn=conn)["value"] == pytest.approx(0.0501)
    assert len(rates_fred.history(path, "DGS10", conn=conn)) == 3
    conn.execute("SELECT 1")            # still open, so the caller still owns it
    conn.close()


def test_two_databases_never_share_a_cached_read(tmp_path):
    """The cache is keyed on the file a connection is open on, not the path a caller
    named. A caller lending a connection usually has no path to give, so keying on the
    argument filed every lent read under None and let one database read another's."""
    one, two = str(tmp_path / "one.db"), str(tmp_path / "two.db")
    for path, value in ((one, 0.0501), (two, 0.0312)):
        db.init(path)
        conn = db.get_connection(path)
        conn.execute("INSERT INTO market_rates (series, as_of, value, source)"
                     " VALUES ('DGS10', '2026-09-18', ?, 'fred')", (value,))
        conn.commit()
        conn.close()
    rates_fred.clear_cache()

    # Lent connections, both with no db_path, which is how assumptions.load calls it.
    a, b = db.get_connection(one), db.get_connection(two)
    assert rates_fred.latest(None, "DGS10", conn=a)["value"] == pytest.approx(0.0501)
    assert rates_fred.latest(None, "DGS10", conn=b)["value"] == pytest.approx(0.0312)
    assert rates_fred.latest(None, "DGS10", conn=a)["value"] == pytest.approx(0.0501)
    a.close()
    b.close()
