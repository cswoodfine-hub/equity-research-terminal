"""A company's move against its sector, on the dates both of them traded.

The comparison is the whole difficulty. Two series with their own first and last days
measured over their own windows differ by the calendar as much as by performance, and
the difference reads as alpha.
"""

import pytest

import comps
import db


def _seed(path, stock: dict, market: dict, symbol="XLV"):
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    for as_of, close in stock.items():
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source)"
                     " VALUES (1, ?, ?, '1d', 't')", (as_of, close))
    for as_of, adj in market.items():
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close, adjclose)"
                     " VALUES (?, ?, ?, ?)", (symbol, as_of, adj, adj))
    conn.commit()
    conn.close()


def test_the_window_is_the_days_both_of_them_traded(tmp_path):
    """The company traded on a day the sector did not. Measuring each over its own
    first and last day would compare a four-day move with a three-day one and read the
    calendar as performance."""
    path = str(tmp_path / "rel.db")
    _seed(path,
          stock={"2026-09-01": 100.0, "2026-09-02": 101.0, "2026-09-03": 104.0},
          market={"2026-09-02": 50.0, "2026-09-03": 51.0})
    got = comps.relative_performance(path, "LLY", windows=((30, "1m"),))["1m"]
    # From the 2nd, not the 1st: the sector has no bar on the 1st.
    assert got["first_as_of"] == "2026-09-02"
    assert got["company_pct"] == pytest.approx(104.0 / 101.0 - 1)
    assert got["benchmark_pct"] == pytest.approx(51.0 / 50.0 - 1)
    assert got["relative_pct"] == pytest.approx(got["company_pct"]
                                                - got["benchmark_pct"])
    assert got["points"] == 2


def test_the_benchmark_is_read_on_its_adjusted_close(tmp_path):
    """XLV's close and adjusted close differ by 18.2% over ten years, which is the
    dividend stream. On closes the sector's whole payout reads as underperformance."""
    path = str(tmp_path / "adj.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    for as_of, close in (("2026-09-01", 100.0), ("2026-09-02", 110.0)):
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source)"
                     " VALUES (1, ?, ?, '1d', 't')", (as_of, close))
    # The close is flat and the adjusted close is up 10%: a dividend was paid.
    for as_of, close, adj in (("2026-09-01", 50.0, 45.0), ("2026-09-02", 50.0, 49.5)):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close, adjclose)"
                     " VALUES ('XLV', ?, ?, ?)", (as_of, close, adj))
    conn.commit()
    conn.close()
    got = comps.relative_performance(path, "LLY", windows=((30, "1m"),))["1m"]
    assert got["benchmark_pct"] == pytest.approx(0.10)      # not 0.0
    assert got["relative_pct"] == pytest.approx(0.0)        # the company matched it


def test_a_window_the_history_does_not_reach_says_so(tmp_path):
    """A one-year figure drawn from two days of data is a two-day figure wearing the
    wrong label. The figure still comes back, with the dates it was measured over and
    covers_window false, so the caller decides rather than this function guessing."""
    path = str(tmp_path / "short.db")
    _seed(path,
          stock={"2026-09-01": 100.0, "2026-09-02": 101.0},
          market={"2026-09-01": 50.0, "2026-09-02": 50.5})
    got = comps.relative_performance(path, "LLY",
                                     windows=((30, "1m"), (365, "1y")))
    assert got["1y"]["covers_window"] is False
    assert got["1y"]["first_as_of"] == "2026-09-01"
    assert got["1y"]["points"] == 2
    assert got["1m"]["covers_window"] is False


def test_no_overlap_at_all_returns_nothing(tmp_path):
    path = str(tmp_path / "none.db")
    _seed(path,
          stock={"2026-09-01": 100.0, "2026-09-02": 101.0},
          market={"2026-08-01": 50.0, "2026-08-04": 50.5})
    got = comps.relative_performance(path, "LLY", windows=((30, "1m"),))
    assert got["1m"] is None
    # An unknown ticker is refused the same way rather than raising.
    assert comps.relative_performance(path, "NOPE",
                                      windows=((30, "1m"),))["1m"] is None


def test_the_relative_move_is_the_difference_and_is_signed(tmp_path):
    path = str(tmp_path / "sign.db")
    # Reaching back past the window's start, so this one genuinely covers it.
    _seed(path,
          stock={"2026-08-01": 100.0, "2026-09-01": 95.0, "2026-09-30": 90.0},
          market={"2026-08-01": 50.0, "2026-09-01": 52.0, "2026-09-30": 55.0})
    got = comps.relative_performance(path, "LLY", windows=((60, "2m"),))["2m"]
    assert got["covers_window"] is True
    assert got["company_pct"] == pytest.approx(-0.10)
    assert got["benchmark_pct"] == pytest.approx(0.10)
    assert got["relative_pct"] == pytest.approx(-0.20)


def test_the_sector_is_the_benchmark_not_the_market():
    """The question a relative figure answers here is whether a company beat its
    sector, not whether healthcare beat the market."""
    assert comps.RELATIVE_BENCHMARK == "XLV"
    assert [span for _days, span in comps.RELATIVE_WINDOWS] == ["1m", "3m", "1y"]
