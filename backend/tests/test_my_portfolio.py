"""The user's own holdings beside the model's view (my_portfolio.py, fetchers/broker_t212.py)."""

import db
import my_portfolio
import response_cache
from fetchers import broker_t212


def test_a_listing_maps_to_the_books_ticker():
    assert broker_t212.universe_ticker("NVO_US_EQ") == "NVO"
    assert broker_t212.universe_ticker("AZNl_EQ") == "AZN"          # London
    assert broker_t212.universe_ticker("VWRPl_EQ") == "VWRP"
    assert broker_t212.universe_ticker("BLBX_US_EQ") == "BLBX"


def test_no_key_is_a_soft_answer(monkeypatch):
    monkeypatch.setenv("T212_API_KEY", "")
    assert broker_t212.check()["ok"] is False
    assert my_portfolio.mine(None)["ok"] is False


def test_a_covered_holding_carries_the_models_latest_call(tmp_path, monkeypatch):
    path = str(tmp_path / "p.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('AZN', 'AstraZeneca')")
    for day, up in (("2026-10-08", 0.17), ("2026-10-09", 0.20)):
        conn.execute("INSERT INTO model_calls (as_of, ticker, fair_value, upside_12m, rating)"
                     " VALUES (?, 'AZN', 180, ?, 'Buy')", (day, up))
    conn.commit()
    conn.close()
    monkeypatch.setattr(broker_t212, "positions", lambda: {"ok": True, "currency": "GBP", "rows": [
        {"t212_ticker": "AZNl_EQ", "ticker": "AZN", "name": "AstraZeneca", "value": 900.0},
        {"t212_ticker": "VWRPl_EQ", "ticker": "VWRP", "name": "FTSE All-World", "value": 2000.0}]})
    out = my_portfolio.mine(path)
    assert out["covered"] == 1 and out["positions"] == 2
    azn = [r for r in out["rows"] if r["ticker"] == "AZN"][0]
    assert azn["model"]["upside_12m"] == 0.20 and azn["model"]["as_of"] == "2026-10-09"
    assert [r for r in out["rows"] if r["ticker"] == "VWRP"][0]["model"] is None


def test_the_holdings_are_never_cached():
    assert not response_cache.cacheable("/portfolio/mine", "")
