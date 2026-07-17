"""parse_chart is the prices parser; it runs against a saved Yahoo fixture, no network."""

import json
from pathlib import Path

import pytest

from fetchers.prices import parse_chart

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_chart_lly.json"


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
