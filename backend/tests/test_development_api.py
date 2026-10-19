"""The two development routes: shapes, the 404s, a refusal as data, and the headline
value the same with the view read, unread, or the module gone."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
import development as D
import forecast_view as V
import main
from tests.test_development import _book, _trial, big  # noqa: F401  the fixture


@pytest.fixture
def client(tmp_path, big, monkeypatch):  # noqa: F811
    path, conn = _book(tmp_path)
    _trial(conn, "NCT00000001", 7)
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (9, 2, 'notyours', 0)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", Path(path))
    return TestClient(main.app), path


def test_the_asset_route_returns_the_gate_the_ladder_and_the_sources(client):
    http, _ = client
    body = http.get("/companies/abbv/forecast/7/development").json()
    assert body["ok"] is True and body["ticker"] == "ABBV" and body["price_year"] == 2018
    assert {"gate", "ladder", "stages", "outside", "next_12m", "sources", "fx",
            "paid_note"} <= set(body)
    assert {"p", "success_leg", "cost", "net", "breakeven_p", "funds", "high",
            "net_per_share"} <= set(body["gate"])
    assert body["ladder"]["label"] == "after later trial costs"
    assert any("Sertkaya" in s for s in body["sources"])


def test_unknown_tickers_and_other_companies_assets_are_404(client):
    http, _ = client
    assert http.get("/companies/ZZZZ/forecast/7/development").status_code == 404
    assert http.get("/companies/ABBV/forecast/9/development").status_code == 404
    assert http.get("/companies/ZZZZ/development").status_code == 404


def test_a_refusal_is_a_200_with_its_reason(client, monkeypatch):
    http, path = client
    conn = db.get_connection(path)
    conn.execute("UPDATE assets SET generic_name = 'Investigational vaccine' WHERE id = 7")
    conn.commit()
    conn.close()
    response = http.get("/companies/ABBV/forecast/7/development")
    assert response.status_code == 200
    assert response.json()["ok"] is False and response.json()["reason"] == "vaccine"


def test_the_company_route_lists_failing_gates_first_and_reconciles(client):
    http, _ = client
    body = http.get("/companies/ABBV/development").json()
    assert set(body) >= {"failing", "rows", "refused", "reconciliation", "currency"}
    assert [r["asset_id"] for r in body["failing"] + body["rows"]] == [7]


def test_the_value_is_the_same_read_unread_or_without_the_module(client, monkeypatch):
    """The headline: the sum of the parts, equity per share and the 12-month value are
    the same before and after the view is read, and with the module unimportable."""
    http, path = client

    def headline():
        sotp = V.company_verdict(path, "ABBV")["sotp"]
        return {k: sotp.get(k) for k in ("enterprise", "equity_per_share", "forward_12m")}
    before = headline()
    http.get("/companies/ABBV/development")
    http.get("/companies/ABBV/forecast/7/development")
    assert headline() == before
    monkeypatch.setitem(sys.modules, "development", None)
    assert headline() == before
    assert V.company_verdict(path, "ABBV")["sotp"]["equity_per_share"] == \
        before["equity_per_share"]
