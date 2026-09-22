"""The index and sector closes a beta is regressed against.

The table held 2,513 rows of the S&P written once as a one-off and never refreshed,
ending three weeks behind the company prices it was paired with. A beta measured on
that regresses three weeks of company returns against nothing.
"""

import json
import pathlib

import pytest

import db
from fetchers import benchmarks as B

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "yahoo_chart_xlv.json"


def _payload():
    return json.loads(FIXTURE.read_text())


def test_a_day_the_market_did_not_trade_is_dropped_not_carried():
    """Filling a holiday would put a return of nil into a regression that should not
    see that week at all."""
    rows = B.parse_chart(_payload(), "XLV")
    dates = [r["as_of"] for r in rows]
    assert "2016-09-27" not in dates          # the null bar in the fixture
    assert dates == ["2016-09-22", "2016-09-23", "2016-09-26",
                     "2026-09-21", "2026-09-22"]


def test_the_close_and_the_adjusted_close_land_in_their_own_columns():
    """For an ETF they are two different things. XLV's oldest close is 73.34 against
    an adjusted close of 62.04, an 18.2% gap, which is the dividend stream the sector
    has paid since. A relative figure on closes charges all of that to the sector as
    underperformance."""
    rows = B.parse_chart(_payload(), "XLV")
    first = rows[0]
    assert first["close"] == pytest.approx(73.34, abs=0.01)
    assert first["adjclose"] == pytest.approx(62.04, abs=0.01)
    assert first["close"] / first["adjclose"] - 1 == pytest.approx(0.182, abs=0.002)


def test_a_series_with_no_adjusted_close_stores_the_close():
    """An index pays nothing, so the two are the same number. Storing the close is not
    an assumption there, and a null column would make every index row unusable."""
    payload = _payload()
    del payload["chart"]["result"][0]["indicators"]["adjclose"]
    rows = B.parse_chart(payload, "^GSPC")
    assert rows[0]["close"] == rows[0]["adjclose"]


def test_a_chart_error_is_raised_rather_than_read_as_an_empty_series():
    payload = {"chart": {"error": {"code": "Not Found"}, "result": None}}
    with pytest.raises(ValueError):
        B.parse_chart(payload, "NOPE")
    with pytest.raises(ValueError):
        B.parse_chart({"chart": {"result": []}}, "NOPE")


def test_the_same_day_fetched_twice_writes_one_row(tmp_path):
    path = str(tmp_path / "bench.db")
    db.init(path)
    fetcher = B.BenchmarksFetcher(db_path=path)
    rows = B.parse_chart(_payload(), "XLV")
    assert fetcher.upsert(rows).rows_fetched == 5
    fetcher.upsert(rows)
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM benchmark_prices").fetchone()[0] == 5
    # A revised close overwrites rather than duplicating.
    revised = [{**rows[0], "close": 73.50, "adjclose": 62.20}]
    fetcher.upsert(revised)
    got = conn.execute("SELECT close, adjclose FROM benchmark_prices"
                       " WHERE symbol = 'XLV' AND as_of = '2016-09-22'").fetchone()
    assert conn.execute("SELECT COUNT(*) FROM benchmark_prices").fetchone()[0] == 5
    conn.close()
    assert got["close"] == pytest.approx(73.50)
    assert got["adjclose"] == pytest.approx(62.20)


def test_a_live_snapshot_starts_the_ttl_and_a_cache_snapshot_does_not(tmp_path):
    path = str(tmp_path / "bench2.db")
    db.init(path)
    fetcher = B.BenchmarksFetcher(db_path=path)
    assert fetcher._within_ttl() is False

    rows = B.parse_chart(_payload(), "XLV")
    fetcher.upsert(rows)
    fetcher.snapshot(rows)
    assert fetcher._within_ttl() is True
    conn = db.get_connection(path)
    payload = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'benchmark'"
        " ORDER BY id DESC LIMIT 1").fetchone()[0])
    conn.close()
    assert payload["fetch_kind"] == "live"
    assert payload["symbols"]["XLV"]["as_of"] == "2026-09-22"
    assert "fetch_kind" not in payload["symbols"]

    fetcher._snapshot_cache()
    conn = db.get_connection(path)
    cached = json.loads(conn.execute(
        "SELECT payload FROM snapshots WHERE source = 'benchmark'"
        " ORDER BY id DESC LIMIT 1").fetchone()[0])
    conn.close()
    assert cached["fetch_kind"] == "cache"
    # It still says what is stored, so the history keeps no gap.
    assert cached["symbols"]["XLV"]["as_of"] == "2026-09-22"


def test_a_refused_symbol_is_a_soft_error_and_loses_neither_the_other_nor_the_run(tmp_path):
    """A rate limit is the expected failure on an unofficial endpoint. A stale
    benchmark is better than no benchmark, and better than a stopped refresh."""
    import urllib.error

    path = str(tmp_path / "bench3.db")
    db.init(path)
    fetcher = B.BenchmarksFetcher(db_path=path)

    real = B.urllib.request.urlopen
    calls = {"n": 0}

    class _Response:
        def __init__(self, text):
            self._text = text

        def read(self):
            return self._text.encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake(request, timeout=None):
        calls["n"] += 1
        if "XLV" in request.full_url:
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests",
                                         None, None)
        return _Response(json.dumps(_payload()))

    B.urllib.request.urlopen = fake
    try:
        raw = fetcher.fetch()
    finally:
        B.urllib.request.urlopen = real

    assert calls["n"] == 2                       # both symbols attempted
    assert "^GSPC" in raw and "XLV" not in raw   # one lost, one kept
    assert any("429" in e for e in fetcher._soft)
    result = fetcher.upsert(fetcher.normalise(raw))
    assert result.rows_fetched == 5
    assert any("429" in e for e in result.errors)


def test_history_leaves_the_gaps_where_they_are(tmp_path):
    path = str(tmp_path / "bench4.db")
    db.init(path)
    B.BenchmarksFetcher(db_path=path).upsert(B.parse_chart(_payload(), "XLV"))
    got = B.history(path, "XLV")
    assert [r["as_of"] for r in got][:3] == ["2016-09-22", "2016-09-23", "2016-09-26"]
    assert all(r["as_of"] != "2016-09-27" for r in got)
    assert [r["as_of"] for r in B.history(path, "XLV", "2026-01-01")] == [
        "2026-09-21", "2026-09-22"]
    assert B.history(path, "NOPE") == []


def test_the_beta_on_file_is_reported_against_the_one_the_prices_say(tmp_path):
    """Reported, not adopted, following this branch's precedent of a measured rate
    shown and not taken. A partial series reports nothing rather than a figure that
    would move a discount rate if anyone did adopt it."""
    import forecast_view as V

    path = str(tmp_path / "beta.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.commit()
    got = V.measured_beta(conn, "LLY", stored=0.69)
    conn.close()
    assert got["stored"] == 0.69
    assert got["measured"] is None
    assert got["adopted"] is False
    assert "not enough overlapping weekly history" in got["reason"]


def test_nothing_measured_here_is_ever_adopted(tmp_path):
    """The stored betas are not stale: recomputed on 2026-09-22 all nineteen came back
    within 0.01 of the value on file, mean absolute difference 0.004. There is nothing
    to adopt, and adopting would still be a decision rather than a default."""
    import forecast_view as V

    path = str(tmp_path / "beta2.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.commit()
    assert V.measured_beta(conn, "LLY", stored=0.69)["adopted"] is False
    conn.close()
    # And the override table still names only the two fetched rate legs.
    import assumptions
    assert set(assumptions.LIVE_RATES) == {"risk_free", "cost_of_debt"}
