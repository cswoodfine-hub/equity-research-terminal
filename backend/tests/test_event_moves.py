"""A readout's move as the model states it, beside the move the options price."""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import pytest

import event_moves as E

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = dt.datetime(2026, 10, 9, 16, 0)


def _expiry(day, iv, error=0.0):
    t = (dt.datetime.combine(dt.date.fromisoformat(day), E.CLOSE) - AS_OF).total_seconds()
    return {"expiry": dt.date.fromisoformat(day), "t": t / (365 * 86400), "iv": iv,
            "iv_error": error}


def _chain(pairs, error=0.001):
    return {"spot": 100.0, "as_of": AS_OF, "iv30": 30.0,
            "expiries": [_expiry(d, iv, error) for d, iv in pairs]}


def _stake(name, date, per_share, now, win=1.0, lose=0.0, held=None,
           confidence="estimated", url="https://example.com/x"):
    return {"id": 1, "asset_name": name, "catalyst_type": "data readout",
            "expected_date": date, "date_confidence": confidence, "source_url": url,
            "per_share": per_share, "pos_now": now, "pos_success": win,
            "pos_failure": lose, "held": ({"pos": held} if held is not None else None)}


# --- reading the sources ---------------------------------------------------------------
def test_the_chain_reads_each_expiry_at_the_money_from_the_quote_time():
    chain = E.parse_chain(json.loads((FIXTURES / "cboe_options_lly.json").read_text()),
                          "LLY")
    assert chain["spot"] == pytest.approx(1177.0474)
    assert chain["as_of"] == AS_OF
    assert [e["expiry"].isoformat() for e in chain["expiries"]] == [
        "2026-10-23", "2026-11-06", "2026-11-20", "2027-01-15"]
    first = chain["expiries"][0]
    assert first["t"] == pytest.approx(14 / 365)
    # Between the 1175 and 1180 strikes, each the mean of its call and put.
    assert first["strikes"] == (1175.0, 1180.0)
    lo, hi = (0.3019 + 0.3166) / 2, (0.2915 + 0.3315) / 2
    assert first["iv"] == pytest.approx(lo + (1177.0474 - 1175) / 5 * (hi - lo))
    # The error is half the spread over vega, in volatility, shrunk by the quotes used.
    assert 0.0 < first["iv_error"] < 0.03


def test_only_live_two_sided_quotes_on_the_symbols_own_root_count():
    payload = json.loads((FIXTURES / "cboe_options_lly.json").read_text())
    for quote in payload["data"]["options"]:
        if quote["option"].startswith("LLY261023"):
            quote["option"] = "LLY1" + quote["option"][3:]
        elif quote["option"].startswith("LLY261106"):
            # An expiry on the quote's own day has settled.
            quote["option"] = "LLY261009" + quote["option"][9:]
    expiries = {e["expiry"].isoformat()
                for e in E.parse_chain(payload, "LLY")["expiries"]}
    assert expiries == {"2026-11-20", "2027-01-15"}
    payload = json.loads((FIXTURES / "cboe_options_lly.json").read_text())
    for quote in payload["data"]["options"]:
        quote["bid"] = 0.0
    assert E.parse_chain(payload, "LLY")["expiries"] == []


def test_the_next_results_date_is_read_and_marked_expected():
    payload = json.loads((FIXTURES / "nasdaq_earnings_date_lly.json").read_text())
    got = E.parse_earnings(payload)
    assert got["date"] == dt.date(2026, 10, 29) and got["expected"]
    assert E.parse_earnings({"data": {"announcement": ""}}) is None


# --- the model's legs ------------------------------------------------------------------
def test_the_legs_are_at_the_readouts_own_odds_not_the_approval_odds():
    """MariTide on 12 October 2026: approval 0.5452, 0.8937 on a pass, nil on a miss, so
    the readout's own odds are 0.61 and a pass adds 39% of the swing, not 45%."""
    got = E.legs(_stake("MariTide", "2027-01-21", 46.08, 0.5452, 0.8937, 0.0), 415.0)
    assert got["q"] == pytest.approx(0.5452 / 0.8937)
    swing = 46.08 / 415.0
    assert got["up"] == pytest.approx(swing * (0.8937 - 0.5452) / 0.8937)
    assert got["down"] == pytest.approx(-swing * 0.5452 / 0.8937)
    assert got["sd"] == pytest.approx(swing * math.sqrt(got["q"] * (1 - got["q"])))


