"""The Comps tab's valuation payload, over a seeded database, no network.

Never the real book. All seventy companies are seeded from the CSV and most carry no data,
which is itself a case: every null needs its reason. Around them, one company per shape
the view has to get right: a US filer whose cover count is an exception (LLY), an IFRS
filer in kroner with no share count (NVO), a clinical company with no debt line (CRSP), a
company with cash and no cash flow (SANA), a stale price (PFE), euro rows under a dollar
company record (BNTX), a 20-F filer with no recorded standard (ARGX), a September year
(ARWR), a cover count well above the diluted count (VRTX), a 2012 cover count (REGN), a
diluted count in thousands (IOVA), a workbook filer with attributable profit (ROG), product
guidance (GILD, SRPT) and a consensus sign change (GILD).
"""

import datetime as dt
import json
import shutil
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cashflow
import comps_valuation as cv
import db
import main
import response_cache
import seed
from fetchers.financials_edgar import FinancialsEdgarFetcher

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 9, 29)
RATES = {"USD": 1.0, "EUR": 1.1378, "DKK": 0.15221, "CHF": 1.20224, "GBP": 1.326339}
LLY_PRICE = 1184.78

RECORD_KEYS = {
    "ticker", "name", "engine", "stage", "country", "region", "listing", "filer",
    "reporting_currency", "row_currency", "fiscal_year_end_month", "themes", "areas",
    "market", "ev", "periods", "growth", "street", "risk", "healthcare", "model", "flags",
    "na", "lineage", "history", "screen_extras", "detail", "error",
}


# --- seeding -------------------------------------------------------------------------
def _facts(name):
    return json.loads((FIXTURES / name).read_text())


def _cid(conn, ticker):
    return conn.execute("SELECT id FROM companies WHERE ticker = ?", (ticker,)).fetchone()[0]


def _fin(conn, ticker, metric, kind, end, value, unit="USD", months=None,
         source="edgar_companyfacts"):
    conn.execute(
        """INSERT OR REPLACE INTO financials (company_id, period_end, period_type, metric,
               value, unit, fiscal_year, fiscal_period, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_cid(conn, ticker), end, kind, metric, value, unit, int(end[:4]),
         months or ("12M" if kind == "FY" else None), source))


def _price(conn, ticker, day, close):
    conn.execute(
        "INSERT INTO prices (company_id, as_of, close, high, low, source, interval)"
        " VALUES (?, ?, ?, ?, ?, 'yahoo_chart', '1d')",
        (_cid(conn, ticker), day, close, close * 1.01, close * 0.99))


def _snapshot(conn, source, ticker, payload, captured_at="2026-09-28 22:00:00"):
    conn.execute(
        "INSERT INTO snapshots (source, entity_type, entity_key, captured_at, payload)"
        " VALUES (?, 'company', ?, ?, ?)", (source, ticker, captured_at, json.dumps(payload)))


def _estimate(conn, ticker, metric, period, value, source, as_of, low=None, high=None,
              note=None, fx_basis=None, currency="USD"):
    conn.execute(
        """INSERT INTO consensus_estimates (company_id, metric, period, value, low, high,
               currency, source, as_of, note, fx_basis)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_cid(conn, ticker), metric, period, value, low, high, currency, source, as_of,
         note, fx_basis))


def _eps(conn, ticker, period, value, low, high, n, as_of="2026-09-23"):
    _estimate(conn, ticker, "EPS", period, value, "nasdaq", as_of, low, high,
              f"{n} estimates, per US-listed share")


def _weekdays_back(last: dt.date, count: int) -> list:
    days, day = [], last
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= dt.timedelta(days=1)
    return sorted(days)


