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
# Enterprise value takes the most recent balance sheet the filer has published, which
# is the Q1 2026 10-Q, not the FY2025 10-K the revenue comes from. Trailing revenue
# against current net debt is the intended pairing: net debt moves every quarter and an
# EV built from a year-old one is stale by construction.
LLY_CASH = 5282300000     # 2026-03-31, vs 7.268bn at the 2025 fiscal year end
LLY_DEBT = 43370400000    # 2026-03-31, vs 42.503bn at the 2025 fiscal year end


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


def test_comps_trend_aligns_companies_on_shared_year_labels(tmp_path, monkeypatch):
    facts = {"LLY": _facts("companyfacts_lly.json"), "NVO": _facts("companyfacts_nvo.json")}
    monkeypatch.setattr(FinancialsEdgarFetcher, "fetch", lambda self: facts[self.ticker])
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    FinancialsEdgarFetcher("LLY", db_file).run()
    FinancialsEdgarFetcher("NVO", db_file).run()

    trend = comps.comps_trend(db_file)
    labels = trend["labels"]
    assert labels and all(lbl.startswith("FY") for lbl in labels)
    by = {c["ticker"]: c for c in trend["companies"]}
    assert "LLY" in by and "NVO" in by          # both filers with financials appear
    assert "ABBV" not in by                      # a company with no financials is left out
    lly = by["LLY"]
    assert len(lly["revenue_growth"]) == len(labels)   # every series aligns to the labels
    assert len(lly["net_margin"]) == len(labels)
    assert lly["revenue_growth"][-1] is not None       # the latest year is populated
    assert lly["net_margin"][-1] is not None


def test_comps_no_data_all_null(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    rows = {r["ticker"]: r for r in comps.build_comps(db_file)}
    abbv = rows["ABBV"]
    assert abbv["revenue"] is None
    assert abbv["market_cap"] is None
    assert abbv["ev_sales"] is None
