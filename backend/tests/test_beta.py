"""Beta computed against a stored market series rather than remembered.

Every seeded beta in this repository says "computed from 261 weekly returns vs S&P 500,
Blume-adjusted" and none could be reproduced, because the index series was never stored.
That made three of the largest companies in the universe unforecastable: they had no
remembered number and beta is the one discount-rate input no filing carries.
"""

import datetime as dt

import beta
import db


def _seed(tmp_path, stock_factor=1.0, noise=0.0):
    """A company whose weekly return is ``stock_factor`` times the market's."""
    path = str(tmp_path / "b.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'TEST', 'Test')")
    level_m, level_s = 100.0, 50.0
    day = dt.date(2021, 1, 4)
    for week in range(300):
        # A market that moves a different amount each week, so the regression has
        # something to fit rather than one repeated point.
        step = 0.01 if week % 3 == 0 else (-0.005 if week % 3 == 1 else 0.02)
        bump = noise if week % 7 == 0 else 0.0
        level_m *= 1 + step
        level_s *= 1 + step * stock_factor + bump
        stamp = (day + dt.timedelta(weeks=week)).isoformat()
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES (?, ?, ?)",
                     (beta.SYMBOL, stamp, level_m))
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval, source)"
                     " VALUES (1, ?, ?, '1d', 'test')", (stamp, level_s))
    conn.commit()
    return path, conn


def test_a_stock_that_moves_with_the_market_is_one_after_adjustment(tmp_path):
    path, conn = _seed(tmp_path, stock_factor=1.0)
    value, basis = beta.compute(conn, "TEST")
    conn.close()
    assert value == 1.0                       # 2/3 of 1.0 plus 1/3 of 1.0
    assert "weekly returns vs S&P 500" in basis and "Blume-adjusted" in basis


def test_a_stock_that_moves_twice_as_hard_is_pulled_toward_the_market(tmp_path):
    """Raw 2.0, Blume-adjusted to 5/3. The adjustment is the whole point: a raw beta is
    an estimate with a standard error and is known to revert."""
    path, conn = _seed(tmp_path, stock_factor=2.0)
    value, _ = beta.compute(conn, "TEST")
    conn.close()
    assert round(value, 2) == 1.67


def test_a_stock_that_barely_moves_is_pulled_up(tmp_path):
    path, conn = _seed(tmp_path, stock_factor=0.25)
    value, _ = beta.compute(conn, "TEST")
    conn.close()
    assert round(value, 2) == 0.5             # 2/3 of 0.25 plus 1/3


def test_no_market_series_yields_nothing_rather_than_a_guess(tmp_path):
    path, conn = _seed(tmp_path)
    conn.execute("DELETE FROM benchmark_prices")
    conn.commit()
    assert beta.compute(conn, "TEST") == (None, None)
    conn.close()


def test_an_unknown_ticker_yields_nothing(tmp_path):
    path, conn = _seed(tmp_path)
    assert beta.compute(conn, "NOPE") == (None, None)
    conn.close()


def test_too_little_history_is_refused(tmp_path):
    path, conn = _seed(tmp_path)
    conn.execute("DELETE FROM prices WHERE as_of > '2021-06-01'")
    conn.commit()
    assert beta.compute(conn, "TEST") == (None, None)
    conn.close()


def test_the_window_is_the_last_five_years(tmp_path):
    """More history than the window does not widen it: the basis names 261 returns."""
    path, conn = _seed(tmp_path)
    _, basis = beta.compute(conn, "TEST")
    conn.close()
    assert "from 261 weekly returns" in basis
