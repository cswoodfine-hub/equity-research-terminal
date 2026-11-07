"""Which detected changes precede a move, and the benchmark that decides the answer.

The finding this file exists to protect: measured against the book's own equal-weight
universe every change type showed a positive abnormal return, and none of it was real.
A book of biotech is dragged by its own casualties, so its mean is a benchmark almost
anything beats. Against XBI the same effects go to nothing.
"""

import datetime as dt

import db
import event_signal


def _book(tmp_path, closes, bench=None, changes=()):
    """A book with daily closes per ticker, a benchmark series, and detected changes."""
    path = str(tmp_path / "e.db")
    db.init(path)
    conn = db.get_connection(path)
    start = dt.date(2026, 1, 1)
    for i, (ticker, series) in enumerate(closes.items(), start=1):
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     (i, ticker, ticker))
        for day, close in enumerate(series):
            conn.execute("INSERT INTO prices (company_id, as_of, close, interval)"
                         " VALUES (?, ?, ?, '1d')",
                         (i, (start + dt.timedelta(days=day)).isoformat(), close))
    for day, close in enumerate(bench or []):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close, source)"
                     " VALUES ('XBI', ?, ?, 'test')",
                     ((start + dt.timedelta(days=day)).isoformat(), close))
    for cid, when, kind in changes:
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, 'B', 1)", (cid,))
        asset = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO changes (entity_type, entity_key, change_type,"
                     " field, significance, detected_at) VALUES ('asset', ?, ?, 'x', 'high', ?)",
                     (str(asset), kind, when))
    conn.commit()
    conn.close()
    return path


def test_the_books_own_universe_is_a_benchmark_almost_anything_beats(tmp_path):
    """The measurement that was wrong, kept as a test. One company collapses and two
    hold flat: against the equal-weight mean of the universe both flat names show a
    positive abnormal return, and against a flat benchmark neither does."""
    flat = [100.0] * 120
    dying = [100.0 * (0.97 ** d) for d in range(120)]
    path = _book(tmp_path, {"AAA": flat, "BBB": list(flat), "CCC": dying},
                 bench=flat, changes=[(1, "2026-02-01 09:00:00", "status_change")])
    conn = db.get_connection(path)
    try:
        series = __import__("backtest")._series(conn)
        bars = event_signal.benchmark_series(conn, "XBI")
        against_universe = event_signal.abnormal(series, 1, "2026-02-01", 21)
        against_xbi = event_signal.abnormal(series, 1, "2026-02-01", 21, bars)
    finally:
        conn.close()
    assert against_universe > 0.02        # flattered by the dying constituent
    assert abs(against_xbi) < 1e-9        # and nil against a benchmark that is not


def test_a_missing_benchmark_falls_back_and_says_which_was_used(tmp_path):
    path = _book(tmp_path, {"AAA": [100.0] * 120}, bench=None,
                 changes=[(1, "2026-02-01 09:00:00", "status_change")])
    assert event_signal.build(path)["benchmark"] == "universe"
    (tmp_path / "x").mkdir()
    path2 = _book(tmp_path / "x", {"AAA": [100.0] * 120}, bench=[100.0] * 120,
                  changes=[(1, "2026-02-01 09:00:00", "status_change")])
    assert event_signal.build(path2)["benchmark"] == "XBI"


def test_the_placebo_is_drawn_on_the_days_the_events_fall_on(tmp_path):
    """Events are not spread evenly, so a placebo drawn across the whole history asks
    whether the quarter beat the decade rather than whether the event beat its week."""
    path = _book(tmp_path, {"AAA": [100.0] * 260, "BBB": [100.0] * 260},
                 bench=[100.0] * 260)
    conn = db.get_connection(path)
    try:
        series = __import__("backtest")._series(conn)
        bars = event_signal.benchmark_series(conn, "XBI")
        got = event_signal.placebo(series, 21, ["2026-02-01"] * 30, bars, draws=100)
    finally:
        conn.close()
    assert got["n"] > 0 and abs(got["mean"]) < 1e-9


def test_company_months_govern_thinness_rather_than_the_event_count(tmp_path):
    """Two events on one company a week apart share almost all of their forward window,
    so counting events would call a single company's quarter a sample."""
    many = [(1, f"2026-02-{d:02d} 09:00:00", "status_change") for d in range(1, 26)]
    path = _book(tmp_path, {"AAA": [100.0] * 260, "BBB": [100.0] * 260},
                 bench=[100.0] * 260, changes=many)
    out = event_signal.build(path)
    row = next(r for r in out["rows"] if r["change_type"] == "status_change")
    assert row["events"] >= event_signal.MIN_EVENTS     # plenty of events
    assert row["company_months"] == 1                   # and one independent cell
    assert row["windows"]["fwd_1m"]["thin"] is True
    assert out["reason"] and "company-months" in out["reason"]