def _seed(path):
    conn = db.get_connection(path)
    try:
        for base, rate in RATES.items():
            conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of) VALUES (?, 'USD', ?, ?)",
                         (base, rate, "2026-09-28"))

        # LLY: the cover count is the named exception, so the diluted count is used.
        _price(conn, "LLY", "2026-09-25", 1180.0)
        _price(conn, "LLY", "2026-09-28", LLY_PRICE)
        _snapshot(conn, "prices", "LLY", {"currency": "USD", "fetch_kind": "live"})
        _snapshot(conn, "consensus_nasdaq", "LLY", {"estimates": 5, "fetch_kind": "live"},
                  "2026-09-28 05:47:36")
        _eps(conn, "LLY", "FY2026", 36.62, 35.0, 38.0, 9)
        _eps(conn, "LLY", "FY2026", 36.10, 35.0, 38.0, 9, as_of="2026-09-17")
        _eps(conn, "LLY", "FY2027", 45.0, 42.0, 48.0, 9)
        _eps(conn, "LLY", "FY2028", 52.0, 49.0, 55.0, 8)
        _estimate(conn, "LLY", "PriceTarget", "12M", 1381.0, "nasdaq", "2026-09-24", 1000.0,
                  1500.0, "19 buy, 4 hold, 0 sell; per US-listed share")
        for as_of, value in (("2026-02-04", 81.5e9), ("2026-04-30", 83.5e9),
                             ("2026-08-05", 86.0e9)):
            _estimate(conn, "LLY", "Revenue", "FY2026", value, "guidance", as_of,
                      value - 1e9, value + 1e9,
                      "Increased 2026 full-year revenue guidance to be in the range of "
                      "$85.0 billion to $87.0 billion")
        conn.execute(
            """INSERT INTO other_claims (company_id, item, label, value, sign, unit, as_of,
                   basis, source)
               VALUES (?, 'pension_deficit', 'pension and post-employment deficit', 1500.0,
                       -1, 'USD', '20251231', 'filed', 'test')""", (_cid(conn, "LLY"),))
        asset = conn.execute(
            "INSERT INTO assets (owner_company_id, generic_name, is_marketed) VALUES (?, ?, 1)",
            (_cid(conn, "LLY"), "tirzepatide")).lastrowid
        conn.execute("INSERT INTO assumptions (asset_id, key, value) VALUES (?, 'peak_sales', 1)",
                     (asset,))

        # NVO: kroner, no share count, a constant-currency growth guide.
        _price(conn, "NVO", "2026-09-28", 38.71)
        conn.execute("INSERT OR REPLACE INTO adr_ratios (ticker, ordinary_per_adr) VALUES ('NVO', 1.0)")
        _estimate(conn, "NVO", "RevenueGrowth", "FY2026", -3.0, "guidance", "2026-08-04",
                  -6.0, 0.0, "Adjusted sales growth is now expected to be 0% to -6% at CER.",
                  "cer", None)

        # CRSP: clinical, cash and investments, burning cash, no debt line.
        _fin(conn, "CRSP", "Revenues", "FY", "2025-12-31", 3.51e6)
        _fin(conn, "CRSP", "Revenues", "FY", "2024-12-31", 37.314e6)
        _fin(conn, "CRSP", "OperatingIncomeLoss", "FY", "2025-12-31", -664.571e6)
        _fin(conn, "CRSP", "DepreciationAndAmortisation", "FY", "2025-12-31", 19.479e6)
        _fin(conn, "CRSP", "NetIncomeLoss", "FY", "2025-12-31", -581.599e6)
        _fin(conn, "CRSP", "CashFlowOperating", "FY", "2025-12-31", -400e6)
        _fin(conn, "CRSP", "CashFlowOperating", "FY", "2024-12-31", -350e6)
        _fin(conn, "CRSP", "CashAndEquivalents", "instant", "2026-06-30", 1000e6)
        _fin(conn, "CRSP", "ShortTermInvestments", "instant", "2026-06-30", 1364.352e6)
        _fin(conn, "CRSP", "SharesOutstanding", "instant", "2026-07-31", 96.693e6, "shares")
        _price(conn, "CRSP", "2026-09-25", 54.23)
        _price(conn, "CRSP", "2026-09-28", 54.09)

        # SANA: cash on the balance sheet and no operating cash flow rows at all.
        _fin(conn, "SANA", "CashAndEquivalents", "instant", "2026-06-30", 300e6)
        _fin(conn, "SANA", "NetIncomeLoss", "FY", "2025-12-31", -250e6)
        _price(conn, "SANA", "2026-09-28", 4.0)

        # PFE: the latest close is five weekdays before today, eighty closes in all.
        for i, day in enumerate(_weekdays_back(dt.date(2026, 9, 22), 80)):
            _price(conn, "PFE", day.isoformat(), round(28.0 + i / 100.0, 2))

        # BNTX: every money row in euro while the company record says USD.
        for metric, value in (("Revenues", 3000e6), ("NetIncomeLoss", -500e6),
                              ("CashFlowOperating", -800e6)):
            _fin(conn, "BNTX", metric, "FY", "2025-12-31", value, "EUR")
        _fin(conn, "BNTX", "Revenues", "FY", "2024-12-31", 2875e6, "EUR")
        _fin(conn, "BNTX", "CashAndEquivalents", "instant", "2025-12-31", 10000e6, "EUR")
        _fin(conn, "BNTX", "SharesOutstanding", "instant", "2026-03-27", 240e6, "shares")
        _price(conn, "BNTX", "2026-09-28", 103.5)
        _snapshot(conn, "financials", "BNTX", {"taxonomy": "ifrs-full", "fetch_kind": "live"})
        for ticker in ("BNTX", "ARGX"):
            for form, filed, accession in (("20-F", "2026-03-10", f"{ticker}-1"),
                                           ("6-K", "2026-08-04", f"{ticker}-2")):
                conn.execute(
                    "INSERT INTO filings (company_id, form_type, filed_date, accession, title)"
                    " VALUES (?, ?, ?, ?, ?)", (_cid(conn, ticker), form, filed, accession,
                                                f"{ticker} {form}"))
        _fin(conn, "ARGX", "Revenues", "FY", "2025-12-31", 4151e6)

        # ARWR: a September fiscal year.
        _fin(conn, "ARWR", "Revenues", "FY", "2025-09-30", 829e6)
        _fin(conn, "ARWR", "Revenues", "FY", "2024-09-30", 3.55e6)
        _fin(conn, "ARWR", "NetIncomeLoss", "FY", "2025-09-30", 1.0e6)
        _price(conn, "ARWR", "2026-09-28", 70.0)
        _eps(conn, "ARWR", "FY2026", -1.0, -1.5, -0.5, 10)
        _eps(conn, "ARWR", "FY2027", -4.8, -6.0, -3.0, 10)

        # VRTX: a current cover count 1.3 times the weighted diluted count.
        _fin(conn, "VRTX", "SharesOutstanding", "instant", "2026-07-31", 130e6, "shares")
        _fin(conn, "VRTX", "WeightedAverageDilutedShares", "FY", "2025-12-31", 100e6, "shares")
        _fin(conn, "VRTX", "Revenues", "FY", "2025-12-31", 12000e6)
        _price(conn, "VRTX", "2026-09-28", 500.0)

        # REGN: a cover count from 2012.
        _fin(conn, "REGN", "SharesOutstanding", "instant", "2012-07-13", 93.955e6, "shares")
        _fin(conn, "REGN", "WeightedAverageDilutedShares", "FY", "2025-12-31", 108.6e6,
             "shares")
        _fin(conn, "REGN", "Revenues", "FY", "2025-12-31", 14343e6)
        _price(conn, "REGN", "2026-09-28", 700.0)

        # IOVA: the weighted diluted count is filed in thousands.
        _fin(conn, "IOVA", "SharesOutstanding", "instant", "2026-07-29", 452.971432e6,
             "shares")
        _fin(conn, "IOVA", "WeightedAverageDilutedShares", "FY", "2025-12-31", 357345.0,
             "shares")
        _fin(conn, "IOVA", "Revenues", "FY", "2025-12-31", 264e6)
        _price(conn, "IOVA", "2026-09-28", 11.0)

        # ROG: a workbook filer carrying both total and attributable profit.
        for metric, value in (("Revenues", 61516e6), ("NetIncomeLoss", 13799e6),
                              ("NetIncomeAttributableToParent", 12880e6)):
            _fin(conn, "ROG", metric, "FY", "2025-12-31", value, "CHF", source="financials_ir")
        _fin(conn, "ROG", "WeightedAverageDilutedShares", "FY", "2025-12-31", 802.99e6,
             "shares", source="financials_ir")
        conn.execute("INSERT OR REPLACE INTO adr_ratios (ticker, ordinary_per_adr) VALUES ('ROG', 0.125)")
        _price(conn, "ROG", "2026-09-28", 53.37)

        # GILD: product-sales guidance, and consensus crossing from a loss to a profit.
        _fin(conn, "GILD", "Revenues", "FY", "2025-12-31", 29443e6)
        _price(conn, "GILD", "2026-09-28", 120.0)
        _eps(conn, "GILD", "FY2026", -0.48, -1.2, 0.5, 20)
        _eps(conn, "GILD", "FY2027", 9.87, 9.0, 10.5, 20)
        _estimate(conn, "GILD", "ProductSales", "FY2026", 30.25e9, "guidance", "2026-08-04",
                  30.1e9, 30.4e9, "Product sales $30,100 to $30,400 in millions.", "reported")

        # SRPT: a revenue guide whose words say net product revenue.
        _fin(conn, "SRPT", "Revenues", "FY", "2025-12-31", 2198e6)
        _estimate(conn, "SRPT", "Revenue", "FY2026", 1.25e9, "guidance", "2026-08-05", 1.2e9,
                  1.3e9, "Company narrowed its 2026 total net product revenue guidance to "
                  "$1.2-$1.3 billion")

        # The latest refresh run: one consensus failure named by ticker, one other source.
        detail = {"sources": [
            {"source": "consensus_nasdaq",
             "errors": ["STOK: consensus_nasdaq: The read operation timed out"]},
            {"source": "approvals", "errors": ["INCY: approvals: The read operation timed out"]},
            {"source": "prices", "errors": []},
        ]}
        conn.execute(
            "INSERT INTO refresh_runs (started_at, finished_at, status, detail)"
            " VALUES ('2026-09-29 05:07:26', '2026-09-29 09:35:41', 'partial', ?)",
            (json.dumps(detail),))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def valuation_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("valuation") / "test.db"
    facts = {"LLY": _facts("companyfacts_lly.json"), "NVO": _facts("companyfacts_nvo.json")}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(FinancialsEdgarFetcher, "fetch", lambda self: facts[self.ticker])
        db.init(path)
        seed.load_companies(path)
        FinancialsEdgarFetcher("LLY", path).run()
        FinancialsEdgarFetcher("NVO", path).run()
    _seed(path)
    return path