def test_a_miss_the_model_holds_moves_the_price_only_on_a_pass():
    """With nine other Phase 3s open the model holds MariTide at 55% on a miss: the miss
    leg is nil and the move is the pass leg's alone."""
    got = E.legs(_stake("MariTide", "2027-01-21", 46.08, 0.5452, 0.8937, 0.0,
                        held=0.5452), 415.0)
    assert got["held"] and got["down"] == 0.0
    assert got["sd"] == pytest.approx(got["up"] * math.sqrt(got["q"] * (1 - got["q"])))
    assert got["sd"] == pytest.approx(0.0211, abs=5e-4)


# --- spans and windows ------------------------------------------------------------------
def test_a_date_spans_what_it_can_mean():
    assert E._span(_stake("A", "2026-11", 1, 0.5, confidence="month")) == (
        dt.date(2026, 11, 1), dt.date(2026, 11, 30))
    assert E._span(_stake("A", "2027-06-30", 1, 0.5, confidence="half")) == (
        dt.date(2027, 1, 1), dt.date(2027, 6, 30))
    registry = _stake("A", "2027-02-18", 1, 0.5, url="https://clinicaltrials.gov/study/N")
    assert E._span(registry) == (dt.date(2027, 2, 18),
                                 dt.date(2027, 2, 18) + dt.timedelta(days=120))
    assert E._span(_stake("A", "2027-02-18", 1, 0.5)) == (dt.date(2027, 2, 18),) * 2


def test_a_date_sits_between_the_last_expiry_before_it_and_the_first_on_or_after():
    expiries = [_expiry(d, 0.3) for d in ("2026-10-23", "2026-11-20", "2026-12-18")]
    before, after = E.window(expiries, dt.date(2026, 11, 20), dt.date(2026, 11, 20))
    assert (before["expiry"].isoformat(), after["expiry"].isoformat()) == (
        "2026-10-23", "2026-11-20")
    assert E.window(expiries, dt.date(2027, 1, 5), dt.date(2027, 1, 5))[1] is None


# --- the options' move ------------------------------------------------------------------
def _with_event(pairs, at, move):
    """A flat 30% surface with ``move`` added at the expiries from ``at``."""
    chain = _chain(pairs)
    for e in chain["expiries"]:
        if e["expiry"] >= dt.date.fromisoformat(at):
            e["iv"] = math.sqrt(0.30 ** 2 + move ** 2 / e["t"])
    return chain


def test_a_readout_the_options_price_as_the_model_does_reads_in_line():
    days = ("2026-10-23", "2026-11-20", "2026-12-18", "2027-01-15")
    chain = _with_event([(d, 0.30) for d in days], "2026-12-18", 0.06)
    swing = 0.06 / 0.5 * 100.0
    got = E.compare(chain, None, [_stake("X-1", "2026-12-01", swing, 0.5)])
    row = got["rows"][0]
    assert row["window"] == ["2026-11-20", "2026-12-18"]
    assert row["model_sd"] == pytest.approx(0.06)
    assert math.sqrt(row["market_variance"]) == pytest.approx(0.06)
    assert row["verdict"] == "in_line"
    assert (row["up_pct"], row["down_pct"]) == pytest.approx((0.06, -0.06))


def test_the_base_is_stripped_of_the_results_the_earlier_expiry_holds():
    """Novo's case: the earlier expiry already holds the next results. Run on, its
    volatility counts them again over the gap and hides a readout the options do price."""
    days = ("2026-10-23", "2026-11-13", "2026-12-18", "2027-01-15", "2027-03-19")
    chain = _chain([(d, 0.30) for d in days])
    for e in chain["expiries"]:
        extra = (0.08 ** 2 if e["expiry"] >= dt.date(2026, 11, 13) else 0.0) + (
            0.06 ** 2 if e["expiry"] >= dt.date(2027, 3, 19) else 0.0) + (
            0.08 ** 2 if e["expiry"] >= dt.date(2027, 3, 19) else 0.0)
        e["iv"] = math.sqrt(0.30 ** 2 + extra / e["t"])
    results = {"date": dt.date(2026, 11, 4), "expected": True}
    swing = 0.06 / 0.5 * 100.0
    got = E.compare(chain, results, [_stake("Cagri", "2027-03-01", swing, 0.5)])
    row = got["rows"][0]
    assert got["results"]["move"] == pytest.approx(0.08, rel=1e-6)
    assert row["held_results"] == 1                       # 3 February, projected
    assert row["base_iv"] == pytest.approx(0.30, rel=1e-6)
    assert math.sqrt(row["market_variance"]) == pytest.approx(0.06, rel=1e-6)
    assert row["raw_base_iv"] > row["base_iv"]


