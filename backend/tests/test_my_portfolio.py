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
    monkeypatch.setattr(broker_t212, "summary", lambda: {"ok": True, "cash": 100.0})
    monkeypatch.setattr(my_portfolio, "CONFIG", tmp_path / "none.json")
    monkeypatch.setattr(my_portfolio, "_theme",
                        lambda t, isin, covered, groups: "Healthcare" if covered else "Index funds")
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


# --- performance -------------------------------------------------------------------
import datetime as dt

import pytest


def test_a_money_weighted_rate_and_its_period_return():
    d0, d1 = dt.date(2025, 1, 1), dt.date(2026, 1, 1)
    rate = my_portfolio.xirr([(d0, -100.0), (d1, 110.0)])
    assert rate == pytest.approx(0.10, abs=1e-3)
    half = my_portfolio._period(0.10, [(d0, -100.0)], dt.date(2025, 7, 2))
    assert half == pytest.approx(1.10 ** 0.5 - 1, abs=2e-3)


def test_deposits_go_in_and_withdrawals_come_out():
    flows = my_portfolio._cash_flows([
        {"type": "DEPOSIT", "amount": 100.0, "dateTime": "2026-07-10T09:00:00Z"},
        {"type": "WITHDRAW", "amount": -50.0, "dateTime": "2026-08-01T09:00:00Z"}])
    assert flows == [(dt.date(2026, 7, 10), -100.0), (dt.date(2026, 8, 1), 50.0)]


def test_cash_the_api_does_not_itemise_is_its_own_line(tmp_path, monkeypatch):
    path = str(tmp_path / "perf.db")
    db.init(path)
    conn = db.get_connection(path)
    for day, close in (("2026-07-10", 100.0), ("2026-10-09", 110.0)):
        for sym in ("^GSPC", "PPH"):
            conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES (?, ?, ?)",
                         (sym, day, close))
    conn.commit()
    conn.close()
    monkeypatch.setattr(my_portfolio, "_usd_per", lambda db_path, cur, day: 1.25)
    monkeypatch.setattr(broker_t212, "summary", lambda: {
        "ok": True, "currency": "GBP", "total": 1150.0, "cash": 150.0, "invested": 1000.0,
        "realised": 10.0, "unrealised": 40.0})
    monkeypatch.setattr(broker_t212, "history", lambda kind, pause=None: {"ok": True, "rows": {
        "transactions": [{"type": "DEPOSIT", "amount": 1000.0, "dateTime": "2026-07-10T00:00:00Z"}],
        "dividends": [{"amount": 5.0}], "orders": []}[kind]})
    monkeypatch.setattr(broker_t212, "positions", lambda: {"ok": True, "rows": [
        {"fx_effect": 15.0}]})
    out = my_portfolio.performance(path, today=dt.date(2026, 10, 9))
    assert out["gain"] == 150.0 and out["net_deposits"] == 1000.0
    split = out["split"]
    assert split["unrealised_price"] == 25.0 and split["unrealised_currency"] == 15.0
    assert split["not_itemised"] == pytest.approx(150.0 - (10 + 25 + 15 + 5))
    sp = [b for b in out["benchmarks"] if b["label"] == "S&P 500"][0]
    assert sp["value"] == pytest.approx(1100.0) and sp["return"] == pytest.approx(0.10, abs=1e-3)


def test_the_view_says_the_unitemised_cash_and_never_advises():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frontend"))
    import holdings_view as H
    html = H._summary({"currency": "GBP", "since": "2026-07-10", "total": 1150.0, "cash": 150.0,
                       "gain": 150.0, "return": 0.15, "split": {
                           "realised": 10.0, "unrealised_price": 25.0, "unrealised_currency": 15.0,
                           "dividends": 5.0, "not_itemised": 95.0},
                       "benchmarks": [{"label": "S&P 500", "gain": 100.0, "return": 0.10}]})
    assert "not itemised by the API +£95.00 (fees, interest" in html
    for word in ("buy now", "sell now", "should"):
        assert word not in html.lower()


def test_shares_transferred_in_are_money_put_in():
    flows = my_portfolio._transfers_in([
        {"order": {"side": "BUY"}, "fill": {"type": "FOP", "filledAt": "2026-07-31T10:00:00Z",
                                            "walletImpact": {"netValue": 171.64}}},
        {"order": {"side": "BUY"}, "fill": {"type": "TRADE", "filledAt": "2026-07-31T10:00:00Z",
                                            "walletImpact": {"netValue": 50.0}}}])
    assert flows == [(dt.date(2026, 7, 31), -171.64)]


def test_the_chart_is_a_unit_price_beside_the_benchmarks():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frontend"))
    import holdings_view as H
    html = H._chart({"dates": ["2026-07-10", "2026-07-11", "2026-08-01"],
                     "index": [100.0, 104.0, 97.5], "sp500_index": [100.0, 101.0, 105.5],
                     "pph_index": [100.0, 100.5, 103.1]})
    assert html.count("<path") == 3
    assert "You −2.5%" in html or "You -2.5%" in html
    assert "S&amp;P 500 +5.5%" in html and "PPH +3.1%" in html


def test_exposure_groups_by_the_users_themes_and_counts_the_small_positions():
    rows = [{"theme": "Rare earths", "value": 100.0, "cost": 150.0},
            {"theme": "Rare earths", "value": 50.0, "cost": 50.0},
            {"theme": "Utilities", "value": 1000.0, "cost": 800.0},
            {"theme": "Healthcare", "value": 850.0, "cost": 900.0}]
    e = my_portfolio.exposure(rows, 2000.0, {}, 200.0, "earmarked for fees")
    assert e["cash_share"] == pytest.approx(0.5) and e["cash_note"] == "earmarked for fees"
    rare = [t for t in e["themes"] if t["theme"] == "Rare earths"][0]
    assert rare["share"] == pytest.approx(150 / 2000) and rare["return"] == pytest.approx(-0.25)
    assert e["top3_share"] == pytest.approx(1950 / 2000)
    assert e["small"] == {"threshold": 200.0, "count": 2, "value": 150.0,
                          "share": pytest.approx(150 / 2000)}


def test_the_users_grouping_wins_over_the_sector(monkeypatch):
    groups = {"Rare earths": ["MP_US_EQ"]}
    assert my_portfolio._theme("MP_US_EQ", "X", False, groups) == "Rare earths"
    assert my_portfolio._theme("AZNl_EQ", "Y", True, groups) == "Healthcare"