@pytest.fixture(scope="module")
def out(valuation_db):
    return cv.build(valuation_db, today=TODAY)


def _by(out):
    return {r["ticker"]: r for r in out["companies"]}


def _codes(record, code=None):
    return [f for f in record["flags"] if code is None or f["code"] == code]


# --- the whole payload ---------------------------------------------------------------
def test_every_company_has_the_full_record(out):
    assert out["schema"] == cv.SCHEMA == 1
    assert len(out["companies"]) == 70
    tickers = [r["ticker"] for r in out["companies"]]
    assert len(set(tickers)) == 70
    for record in out["companies"]:
        assert set(record) == RECORD_KEYS, record["ticker"]
    assert out["errors"] == []
    assert out["universe"]["n"] == 70
    assert out["fx"]["usd_per_unit"]["DKK"] == pytest.approx(RATES["DKK"])
    assert out["fx"]["usd_per_unit"]["USD"] == 1.0
    assert "{cur}" in out["basis_text"]["standardised"]
    assert "28 Sep 2026" in out["basis_text"]["standardised"]


def test_strict_json_and_plain_types(out):
    json.dumps(out, allow_nan=False)

    def walk(value):
        assert value is None or isinstance(value, (dict, list, str, int, float, bool)), \
            type(value)
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(out)


