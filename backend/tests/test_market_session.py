"""A daily bar from a session still trading is held back, whenever the read happens.

The schedule was the only thing keeping an intraday price out of the stored closes, and
the committed run log shows it starting in the middle of the US session. These pin the
rule to the payload's own hours instead.
"""

import json
from pathlib import Path

import market_session
from fetchers import benchmarks
from fetchers.prices import parse_chart

FIXTURES = Path(__file__).parent / "fixtures"

# The saved Lilly payload was itself read mid-session: its newest daily bar is stamped
# at the opening bell of 2026-07-17 and its last trade came 3h53m later.
OPEN, CLOSE, LAST_TRADE = 1784295000, 1784318400, 1784308997


def _lly():
    return json.loads((FIXTURES / "yahoo_chart_lly.json").read_text())


def _meta(start=OPEN, end=CLOSE, offset=-14400):
    return {"gmtoffset": offset,
            "currentTradingPeriod": {"regular": {"start": start, "end": end}}}


def test_a_bar_from_the_open_session_is_not_settled_until_the_bell():
    assert market_session.is_settled(OPEN, _meta(), LAST_TRADE) is False
    assert market_session.is_settled(OPEN, _meta(), CLOSE - 1) is False
    assert market_session.is_settled(OPEN, _meta(), CLOSE) is True


def test_an_earlier_session_is_settled_while_today_trades():
    assert market_session.is_settled(OPEN - 86400, _meta(), LAST_TRADE) is True


def test_before_the_open_nothing_is_held_back():
    """The hours describe a session that has not started, and no bar is stamped in it."""
    assert market_session.is_settled(OPEN - 86400, _meta(), OPEN - 3600) is True


def test_no_clock_asks_no_question():
    assert market_session.is_settled(OPEN, _meta(), None) is True


def test_with_no_hours_stated_a_bar_dated_today_is_held_back():
    """Not knowing when the session ends is not leave to call its bar a close."""
    meta = {"gmtoffset": -14400}
    evening = CLOSE + 2 * 3600          # 18:00 in New York, the same day
    assert market_session.is_settled(OPEN, meta, evening) is False
    assert market_session.is_settled(OPEN - 86400, meta, evening) is True
    assert market_session.is_settled(OPEN, meta, OPEN + 86400) is True   # the next day


def test_the_price_parser_holds_back_the_session_in_progress():
    rows, meta = parse_chart(_lly(), "LLY", now=LAST_TRADE)
    assert len(rows) == 123
    assert rows[-1]["as_of"] == "2026-07-16"
    assert meta["held_back"]["as_of"] == "2026-07-17"
    assert meta["held_back"]["last_trade"] == parse_chart(_lly(), "LLY")[0][-1]["close"]


def test_the_price_parser_keeps_the_bar_once_the_session_has_closed():
    rows, meta = parse_chart(_lly(), "LLY", now=CLOSE)
    assert len(rows) == 124
    assert rows[-1]["as_of"] == "2026-07-17"
    assert meta["held_back"] is None


def test_a_saved_payload_read_with_no_clock_is_unchanged():
    rows, meta = parse_chart(_lly(), "LLY")
    assert len(rows) == 124 and meta["held_back"] is None


def test_an_intraday_series_is_never_cut():
    """Its newest bar is meant to be live; only the daily series is a record of closes."""
    payload = json.loads((FIXTURES / "yahoo_chart_lly_5m_live.json").read_text())
    result = payload["chart"]["result"][0]
    now = result["meta"]["regularMarketTime"]
    kept, _ = parse_chart(payload, "LLY", "5m", now=now)
    every, _ = parse_chart(payload, "LLY", "5m")
    assert len(kept) == len(every) > 0


def test_the_fetcher_snapshots_the_last_finished_close(tmp_path, monkeypatch):
    """What reaches the snapshot history mid-session is yesterday's close under
    yesterday's date, as it is on a weekend, and never today's last trade."""
    import db
    import seed
    from fetchers import prices as P

    db_file = tmp_path / "t.db"
    db.init(db_file)
    seed.load_companies(db_file)
    monkeypatch.setattr(P.time, "time", lambda: float(LAST_TRADE))
    fetcher = P.PricesFetcher("LLY", db_file)
    rows = fetcher.normalise(_lly())
    fetcher.snapshot(rows)
    fetcher.upsert(rows)

    conn = db.get_connection(db_file)
    try:
        snap = json.loads(conn.execute(
            "SELECT payload FROM snapshots WHERE source = 'prices'"
            " ORDER BY id DESC LIMIT 1").fetchone()["payload"])
        newest = conn.execute(
            "SELECT MAX(as_of) FROM prices WHERE interval = '1d'").fetchone()[0]
    finally:
        conn.close()
    assert snap["as_of"] == "2026-07-16"
    assert newest == "2026-07-16"


def test_the_benchmark_parser_follows_the_same_rule():
    """The two are read against each other, so they settle together."""
    payload = _lly()            # any payload with stated hours and an open session
    live = benchmarks.parse_chart(payload, "XBI", now=LAST_TRADE)
    done = benchmarks.parse_chart(payload, "XBI", now=CLOSE)
    assert len(done) == len(live) + 1
    assert live[-1]["as_of"] == "2026-07-16"


def test_a_benchmark_payload_with_no_hours_holds_back_only_a_bar_dated_today():
    payload = json.loads((FIXTURES / "yahoo_chart_xlv.json").read_text())
    stamps = payload["chart"]["result"][0]["timestamp"]
    same_day = stamps[-1] + 3600
    assert len(benchmarks.parse_chart(payload, "XLV", now=same_day)) == 4
    assert len(benchmarks.parse_chart(payload, "XLV", now=stamps[-1] + 86400)) == 5
    assert len(benchmarks.parse_chart(payload, "XLV")) == 5


# --- where a piece of news sits among the closes --------------------------------------------
def test_news_accepted_before_the_close_is_one_session_from_the_day_before():
    # 11:30 UTC on a November day is 06:30 in New York.
    got = market_session.news_window("2026-11-18", "2026-11-18T11:30:00.000Z")
    assert got == {"anchor": "2026-11-17", "sessions": 1, "basis": "timed"}


def test_news_accepted_after_the_close_is_given_two_sessions():
    # 22:00 UTC is 17:00 in New York: after the bell on the 18th.
    got = market_session.news_window("2026-11-18", "2026-11-18T22:00:15.000Z")
    assert got == {"anchor": "2026-11-17", "sessions": 2, "basis": "timed"}


def test_the_new_york_date_decides_and_not_the_one_the_filing_is_listed_under():
    """EDGAR lists a filing accepted after 17:30 under the next business day. The news
    was public the evening before, so the close before it is the day before that."""
    got = market_session.news_window("2026-11-19", "2026-11-18T23:10:00.000Z")
    assert got["anchor"] == "2026-11-17" and got["sessions"] == 2


def test_summer_time_is_read_off_the_calendar_and_not_assumed():
    # 20:30 UTC is 16:30 in New York in July (after the close) and 15:30 in December.
    assert market_session.news_window("2026-07-15", "2026-07-15T20:30:00Z")["sessions"] == 2
    assert market_session.news_window("2026-12-15", "2026-12-15T20:30:00Z")["sessions"] == 1


def test_a_date_with_no_time_is_given_two_sessions_from_the_day_before():
    got = market_session.news_window("2026-11-18")
    assert got == {"anchor": "2026-11-17", "sessions": 2, "basis": "date only"}
    assert market_session.news_window("2026-11-18", "not a time")["basis"] == "date only"
    assert market_session.news_window(None) is None and market_session.news_window("") is None
