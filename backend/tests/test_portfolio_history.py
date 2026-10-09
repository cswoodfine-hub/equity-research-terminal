"""The account rebuilt day by day from its fills and cash (portfolio_history.py)."""

import datetime as dt

import portfolio_history as PH
from fetchers import broker_t212


def test_a_listing_is_found_by_market_then_by_isin(monkeypatch):
    assert PH._candidates("AZNl_EQ", "GB0009895292") == ["AZN.L"]
    assert PH._candidates("NEO_CA_EQ", None) == ["NEO.TO"]
    monkeypatch.setattr(PH, "_json", lambda url: {"quotes": [{"symbol": "HUMA"}]})
    assert PH._candidates("AHAC_US_EQ", "US44730L1044") == ["AHAC", "HUMA"]


def test_a_series_in_the_wrong_currency_or_far_from_the_price_is_refused(monkeypatch):
    table = {"VUAA.L": ({"2026-10-09": 120.0}, "USD"), "AHAC": ({"2026-10-09": 9.0}, "USD"),
             "HUMA": ({"2026-10-09": 0.70}, "USD")}
    monkeypatch.setattr(PH, "closes", lambda symbol, start: table.get(symbol, ({}, None)))
    monkeypatch.setattr(PH, "_candidates", lambda t, isin: ["AHAC", "HUMA"])
    symbol, _series = PH.resolve("AHAC_US_EQ", "x", "USD", 0.68, dt.date(2026, 7, 1))
    assert symbol == "HUMA"                                  # AHAC is 13 times the price
    monkeypatch.setattr(PH, "_candidates", lambda t, isin: ["VUAA.L"])
    assert PH.resolve("VUAGl_EQ", "x", "GBP", 100.0, dt.date(2026, 7, 1))[0] is None


def test_the_rebuilt_value_follows_cash_shares_and_prices(monkeypatch):
    monkeypatch.setattr(broker_t212, "summary", lambda: {"ok": True, "currency": "USD",
                                                         "total": 1100.0})
    monkeypatch.setattr(broker_t212, "positions", lambda: {"ok": True, "rows": [
        {"t212_ticker": "AAA_US_EQ", "current_price": 12.0}]})
    monkeypatch.setattr(broker_t212, "history", lambda kind, pause=None: {"ok": True, "rows": {
        "transactions": [{"type": "DEPOSIT", "amount": 1000.0, "dateTime": "2026-07-01T09:00:00Z"}],
        "orders": [{"order": {"ticker": "AAA_US_EQ", "side": "BUY", "instrument": {
                        "isin": "X", "currency": "USD", "name": "Aaa"}},
                    "fill": {"type": "TRADE", "filledAt": "2026-07-02T15:00:00Z", "quantity": 50,
                             "walletImpact": {"netValue": 500.0}}}],
        "dividends": []}[kind]})
    prices = {"AAA": ({"2026-07-02": 10.0, "2026-07-03": 12.0}, "USD"),
              "^GSPC": ({"2026-07-01": 100.0, "2026-07-03": 110.0}, "USD")}
    monkeypatch.setattr(PH, "closes", lambda symbol, start: prices.get(symbol, ({}, None)))
    monkeypatch.setattr(PH, "_candidates", lambda t, isin: ["AAA"])
    out = PH.build(today=dt.date(2026, 7, 3))
    assert out["ok"] and out["dates"] == ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert out["value"] == [1000.0, 1000.0, 1100.0]          # 500 cash + 50 x 12
    assert out["contributions"] == [1000.0, 1000.0, 1000.0]
    assert out["sp500"][-1] == 1100.0 and out["left_out"] == []


def test_money_put_in_moves_the_value_not_the_unit_price(monkeypatch):
    monkeypatch.setattr(PH, "closes", lambda symbol, start: ({"2026-07-01": 50.0,
                                                              "2026-07-02": 50.0,
                                                              "2026-07-03": 55.0}, "USD"))
    out = {"dates": ["2026-07-01", "2026-07-02", "2026-07-03"],
           "value": [1000.0, 2000.0, 2200.0],          # a 1,000 deposit, then a 10% day
           "contributions": [1000.0, 2000.0, 2000.0]}
    ix = PH._indices(out, {"2026-07-01": 50.0, "2026-07-02": 50.0, "2026-07-03": 55.0},
                     lambda day: 1.0, None)
    assert ix["index"] == [100.0, 100.0, 110.0] and ix["sp500_index"][-1] == 110.0
