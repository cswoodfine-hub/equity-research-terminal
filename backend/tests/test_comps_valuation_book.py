"""The valuation payload against the built book: coverage, size, time and the named cases.

Read only. Skipped where no book is built (a fresh worktree). Run it off a backup copy
rather than the live file:

    sqlite3 backend/er_tool.db ".backup '/tmp/book.db'"
    ER_TOOL_DB=/tmp/book.db .venv/bin/python -m pytest -q tests/test_comps_valuation_book.py

The response cache is off in the suite, so every modelled company reads as not computed
and ``complete`` is false; the model block is covered by the seeded tests.
"""

import json
import time

import pytest

import comps_valuation as cv
import db


@pytest.fixture(scope="module")
def payload():
    if not db.DB_PATH.exists():
        pytest.skip(f"no built database at {db.DB_PATH}")
    conn = db.get_connection()
    try:
        built = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    except Exception:
        built = 0
    finally:
        conn.close()
    if not built:
        pytest.skip(f"the database at {db.DB_PATH} has not been built")
    started = time.perf_counter()
    out = cv.build()
    return out, time.perf_counter() - started


def _by(out):
    return {r["ticker"]: r for r in out["companies"]}


def _flag(record, code):
    return [f for f in record["flags"] if f["code"] == code]


def test_coverage_size_and_time(book, payload):
    out, seconds = payload
    companies = out["companies"]
    assert len(companies) == 70
    assert out["errors"] == []
    assert sum(1 for r in companies if r["market"]["market_cap_usd_m"]) == 70
    assert sum(1 for r in companies if r["ev"]["ev_usd_m"] is not None) >= 36
    positive_ntm = sum(1 for r in companies
                       if (r["periods"]["NTM"] or {}).get("eps") is not None
                       and r["periods"]["NTM"]["eps"] > 0 and r["market"]["price"])
    assert positive_ntm >= 29
    body = json.dumps(out, allow_nan=False, separators=(",", ":"))
    assert len(body.encode("utf-8")) < 900 * 1024
    assert seconds < 10


def test_named_cases(book, payload):
    by = _by(payload[0])
    regn, lly, iova = by["REGN"], by["LLY"], by["IOVA"]
    assert regn["market"]["market_cap_basis"] == "diluted_weighted" and _flag(regn, "stale_shares")
    assert lly["market"]["market_cap_basis"] == "diluted_weighted"
    assert _flag(lly, "cover_count_exception")
    assert iova["market"]["market_cap_alt_usd_m"] is None
    assert iova["na"]["market.market_cap_alt_usd_m"] == "share_count_scale"
    for ticker in ("BNTX", "ARGX", "LEGN"):
        assert by[ticker]["filer"]["kind"] == "20-F filer", ticker
        assert by[ticker]["region"] is None, ticker
    assert _flag(by["GILD"], "eps_sign_change")
    for ticker in ("SRPT", "ALNY"):
        assert by[ticker]["periods"]["FY1"]["guidance"]["metric_scope"] == "product", ticker


def test_enterprise_value_uses_dated_debt(book, payload):
    """INCY's 2018 debt mis-tag once put its EV/Sales at 7.9x; dated net debt gives 4.2x."""
    incy = _by(payload[0])["INCY"]
    ev, revenue = incy["ev"]["ev_usd_m"], incy["periods"]["FY0"]["revenue_usd_m"]
    assert ev is not None and 3.5 < ev / revenue < 5.0