def test_every_null_carries_its_reason(out):
    def nulls(value, path):
        if value is None:
            yield path
        elif isinstance(value, dict):
            for key, child in value.items():
                yield from nulls(child, f"{path}.{key}")
        elif isinstance(value, list):
            for child in value:
                yield from nulls(child, path)

    for record in out["companies"]:
        na = record["na"]

        def covered(path):
            parts = path.split(".")
            return any(".".join(parts[:i]) in na for i in range(1, len(parts) + 1))

        for section in cv.NA_SECTIONS:
            for path in nulls(record[section], section):
                assert covered(path), (record["ticker"], path)
        if record["filer"]["standard"] is None:
            assert covered("filer.standard"), record["ticker"]
        if record["region"] is None:
            assert covered("region"), record["ticker"]


# --- market cap, enterprise value, periods -------------------------------------------
def test_lly_diluted_route_by_exception(out, valuation_db):
    lly = _by(out)["LLY"]
    m = lly["market"]
    assert m["market_cap_basis"] == "diluted_weighted"
    assert _codes(lly, "cover_count_exception")
    assert m["market_cap_basis_text"].endswith(cv.COVER_COUNT_EXCEPTIONS["LLY"])
    assert m["market_cap_shares_m"] == pytest.approx(m["market_cap_usd_m"] / m["price"])
    assert m["shares_diluted_m"] == pytest.approx(899.3)
    assert m["price"] == LLY_PRICE
    net_debt = cashflow.build_cashflow(valuation_db, "LLY")["net_debt_usd"] / 1e6
    assert lly["ev"]["ev_usd_m"] == pytest.approx(m["market_cap_usd_m"] + net_debt)
    fy0 = lly["periods"]["FY0"]
    assert fy0["revenue_usd_m"] == 65179.0
    assert fy0["label"] == "FY2025"
    fy1 = lly["periods"]["FY1"]
    assert fy1["eps_n"] == 9 and fy1["eps"] == 36.62
    assert lly["street"]["price_target"]["ratings"] == {"buy": 19, "hold": 4, "sell": 0}
    assert lly["street"]["eps_first"]["FY1"] == {"value": 36.10, "as_of": "2026-09-17"}
    weight = (dt.date(2026, 12, 31) - dt.date(2026, 9, 28)).days / 365
    assert lly["periods"]["NTM"]["weight_fy1"] == pytest.approx(weight)
    assert lly["periods"]["NTM"]["eps"] == pytest.approx(weight * 36.62 + (1 - weight) * 45.0)
    guidance = fy1["guidance"]
    assert guidance["as_of"] == "2026-08-05" and guidance["value_usd_m"] == pytest.approx(86000)
    assert lly["filer"]["standard"] == "US GAAP"
    assert lly["filer"]["standard_source"] == "filed facts"


