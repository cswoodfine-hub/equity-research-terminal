"""The model's calls, recorded as made and scored as the market answers (call_log.py)."""

import datetime as dt

import pytest

import call_log
import db
import history

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("ER_TOOL_CALL_LOG", "1")
    path = str(tmp_path / "calls.db")
    db.init(path)
    conn = db.get_connection(path)
    for t in TICKERS:
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (t, t + " Inc"))
    conn.commit()
    conn.close()
    return path


def _fair(price, upside, target=None):
    return {"ok": True, "equity_per_share": price * (1 + upside), "price_date": "2026-01-02",
            "rating": {"ok": True, "close": price, "value_today": price * (1 + upside),
                       "forward_12m": price * (1 + upside), "upside_12m": upside,
                       "rating": "Buy" if upside > 0 else "Sell"},
            "lenses": [{"key": "targets", "low": target, "mid": target, "high": target}]
            if target else []}


def _stakes(p_gate):
    # Legs in $ millions, 100 million diluted shares: the stake's own swing a share is $8.
    return {"diluted_shares": 100e6, "priced": [
        {"priced": True, "id": 7, "asset_id": 70, "asset_name": "Drugx", "gate": "p3_to_nda",
         "gate_label": "Phase 3 readout", "gate_trial": "NCT1", "expected_date": "2026-06",
         "p_gate": p_gate, "rnpv_now": 500.0, "rnpv_success": 800.0, "rnpv_failure": 0.0,
         "per_share": 8.0, "swing": 800.0}]}


def test_a_day_is_recorded_once_and_never_rewritten(book):
    out = call_log.record(book, as_of="2026-01-02", tickers=["AAA"],
                          fair_fn=lambda t: _fair(100.0, 0.2, 120.0),
                          stakes_fn=lambda t: _stakes(0.6))
    assert (out["calls"], out["gates"], out["kept"]) == (1, 1, 0)
    again = call_log.record(book, as_of="2026-01-02", tickers=["AAA"],
                            fair_fn=lambda t: _fair(100.0, -0.5), stakes_fn=lambda t: _stakes(0.1))
    assert (again["calls"], again["gates"], again["kept"]) == (0, 0, 1)
    call = call_log.history(book, "AAA")[0]
    assert call["upside_12m"] == 0.2 and call["target_mid"] == 120.0 and call["rating"] == "Buy"
    conn = db.get_connection(book)
    gate = dict(conn.execute("SELECT * FROM gate_calls").fetchone())
    conn.close()
    assert gate["p_gate"] == 0.6 and gate["per_share_now"] == 5.0 \
        and gate["per_share_success"] == 8.0


def test_a_company_the_model_cannot_value_is_left_out(book):
    out = call_log.record(book, as_of="2026-01-02", tickers=["AAA", "BBB"],
                          fair_fn=lambda t: {"ok": False} if t == "BBB" else _fair(10.0, 0.1),
                          stakes_fn=lambda t: {})
    assert out["calls"] == 1 and call_log.history(book, "BBB") == []


def test_off_when_the_environment_says_so(book, monkeypatch):
    monkeypatch.setenv("ER_TOOL_CALL_LOG", "0")
    assert call_log.record(book, tickers=["AAA"]) == {"skipped": "ER_TOOL_CALL_LOG=0"}


def _prices(conn, ticker, rows):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]
    for day, close in rows:
        conn.execute("INSERT INTO prices (company_id, as_of, close, interval) VALUES"
                     " (?, ?, ?, '1d')", (cid, day, close))


def test_upside_that_ranks_the_returns_scores_one_and_a_reversed_street_minus_one(book):
    # Six calls on one day; each stock's return over the month is its upside, PPH flat.
    upsides = [-0.3, -0.1, 0.05, 0.1, 0.2, 0.4]
    for t, up in zip(TICKERS, upsides):
        call_log.record(book, as_of="2026-01-02", tickers=[t],
                        fair_fn=lambda _t, up=up: _fair(100.0, up, 100.0 * (1 - up)),
                        stakes_fn=lambda _t: {})
    conn = db.get_connection(book)
    for t, up in zip(TICKERS, upsides):
        _prices(conn, t, [("2026-01-02", 100.0), ("2026-02-01", 100.0 * (1 + up))])
    for day in ("2026-01-02", "2026-02-01"):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES ('PPH', ?, 50)",
                     (day,))
    conn.commit()
    conn.close()
    out = call_log.score(book, today=dt.date(2026, 3, 1))
    month = out["horizons"]["1m"]
    assert month["model"]["ic"] == pytest.approx(1.0)
    assert month["street"]["ic"] == pytest.approx(-1.0)
    assert month["model"]["hit_rate"] == 1.0 and month["model"]["top_minus_bottom"] > 0
    # A horizon not yet passed is not scored, and says when it will be.
    year = out["horizons"]["12m"]
    assert year["model"]["ic"] is None and year["first_scored"] == "2027-01-02"


def test_a_window_with_no_close_near_its_end_is_not_scored(book):
    call_log.record(book, as_of="2026-01-02", tickers=["AAA"],
                    fair_fn=lambda t: _fair(100.0, 0.2), stakes_fn=lambda t: {})
    conn = db.get_connection(book)
    _prices(conn, "AAA", [("2026-01-02", 100.0), ("2026-01-10", 130.0)])
    conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES ('PPH', '2026-01-02', 50)")
    conn.commit()
    conn.close()
    out = call_log.score(book, today=dt.date(2026, 3, 1))
    assert out["horizons"]["1m"]["model"]["calls"] == 0


def test_a_gate_is_scored_on_the_last_call_before_its_readout(book):
    for day, p in (("2026-01-02", 0.5), ("2026-02-02", 0.9)):
        call_log.record(book, as_of=day, tickers=["AAA"],
                        fair_fn=lambda t: _fair(100.0, 0.1), stakes_fn=lambda t, p=p: _stakes(p))
    conn = db.get_connection(book)
    cid = conn.execute("SELECT id FROM companies WHERE ticker = 'AAA'").fetchone()[0]
    conn.execute("INSERT INTO trial_readouts (company_id, drug, phase, outcome, event_date)"
                 " VALUES (?, 'Drugx', 3, 'positive', '2026-03-01')", (cid,))
    conn.commit()
    conn.close()
    gates = call_log.score(book, today=dt.date(2026, 4, 1))["gates"]
    assert gates["resolved"] == 1 and gates["brier"] == pytest.approx((0.9 - 1) ** 2)
    band = [b for b in gates["bands"] if b["gates"]][0]
    assert band["odds"] == "80% to 100%" and band["passed"] == 1.0


def test_the_history_export_carries_the_calls(book, tmp_path):
    call_log.record(book, as_of="2026-01-02", tickers=["AAA"],
                    fair_fn=lambda t: _fair(100.0, 0.2), stakes_fn=lambda t: _stakes(0.6))
    written = history.export(book, tmp_path / "hist")
    assert written["model_calls"] == 1 and written["gate_calls"] == 1


def test_without_the_stakes_own_figure_the_legs_are_millions_over_the_shares(book):
    stakes = _stakes(0.6)
    for key in ("per_share", "swing"):
        stakes["priced"][0].pop(key)
    call_log.record(book, as_of="2026-01-02", tickers=["AAA"],
                    fair_fn=lambda t: _fair(100.0, 0.2), stakes_fn=lambda t: stakes)
    conn = db.get_connection(book)
    gate = dict(conn.execute("SELECT * FROM gate_calls").fetchone())
    conn.close()
    assert gate["per_share_now"] == 5.0 and gate["per_share_success"] == 8.0

