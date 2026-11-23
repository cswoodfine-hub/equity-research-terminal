"""A recorded price that was not the close of its session is corrected beside the
record, never in it, and the calls are scored from both (price_record.py)."""

import datetime as dt
import json

import pytest

import call_log
import db
import history
import price_record

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("ER_TOOL_CALL_LOG", "1")
    path = str(tmp_path / "record.db")
    db.init(path)
    conn = db.get_connection(path)
    for t in TICKERS:
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (t, t + " Inc"))
    conn.commit()
    conn.close()
    return path


def _prices(conn, ticker, rows):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    for day, close in rows:
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval) VALUES"
                     " (?, ?, ?, '1d')", (cid, day, close))


def _snapshot(conn, ticker, captured, as_of, close, kind="live"):
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, captured_at, payload)"
        " VALUES ('prices', 'company', ?, ?, ?)",
        (ticker, captured, json.dumps({"ticker": ticker, "as_of": as_of, "close": close,
                                       "fetch_kind": kind})))


def _fair(price, upside, target=None, price_date=None):
    return {"ok": True, "close": price, "price_date": price_date,
            "equity_per_share": price * (1 + upside),
            "rating": {"ok": True, "close": price, "value_today": price * (1 + upside),
                       "forward_12m": price * (1 + upside), "upside_12m": upside,
                       "rating": "Buy"},
            "lenses": [{"key": "targets", "mid": target}] if target else []}


def test_a_session_is_settled_only_once_the_series_has_moved_past_it(book):
    conn = db.get_connection(book)
    _prices(conn, "AAA", [("2026-01-02", 100.0), ("2026-01-05", 104.0)])
    conn.commit()
    assert price_record.settled_close(conn, "AAA", "2026-01-02") == 100.0
    # The newest bar may still be a session in progress on an older book.
    assert price_record.settled_close(conn, "AAA", "2026-01-05") is None
    assert price_record.settled_close(conn, "AAA", "2026-01-03") is None   # no bar
    conn.close()


def test_a_snapshot_filed_mid_session_is_found_and_one_at_the_close_is_not(book):
    conn = db.get_connection(book)
    _prices(conn, "AAA", [("2026-01-02", 100.0), ("2026-01-05", 104.0), ("2026-01-06", 105.0)])
    _snapshot(conn, "AAA", "2026-01-02 15:13:00", "2026-01-02", 97.5)    # the last trade
    _snapshot(conn, "AAA", "2026-01-03 14:00:00", "2026-01-02", 100.0)   # the close, a day on
    _snapshot(conn, "AAA", "2026-01-06 15:00:00", "2026-01-06", 101.0)   # not settled yet
    conn.commit()
    found = price_record.find(conn)
    conn.close()
    assert [(f["kind"], f["price_date"], f["recorded"], f["settled"]) for f in found] == [
        ("snapshot", "2026-01-02", 97.5, 100.0)]
    assert found[0]["ref_key"] == "AAA|2026-01-02 15:13:00"


def test_the_ledger_is_appended_once_and_the_record_is_left_as_it_was(book):
    call_log.record(book, as_of="2026-01-02", tickers=["AAA"],
                    fair_fn=lambda t: _fair(97.5, 0.2, price_date="2026-01-02"),
                    stakes_fn=lambda t: {})
    conn = db.get_connection(book)
    _prices(conn, "AAA", [("2026-01-02", 100.0), ("2026-01-05", 104.0)])
    _snapshot(conn, "AAA", "2026-01-02 15:13:00", "2026-01-02", 97.5)
    conn.commit()
    conn.close()

    first = price_record.record(book)
    second = price_record.record(book)
    assert first["written"] == 2 and first["by_kind"] == {"snapshot": 1, "model_call": 1}
    assert second["written"] == 0 and second["found"] == 2

    conn = db.get_connection(book)
    call = conn.execute("SELECT price FROM model_calls WHERE ticker = 'AAA'").fetchone()
    snap = json.loads(conn.execute("SELECT payload FROM snapshots").fetchone()["payload"])
    rows = conn.execute("SELECT kind, ref_key, recorded, settled FROM price_corrections"
                        " ORDER BY kind").fetchall()
    conn.close()
    assert call["price"] == 97.5 and snap["close"] == 97.5          # untouched
    assert [(r["kind"], r["ref_key"]) for r in rows] == [
        ("model_call", "AAA|2026-01-02"), ("snapshot", "AAA|2026-01-02 15:13:00")]
    assert all(r["recorded"] == 97.5 and r["settled"] == 100.0 for r in rows)
    summary = price_record.summary(book)
    assert summary["rows"] == 2 and summary["sessions"] == 1
    assert summary["median_gap"] == pytest.approx(0.025)


