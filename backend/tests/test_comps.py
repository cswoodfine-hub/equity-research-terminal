"""build_comps over a seeded DB, no network.

Financials are loaded through the real fetcher with the Yahoo/EDGAR fetch monkeypatched
to fixtures; the price is inserted directly. Asserts valuation ratios resolve for the
US filer and are left null for the foreign (DKK, no shares) filer.
"""

import json
from pathlib import Path

import pytest

import comps
import db
import seed
from fetchers.financials_edgar import FinancialsEdgarFetcher

FIXTURES = Path(__file__).parent / "fixtures"
LLY_CLOSE = 1000.0
LLY_SHARES = 941741406
LLY_NET_INCOME = 20640000000
LLY_REVENUE = 65179000000
LLY_CASH = 7268000000
LLY_DEBT = 42503000000


def _facts(name):
    return json.loads((FIXTURES / name).read_text())


def _seed_prices(db_file, ticker, close, currency):
    conn = db.get_connection(db_file)
    try:
        cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
        conn.execute(
            "INSERT INTO prices (company_id, as_of, close, source) VALUES (?, ?, ?, 'yahoo_chart')",
            (cid, "2026-07-17", close),
        )
        conn.execute(
            """
            INSERT INTO snapshots (source, entity_type, entity_key, payload)
            VALUES ('prices', 'company', ?, ?)
            """,
            (ticker, json.dumps({"currency": currency, "fetch_kind": "live"})),
        )
        conn.commit()
    finally:
        conn.close()


def test_comps_us_filer_full_foreign_gapped(tmp_path, monkeypatch):
    facts = {"LLY": _facts("companyfacts_lly.json"), "NVO": _facts("companyfacts_nvo.json")}
    monkeypatch.setattr(FinancialsEdgarFetcher, "fetch", lambda self: facts[self.ticker])

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    FinancialsEdgarFetcher("LLY", db_file).run()
    FinancialsEdgarFetcher("NVO", db_file).run()
    _seed_prices(db_file, "LLY", LLY_CLOSE, "USD")   # USD price matches USD financials
    _seed_prices(db_file, "NVO", 90.0, "USD")        # USD price vs DKK financials -> no mktcap

    rows = {r["ticker"]: r for r in comps.build_comps(db_file)}
    lly, nvo = rows["LLY"], rows["NVO"]

    # US filer: full valuation stack resolves.
    assert lly["currency"] == "USD"
    assert lly["revenue"] == LLY_REVENUE
    assert lly["revenue_growth"] == pytest.approx(65179000000 / 45043000000 - 1)
    assert lly["market_cap"] == pytest.approx(LLY_CLOSE * LLY_SHARES)
    assert lly["pe"] == pytest.approx(LLY_CLOSE * LLY_SHARES / LLY_NET_INCOME)
    expected_ev = LLY_CLOSE * LLY_SHARES + LLY_DEBT - LLY_CASH
    assert lly["ev_sales"] == pytest.approx(expected_ev / LLY_REVENUE)

    # Foreign filer: operating metrics present, USD valuation ratios null.
    assert nvo["currency"] == "DKK"
    assert nvo["revenue"] == 309064000000
    assert nvo["revenue_growth"] is not None
    assert nvo["market_cap"] is None
    assert nvo["pe"] is None
    assert nvo["ev_sales"] is None


def test_comps_no_data_all_null(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    rows = {r["ticker"]: r for r in comps.build_comps(db_file)}
    abbv = rows["ABBV"]
    assert abbv["revenue"] is None
    assert abbv["market_cap"] is None
    assert abbv["ev_sales"] is None
