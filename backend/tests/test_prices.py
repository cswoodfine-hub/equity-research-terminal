"""parse_chart is the prices parser; it runs against a saved Yahoo fixture, no network."""

import json
from pathlib import Path

import pytest

import db
import seed
from fetchers.prices import PricesFetcher, parse_chart

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_chart_lly.json"


def test_yahoo_symbol_uses_us_adr_for_foreign_names(tmp_path):
    # A US filer quotes by its ticker; foreign names quote by their US ADR (ROG->RHHBY
    # Roche), never the home ticker, which would resolve to an unrelated US company.
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    assert PricesFetcher("LLY", db_file)._yahoo_symbol() == "LLY"
    assert PricesFetcher("ROG", db_file)._yahoo_symbol() == "RHHBY"
    assert PricesFetcher("BAYN", db_file)._yahoo_symbol() == "BAYRY"


def _payload():
    return json.loads(FIXTURE.read_text())


def test_parse_chart_fixture_exact_values():
    rows, meta = parse_chart(_payload(), "LLY")

    assert len(rows) == 124
    assert meta["currency"] == "USD"
    assert rows[0]["as_of"] == "2026-01-20"
    assert rows[0]["close"] == pytest.approx(1041.2900390625)
    assert rows[-1]["as_of"] == "2026-07-17"
    assert rows[-1]["close"] == pytest.approx(1176.635009765625)

    # every row has a real close and dates are ascending
    assert all(r["close"] is not None for r in rows)
    assert [r["as_of"] for r in rows] == sorted(r["as_of"] for r in rows)


def test_parse_chart_drops_null_close_days():
    payload = {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {"currency": "USD", "gmtoffset": 0, "regularMarketPrice": 12.0},
                    "timestamp": [1_700_000_000, 1_700_086_400, 1_700_172_800],
                    "indicators": {
                        "quote": [
                            {
                                "close": [10.0, None, 12.0],  # middle day is a gap
                                "open": [9.0, None, 11.5],
                                "high": [10.5, None, 12.5],
                                "low": [8.5, None, 11.0],
                                "volume": [100, None, 120],
                            }
                        ]
                    },
                }
            ],
        }
    }
    rows, _ = parse_chart(payload, "TEST")
    assert [r["close"] for r in rows] == [10.0, 12.0]  # null day dropped, not fabricated


def test_parse_chart_raises_on_yahoo_error():
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "x"}}}
    with pytest.raises(ValueError):
        parse_chart(payload, "ZZZZ")


def test_parse_chart_raises_on_empty_result():
    with pytest.raises(ValueError):
        parse_chart({"chart": {"result": None, "error": None}}, "ZZZZ")


def test_intraday_bars_keep_their_time_and_stay_out_of_the_daily_series(tmp_path):
    """The two series share a table and must never contaminate each other.

    A 15m bar stamped with a bare date would collapse a session of bars onto one key,
    and the unique constraint would keep only the last. Stamped with a time they are
    distinct rows, and every daily query filters on interval so they cannot interleave
    into the five year chart.
    """
    payload = {"chart": {"result": [{
        "meta": {"currency": "USD", "gmtoffset": 0},
        "timestamp": [1_752_000_000, 1_752_000_900, 1_752_001_800],
        "indicators": {"quote": [{"close": [10.0, 11.0, 12.0], "open": [None] * 3,
                                  "high": [None] * 3, "low": [None] * 3,
                                  "volume": [None] * 3}]},
    }]}}
    rows, _ = parse_chart(payload, "LLY", "15m")
    assert len(rows) == 3, "three bars must survive as three rows"
    assert len({r["as_of"] for r in rows}) == 3
    assert all(len(r["as_of"]) == 16 for r in rows)   # YYYY-MM-DD HH:MM
    assert all(r["interval"] == "15m" for r in rows)

    daily, _ = parse_chart(payload, "LLY", "1d")
    assert all(len(r["as_of"]) == 10 for r in daily)  # YYYY-MM-DD
    assert all(r["interval"] == "1d" for r in daily)


def test_the_two_price_fetchers_do_not_share_a_ttl_slot():
    """TTL is tracked per (source, entity_key). A shared source would mean whichever
    fetcher ran first marked the slot fresh and the other was skipped, every time."""
    from fetchers.prices import IntradayPricesFetcher, PricesFetcher
    assert PricesFetcher.source != IntradayPricesFetcher.source
    assert IntradayPricesFetcher.chart_interval == "15m"
    assert IntradayPricesFetcher.chart_range == "5d"