def test_the_ledger_travels_with_the_history(book, tmp_path):
    conn = db.get_connection(book)
    _prices(conn, "AAA", [("2026-01-02", 100.0), ("2026-01-05", 104.0)])
    _snapshot(conn, "AAA", "2026-01-02 15:13:00", "2026-01-02", 97.5)
    conn.commit()
    conn.close()
    price_record.record(book)
    out = tmp_path / "history"
    written = history.export(book, out)
    assert written["price_corrections"] == 1
    line = json.loads((out / "price_corrections.ndjson").read_text().splitlines()[0])
    assert line["ref_key"] == "AAA|2026-01-02 15:13:00" and line["settled"] == 100.0


def test_calls_are_scored_from_the_recorded_price_and_from_the_close(book):
    """Six calls on one day, each recorded off a last trade that sat 10% under the
    close for the names that then did worst and 10% over it for those that did best.
    From the recorded price the upside looks blind; from the close it ranks the month."""
    upsides = [-0.3, -0.1, 0.05, 0.1, 0.2, 0.4]
    skew = [0.70, 0.90, 1.05, 1.10, 1.20, 1.40]      # recorded price over the close
    for t, up, k in zip(TICKERS, upsides, skew):
        recorded = 100.0 * k
        row = _fair(recorded, 0.0, 100.0, price_date="2026-01-02")
        row["rating"]["forward_12m"] = 100.0 * (1 + up)
        row["rating"]["upside_12m"] = 100.0 * (1 + up) / recorded - 1     # nil for all
        call_log.record(book, as_of="2026-01-02", tickers=[t],
                        fair_fn=lambda _t, row=row: row, stakes_fn=lambda _t: {})
    conn = db.get_connection(book)
    for t, up in zip(TICKERS, upsides):
        _prices(conn, t, [("2026-01-02", 100.0), ("2026-02-01", 100.0 * (1 + up))])
    for day in ("2026-01-02", "2026-02-01"):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES ('XBI', ?, 50)",
                     (day,))
    conn.commit()
    conn.close()

    out = call_log.score(book, today=dt.date(2026, 3, 1))
    month = out["horizons"]["1m"]
    assert out["price_basis"]["repriced_calls"] == 6
    assert out["price_basis"]["not_yet_settled"] == 0
    assert month["settled"]["repriced"] == 6
    assert month["settled"]["model"]["ic"] == pytest.approx(1.0)
    # Recorded: every upside is nil and every return from the recorded price is nil,
    # so there is nothing to rank and no score is claimed.
    assert month["model"]["ic"] is None


def test_a_call_made_at_the_close_scores_the_same_on_both_bases(book):
    upsides = [-0.3, -0.1, 0.05, 0.1, 0.2, 0.4]
    for t, up in zip(TICKERS, upsides):
        call_log.record(book, as_of="2026-01-02", tickers=[t],
                        fair_fn=lambda _t, up=up: _fair(100.0, up, 100.0 * (1 - up),
                                                        price_date="2026-01-02"),
                        stakes_fn=lambda _t: {})
    conn = db.get_connection(book)
    for t, up in zip(TICKERS, upsides):
        _prices(conn, t, [("2026-01-02", 100.0), ("2026-02-01", 100.0 * (1 + up))])
    for day in ("2026-01-02", "2026-02-01"):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES ('XBI', ?, 50)",
                     (day,))
    conn.commit()
    conn.close()
    out = call_log.score(book, today=dt.date(2026, 3, 1))
    month = out["horizons"]["1m"]
    assert out["price_basis"]["repriced_calls"] == 0
    assert month["settled"]["model"] == month["model"]
    assert month["settled"]["street"] == month["street"]