def test_nvo_converted_from_kroner(out):
    nvo = _by(out)["NVO"]
    m = nvo["market"]
    assert m["market_cap_basis"] == "diluted_weighted"
    ordinary = 102434000000 / 23.03           # net income over diluted EPS
    assert m["market_cap_usd_m"] == pytest.approx(38.71 * ordinary / 1e6)
    flag = _codes(nvo, "fx_converted")[0]
    assert flag["params"]["from"] == "DKK" and flag["params"]["rate"] == pytest.approx(0.15221)
    assert _codes(nvo, "market_cap_diluted_route")
    assert nvo["growth"]["revenue_fy"] == pytest.approx(309064 / 290403 - 1)
    assert nvo["periods"]["FY0"]["revenue_usd_m"] == pytest.approx(309064 * 0.15221)
    guidance = nvo["periods"]["FY1"]["guidance"]
    assert guidance["growth"] == pytest.approx(-0.03)
    assert guidance["growth_low"] == pytest.approx(-0.06)
    assert nvo["growth"]["revenue_guided_fy1"] is None
    assert nvo["na"]["growth.revenue_guided_fy1"] == "guidance_cer"


def test_clinical_company_without_a_debt_line(out):
    crsp, sana = _by(out)["CRSP"], _by(out)["SANA"]
    assert crsp["stage"] == "clinical"
    assert crsp["ev"]["ev_usd_m"] is None
    assert crsp["na"]["ev.ev_usd_m"] == "no_debt_line"
    assert crsp["ev"]["cash_usd_m"] == pytest.approx(2364.352)
    assert crsp["risk"]["runway_months"] > 0
    assert crsp["market"]["market_cap_basis"] == "shares_outstanding"
    assert sana["risk"]["runway_months"] is None
    assert sana["na"]["risk.runway_months"] == "no_cash_flow"
    # No revenue and no cash flow row, so cash is shown in its own row's unit.
    assert sana["ev"]["cash_usd_m"] == pytest.approx(300.0)


def test_stale_price_and_the_spark(out, valuation_db, monkeypatch):
    pfe, lly = _by(out)["PFE"], _by(out)["LLY"]
    stale = _codes(pfe, "stale_price")
    assert stale and stale[0]["params"]["trading_days"] == 4
    assert stale[0]["params"]["as_of"] == "2026-09-22"
    assert not _codes(lly, "stale_price")
    spark = pfe["market"]["spark_90d"]
    assert 2 <= len(spark) <= cv.SPARK_POINTS
    assert spark[-1] == pfe["market"]["price"]
    assert out["as_of"]["price_trading_days_old"] == 0

    class Later(dt.date):
        @classmethod
        def today(cls):
            return cls(2031, 1, 1)

    shim = types.SimpleNamespace(date=Later, timedelta=dt.timedelta, datetime=dt.datetime,
                                 timezone=dt.timezone)
    monkeypatch.setattr(cv, "dt", shim)
    again = _by(cv.build(valuation_db, today=TODAY))["PFE"]
    assert again["market"]["spark_90d"] == spark


def test_the_week_reads_five_sessions_back(out):
    """change_5d is the close against the close five sessions earlier, the move the
    Universe board draws. Sessions, not calendar days, so a holiday does not shorten it."""
    pfe, lly = _by(out)["PFE"], _by(out)["LLY"]
    m = pfe["market"]
    assert m["price_as_of"] == "2026-09-22"
    assert m["close_5d_as_of"] == "2026-09-15" and m["close_5d"] == pytest.approx(28.74)
    assert m["change_5d"] == pytest.approx(28.79 / 28.74 - 1)
    # Two closes on file: no week, and the reason says why rather than a zero.
    assert lly["market"]["change_5d"] is None
    assert lly["na"]["market.change_5d"] == "insufficient_history"


