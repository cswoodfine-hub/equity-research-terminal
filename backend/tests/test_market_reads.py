"""Short interest and the options-implied move, read for the catalyst focus list's week."""

import datetime as dt
import json
import pathlib

import pytest

import event_moves
import market_reads as mr

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_short_interest_parses_newest_first():
    rows = mr.parse_short_interest(json.loads(
        (FIXTURES / "nasdaq_short_interest_capr.json").read_text()))
    assert rows[0] == {"settlement": "2026-09-30", "shares": 18825352.0,
                       "avg_volume": 4165921.0, "days_to_cover": pytest.approx(4.518893)}
    assert [r["settlement"] for r in rows] == sorted((r["settlement"] for r in rows),
                                                     reverse=True)


def test_an_empty_or_refused_payload_reads_nothing():
    assert mr.parse_short_interest(None) == []
    assert mr.parse_short_interest({"data": None}) == []


def test_the_move_is_read_at_the_first_expiry_on_or_after_the_event():
    chain = event_moves.parse_chain(json.loads(
        (FIXTURES / "cboe_options_lly.json").read_text()), "LLY")
    first = chain["expiries"][2]
    got = mr.implied_move(chain, first["expiry"])
    assert got["expiry"] == first["expiry"].isoformat()
    assert got["move"] == pytest.approx(first["iv"] * first["t"] ** 0.5)
    assert mr.implied_move(chain, dt.date(2099, 1, 1)) is None
    assert mr.implied_move(None, dt.date(2026, 1, 1)) is None


def test_reads_are_cached_and_a_failure_is_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "CACHE_PATH", tmp_path / "reads.json")
    calls = []
    payload = json.loads((FIXTURES / "nasdaq_short_interest_capr.json").read_text())

    def get(url):
        calls.append(url)
        return payload if "CAPR" in url else None
    first = mr.short_interest(["CAPR", "XXXX"], get=get)
    again = mr.short_interest(["CAPR"], get=get)
    assert first["CAPR"][0]["shares"] == 18825352.0 and first["XXXX"] == []
    assert again["CAPR"] == first["CAPR"] and len(calls) == 2      # CAPR read once
