"""The book's own calls, kept and then read against what the price did.

What is tested here is the wrapper's behaviour rather than a valuation: that a call is
written once per price date, that a refusal is kept with its reason, that the forward
return is measured against the universe rather than raw, and above all that a thin
history says so instead of reporting a mean over four observations.
"""

import datetime as dt

import db
import valuation_history as vh


def _book(tmp_path, closes):
    """A two-company book with a daily price series. ``closes`` is {ticker: [closes]}."""
    path = str(tmp_path / "v.db")
    db.init(path)
    conn = db.get_connection(path)
    start = dt.date(2026, 1, 1)
    for i, (ticker, series) in enumerate(closes.items(), start=1):
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     (i, ticker, ticker))
        for day, close in enumerate(series):
            conn.execute(
                "INSERT INTO prices (company_id, as_of, close, interval)"
                " VALUES (?, ?, ?, '1d')",
                (i, (start + dt.timedelta(days=day)).isoformat(), close))
    conn.commit()
    return path, conn


def _call(conn, company_id, as_of, upside, refused=None):
    conn.execute(
        "INSERT INTO valuation_snapshots (company_id, as_of, captured_at, close,"
        " equity_per_share, upside, refused) VALUES (?, ?, '2026-01-01 00:00:00',"
        " 100.0, ?, ?, ?)",
        (company_id, as_of, None if upside is None else 100 * (1 + upside), upside,
         refused))
    conn.commit()


def test_a_thin_history_says_so_rather_than_reporting_a_mean(tmp_path):
    """The first year of calls cannot answer the question, and a mean over four of them
    reads like evidence when it is a coincidence."""
    path, conn = _book(tmp_path, {"AAA": [100.0] * 300, "BBB": [100.0] * 300})
    _call(conn, 1, "2026-01-02", 0.5)
    _call(conn, 2, "2026-01-02", -0.5)
    out = vh.build(path)
    assert out["calls"] == 2
    assert out["reason"] and "under the" in out["reason"]
    for row in out["rows"]:
        for window in row["windows"].values():
            assert window["thin"] is True
    conn.close()


def test_with_no_calls_it_says_the_book_has_not_started_keeping_them(tmp_path):
    path, _ = _book(tmp_path, {"AAA": [100.0] * 30})
    out = vh.build(path)
    assert out["calls"] == 0
    assert "starts keeping them" in out["reason"]


def test_the_forward_return_is_measured_against_the_universe_not_raw(tmp_path):
    """A sector that rises together is not the book being right. AAA and BBB both double;
    the abnormal return of either against the other is nil."""
    rising = [100.0 * (1.02 ** d) for d in range(300)]
    path, conn = _book(tmp_path, {"AAA": rising, "BBB": list(rising)})
    series = vh._series(db.get_connection(path))
    own = vh.forward_return(series, 1, "2026-01-02", 21)
    market = vh.universe_forward(series, "2026-01-02", 21, exclude=1)
    assert own > 0.4                                  # the raw move is large
    assert abs(own - market) < 1e-9                   # and the abnormal move is nil
    conn.close()


def test_a_call_is_written_once_per_price_date(tmp_path):
    """A refresh run twice in a day replaces its own row rather than writing a second."""
    path, conn = _book(tmp_path, {"AAA": [100.0] * 30})
    _call(conn, 1, "2026-01-02", 0.5)
    conn.execute(
        "INSERT INTO valuation_snapshots (company_id, as_of, captured_at, close, upside)"
        " VALUES (1, '2026-01-02', '2026-01-01 01:00:00', 100.0, 0.9)"
        " ON CONFLICT (company_id, as_of) DO UPDATE SET upside = excluded.upside")
    conn.commit()
    rows = conn.execute("SELECT upside FROM valuation_snapshots").fetchall()
    assert len(rows) == 1 and rows[0]["upside"] == 0.9
    conn.close()


def test_a_refusal_is_kept_with_its_reason_and_left_out_of_the_measurement(tmp_path):
    """A refusal is a call as much as a number is, and a book that remembered only its
    answers would flatter itself. It is counted and not measured."""
    path, conn = _book(tmp_path, {"AAA": [100.0] * 300})
    _call(conn, 1, "2026-01-02", None, refused="marketed products: none of what the "
                                               "company reports selling is modelled")
    out = vh.build(path)
    assert out["calls"] == 0 and out["refusals"] == 1
    stored = conn.execute("SELECT refused FROM valuation_snapshots").fetchone()["refused"]
    assert "none of what the company reports selling is modelled" in stored
    conn.close()


def test_the_buckets_cut_on_the_call_and_not_on_deciles():
    assert vh._bucket(0.45) == "cheap by 30% or more"
    assert vh._bucket(0.05) == "cheap"
    assert vh._bucket(-0.05) == "dear"
    assert vh._bucket(-0.62) == "dear by 30% or more"