def test_spark_keeps_first_and_last(valuation_db):
    conn = db.get_connection(valuation_db)
    try:
        pfe = _cid(conn, "PFE")
        closes = cv._spark(conn, pfe, TODAY, days=365, max_points=10)
    finally:
        conn.close()
    assert len(closes) == 10
    assert closes[0] == 28.0 and closes[-1] == 28.79


def test_negative_ebitda_is_kept(out):
    crsp = _by(out)["CRSP"]
    assert crsp["periods"]["FY0"]["ebitda_usd_m"] == pytest.approx(-645.092)
    assert crsp["growth"]["ebitda_fy"] is None


def test_euro_rows_under_a_dollar_record(out):
    bntx, argx = _by(out)["BNTX"], _by(out)["ARGX"]
    assert _codes(bntx, "currency_mismatch")
    assert _codes(bntx, "currency_mismatch")[0]["params"]["row_units"] == ["EUR"]
    assert bntx["row_currency"] == "EUR"
    assert bntx["periods"]["FY0"]["revenue_usd_m"] == pytest.approx(3000 * 1.1378)
    assert bntx["ev"]["cash_usd_m"] == pytest.approx(10000 * 1.1378)
    # The diluted count fell back to the cover page, so it is no second measurement.
    assert bntx["market"]["market_cap_basis"] == "shares_outstanding"
    assert bntx["market"]["market_cap_alt_usd_m"] is None
    assert bntx["na"]["market.market_cap_alt_usd_m"] == "no_shares"
    assert bntx["filer"]["kind"] == "20-F filer"
    assert bntx["filer"]["standard"] == "IFRS"
    assert bntx["filer"]["standard_source"] == "filed facts"
    assert bntx["region"] is None and bntx["na"]["region"] == "domicile_unknown"
    assert bntx["na"]["periods.LTM"] == "no_ltm_20f"
    assert argx["filer"]["kind"] == "20-F filer"
    assert argx["filer"]["standard"] is None
    assert argx["na"]["filer.standard"] == "standard_not_recorded"


def test_september_year_end(out):
    arwr = _by(out)["ARWR"]
    assert arwr["fiscal_year_end_month"] == 9
    assert _codes(arwr, "fiscal_year_end")[0]["params"]["month"] == 9
    assert arwr["periods"]["FY1"]["label"] == "FY2026"
    weight = (dt.date(2026, 9, 30) - dt.date(2026, 9, 28)).days / 365
    assert arwr["periods"]["NTM"]["weight_fy1"] == pytest.approx(weight)


def test_cover_count_above_the_diluted_count(out):
    vrtx = _by(out)["VRTX"]
    assert vrtx["market"]["market_cap_basis"] == "shares_outstanding"
    assert _codes(vrtx, "market_cap_disagreement")
    m = vrtx["market"]
    assert m["market_cap_disagreement"] == pytest.approx(0.30)
    assert m["market_cap_disagreement"] == pytest.approx(
        abs(m["market_cap_usd_m"] / m["market_cap_alt_usd_m"] - 1))
    assert _codes(vrtx, "market_cap_disagreement")[0]["params"]["reason"] == \
        "it is the more recent count"


def test_stale_and_mis_scaled_share_counts(out):
    regn, iova = _by(out)["REGN"], _by(out)["IOVA"]
    assert regn["market"]["market_cap_basis"] == "diluted_weighted"
    assert _codes(regn, "stale_shares")[0]["params"]["as_of"] == "2012-07-13"
    assert regn["market"]["market_cap_basis_text"].endswith("the cover count is from 2012-07-13")
    assert iova["market"]["market_cap_basis"] == "shares_outstanding"
    assert iova["market"]["market_cap_alt_usd_m"] is None
    assert iova["na"]["market.market_cap_alt_usd_m"] == "share_count_scale"
    assert not _codes(iova, "market_cap_disagreement")


def test_attributable_profit_and_minorities(out):
    rog, nvo, lly = _by(out)["ROG"], _by(out)["NVO"], _by(out)["LLY"]
    fy0 = rog["periods"]["FY0"]
    assert fy0["net_income_usd_m"] == pytest.approx(12880 * 1.20224)
    assert fy0["net_income_basis"] == "attributable to shareholders"
    assert rog["filer"]["kind"] == "not an SEC filer"
    assert _codes(rog, "non_sec_filer") and _codes(rog, "no_consensus")
    assert _codes(rog, "no_consensus")[0]["params"]["otc"] is True
    assert rog["na"]["periods.FY1"] == "no_consensus_otc"
    assert rog["na"]["periods.FYm1"] == "one_year_only"
    lines = {f["field"] for f in _codes(nvo, "includes_minorities")}
    assert lines == {"periods.FY0.net_income_usd_m", "periods.FY0.equity_usd_m"}
    assert not _codes(lly, "includes_minorities")