def test_a_move_below_what_the_options_resolve_is_unresolved():
    days = ("2026-10-23", "2026-11-20", "2026-12-18", "2027-01-15")
    chain = _chain([(d, 0.30) for d in days], error=0.02)
    got = E.compare(chain, None, [_stake("X-1", "2026-12-01", 0.2, 0.5)])
    assert got["rows"][0]["verdict"] == "unresolved"
    assert "the options can resolve" in got["rows"][0]["why"]


def test_windows_the_surface_cannot_read_are_said_not_to_be_read():
    days = ("2026-10-23", "2026-11-20", "2027-06-17", "2027-12-17")
    chain = _chain([(d, 0.30) for d in days])
    got = E.compare(chain, None, [_stake("Far", "2027-09-01", 5.0, 0.5),
                                  _stake("Gone", "2028-03-01", 5.0, 0.5)])
    far, gone = got["rows"]
    assert far["verdict"] == "unread" and "past six months" in far["why"]
    assert gone["verdict"] == "unread" and "past the last listed expiry" in gone["why"]


def test_results_are_read_never_floored_at_nil():
    """A results window whose later expiry prices less than the earlier one (Moderna, 5
    November 2026) holds another event first: its move cannot be read, and is not 0%."""
    chain = _chain([("2026-10-30", 1.19), ("2026-11-06", 1.135), ("2026-12-18", 1.0)])
    assert E.next_results(chain, {"date": dt.date(2026, 11, 5), "expected": True}) is None
    got = E.compare(chain, {"date": dt.date(2026, 11, 5), "expected": True},
                    [_stake("X-1", "2026-12-10", 5.0, 0.5)])
    assert got["results"]["move"] is None
    assert got["rows"][0]["verdict"] == "unread"


def test_a_readout_in_the_next_results_window_is_not_separated():
    days = ("2026-10-23", "2026-11-20", "2026-12-18")
    chain = _with_event([(d, 0.30) for d in days], "2026-11-20", 0.05)
    got = E.compare(chain, {"date": dt.date(2026, 11, 5), "expected": True},
                    [_stake("X-1", "2026-11-10", 10.0, 0.5)])
    assert got["rows"][0]["verdict"] == "unread"
    assert "next results" in got["rows"][0]["why"]


def test_readouts_in_one_window_share_it_and_name_the_one_that_carries_it():
    days = ("2026-10-23", "2026-11-20", "2026-12-18", "2027-01-15")
    chain = _chain([(d, 0.30) for d in days])
    got = E.compare(chain, None, [_stake("A", "2026-12-01", 8.0, 0.5),
                                  _stake("B", "2026-12-10", 6.0, 0.5)])
    a, b = got["rows"]
    assert a["shared_with"] == ["B"] and b["shared_with"] == ["A"]
    assert a["window_model_sd"] == pytest.approx(math.sqrt(0.04 ** 2 + 0.03 ** 2))
    assert a["driver"] == b["driver"] == "A"
    assert "carried by A" in b["why"] and "carried by" not in a["why"]


def test_rows_without_a_date_or_legs_are_kept_and_said_unread():
    got = E.compare(_chain([("2026-10-23", 0.3)]), None,
                    [{"id": 9, "asset_name": "Z", "expected_date": None}])
    assert got["rows"] == [{"catalyst_id": 9, "asset": "Z", "date": None,
                            "verdict": "unread", "why": "no date or no legs on file"}]


def test_no_listed_options_says_so():
    got = E.compare(None, None, [])
    assert not got["ok"] and "no listed options" in got["reason"]