def test_guidance_scope(out):
    by = _by(out)
    for ticker in ("GILD", "SRPT"):
        record = by[ticker]
        assert record["periods"]["FY1"]["guidance"]["metric_scope"] == "product", ticker
        assert record["growth"]["revenue_guided_fy1"] is None
        assert record["na"]["growth.revenue_guided_fy1"] == "guidance_product_scope"
    lly = by["LLY"]
    assert lly["periods"]["FY1"]["guidance"]["metric_scope"] == "total"
    assert lly["growth"]["revenue_guided_fy1"] == pytest.approx(86000 / 65179 - 1)
    assert _codes(lly, "guidance_fx_unstated")


def test_scope_rules():
    assert cv._scope("ProductSales", "Total revenues") == "product"
    assert cv._scope("Revenue", "Scope: Total Revenue (Product Revenue plus Collaboration "
                     "Revenue). More text on product sales.") == "total"
    assert cv._scope("Revenue", "Combined Net Product Revenue Guidance") == "product"
    assert cv._scope("Revenue", "revenue guidance of $350 million") == "total"
    assert cv._scope("Revenue", "Scope: total net product sales, not total revenues.") == \
        "product"


def test_consensus_sign_change(out):
    gild = _by(out)["GILD"]
    assert gild["periods"]["NTM"]["sign_change"] is True
    flag = _codes(gild, "eps_sign_change")[0]
    assert flag["params"] == {"fy1": -0.48, "fy2": 9.87}


def test_failed_sources_of_the_latest_run(out):
    run = out["as_of"]["run"]
    assert run["status"] == "partial" and run["id"] is not None
    assert run["failed_sources"] == [{"source": "consensus_nasdaq", "ticker": "STOK",
                                      "message": "The read operation timed out"}]
    assert "approvals" in run["other_failures"]
    stok = _by(out)["STOK"]
    assert _codes(stok, "source_failed")[0]["params"]["source"] == "consensus_nasdaq"
    assert not _codes(_by(out)["LLY"], "source_failed")


def test_a_month_only_catalyst_keeps_its_month(valuation_db, tmp_path):
    """The registry gives about a quarter of readouts as a month and no day ("2026-11").
    The panel's Key catalysts printed "·" for them while Catalysts and Key insights print
    "Nov 2026": the date was parsed as a day and came back null. A month still running is
    ahead, so a "2026-09" readout on 29 Sep is listed; "2026-08" is past."""
    import sqlite3
    path = tmp_path / "catalysts.db"
    shutil.copy(valuation_db, path)
    conn = sqlite3.connect(path)
    try:
        cid = _cid(conn, "LLY")
        conn.executemany(
            """INSERT INTO catalysts (company_id, catalyst_type, expected_date,
                   date_confidence, title, is_curated, status)
               VALUES (?, 'data readout', ?, ?, ?, 0, 'pending')""",
            [(cid, "2026-11", "month", "Phase 3, a month only"),
             (cid, "2026-09", "month", "Phase 3, this month"),
             (cid, "2026-08", "month", "Phase 3, last month"),
             (cid, "2026-12-15", "estimated", "Phase 3, a day"),
             (cid, "2026-09-28", "estimated", "Phase 3, yesterday")])
        conn.commit()
    finally:
        conn.close()
    rows = _by(cv.build(path, today=TODAY))["LLY"]["detail"]["catalysts"]
    assert [(r["expected_date"], r["date_confidence"]) for r in rows] == [
        ("2026-09", "month"), ("2026-11", "month"), ("2026-12-15", "estimated")]
    assert cv._catalyst_date("2026-13") is None and cv._catalyst_date(None) is None
    assert cv._catalyst_date("2027-01-10 00:00:00") == "2027-01-10"


def test_other_claims(out):
    lly, crsp = _by(out)["LLY"], _by(out)["CRSP"]
    assert lly["ev"]["other_claims_usd_m"] == pytest.approx(-1500.0)
    assert lly["ev"]["other_claims_lines"][0]["as_of"] == "2025-12-31"
    assert crsp["ev"]["other_claims_usd_m"] is None
    assert crsp["na"]["ev.other_claims_usd_m"] == "none_on_file"


# --- the model block -------------------------------------------------------------------
FAIR_VALUE = {"ok": True, "ticker": "LLY", "price_date": "2026-09-28",
              "equity_per_share": 486.21,
              "rating": {"ok": True, "rating": "Sell", "low_today": 400.0, "high_today": 560.0,
                         "forward_12m": 520.0, "upside_12m": -0.56}}
VERDICT = {"ok": True, "ticker": "LLY",
           "sotp": {"pipeline": {"n": 12, "rnpv": 48000.0, "per_share": 53.99,
                                 "per_share_unrisked": 87.11}}}


def test_model_block_off_the_cache(out):
    lly, crsp = _by(out)["LLY"], _by(out)["CRSP"]
    assert lly["model"]["state"] == "not_computed"
    assert lly["na"]["model.fair_value_per_share"] == "model_not_computed"
    assert out["complete"] is False and out["incomplete_reason"] == "model_not_computed"
    assert crsp["model"]["state"] == "not_modelled"


def test_model_block_from_cached_reads(valuation_db, monkeypatch):
    reads = {"/companies/LLY/fair-value": FAIR_VALUE,
             "/companies/LLY/forecast-verdict": VERDICT}
    monkeypatch.setattr(response_cache, "cached_json", lambda path, query="": reads.get(path))
    built = cv.build(valuation_db, today=TODAY)
    model = _by(built)["LLY"]["model"]
    assert built["complete"] is True and built["incomplete_reason"] is None
    assert model["state"] == "modelled"
    assert model["fair_value_per_share"] == 486.21 and model["rating"] == "Sell"
    assert model["range_today"] == [400.0, 560.0]
    assert model["pipeline_rnpv_usd_m"] == pytest.approx(48000.0)
    assert model["pipeline_assets"] == 12 and model["price_date"] == "2026-09-28"


# --- failure isolation, route and cache ------------------------------------------------
def test_one_failing_company_does_not_fail_the_rest(valuation_db, monkeypatch):
    real = cv.beta_module.compute

    def compute(conn, ticker, *args, **kwargs):
        if ticker == "PFE":
            raise RuntimeError("boom")
        return real(conn, ticker, *args, **kwargs)

    monkeypatch.setattr(cv.beta_module, "compute", compute)
    built = cv.build(valuation_db, today=TODAY)
    by = _by(built)
    assert len(built["companies"]) == 70
    assert by["PFE"]["error"] and "boom" in by["PFE"]["error"]
    assert _codes(by["PFE"], "calc_failed")[0]["severity"] == "red"
    assert [e["ticker"] for e in built["errors"]] == ["PFE"]
    assert built["errors"][0]["stage"] == "market"
    assert all(r["error"] is None for t, r in by.items() if t != "PFE")
    json.dumps(built, allow_nan=False)


def test_route_marks_an_incomplete_body(valuation_db, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", Path(valuation_db))
    response = TestClient(main.app).get("/comps/valuation")
    assert response.status_code == 200
    body = response.json()
    assert body["schema"] == 1 and len(body["companies"]) == 70
    assert body["complete"] is False
    assert response.headers.get("x-cache-skip") == "1"


def test_cache_never_stores_an_incomplete_body(valuation_db, tmp_path, monkeypatch):
    database = tmp_path / "copy.db"
    shutil.copy(valuation_db, database)
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setenv("ER_TOOL_RESPONSE_CACHE", "1")
    monkeypatch.setattr(response_cache, "start_warming", lambda base: None)
    response_cache.clear()
    try:
        client = TestClient(main.app)
        first = client.get("/comps/valuation")
        assert first.headers.get("x-cache-skip") == "1"
        assert "/comps/valuation?" not in response_cache._entries

        # Once the model reads are warm the body is complete, and stored as usual.
        reads = {"/companies/LLY/fair-value": FAIR_VALUE,
                 "/companies/LLY/forecast-verdict": VERDICT}
        monkeypatch.setattr(response_cache, "cached_json",
                            lambda path, query="": reads.get(path))
        second = client.get("/comps/valuation")
        assert second.json()["complete"] is True
        assert "x-cache-skip" not in second.headers
        assert "/comps/valuation?" in response_cache._entries
    finally:
        response_cache.clear()
    assert "/comps/valuation" in response_cache.LATE_GLOBAL_READS
    assert "/comps/valuation" not in response_cache.GLOBAL_READS
