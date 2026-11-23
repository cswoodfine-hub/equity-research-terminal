"""The live price read: Yahoo's recent bars, held for a minute and never written.

The two fixtures are Yahoo's own answers for Lilly, saved unedited at 14:37:34 UTC on
2026-11-23, seven and a half minutes into the New York session: five sessions of five
minute bars and a month of hourly ones, the two requests the route makes. A payload read mid-session is the one worth keeping,
because it ends on the last-trade point that a payload read after the close does not
have, and the hourly month reaches back across the clock change of 2026-11-01. No
network: a getter stands in for Yahoo and a counter for each clock.

The page's half, laying the live bars over the stored ones, is tested here too. It
lives in ``frontend/price_chart.py``, which is put on the path as ``test_price_chart.py``
does it.
"""

import datetime as dt
import hashlib
import json
import sqlite3
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import db
import main
import prices_live as PL
import response_cache as RC
import seed
from fetchers import prices as yahoo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import price_chart  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
FIVE = FIXTURES / "yahoo_chart_lly_5m_live.json"
HOUR = FIXTURES / "yahoo_chart_lly_60m_live.json"
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


def _payload(interval):
    return json.loads({"5m": FIVE, "60m": HOUR}[interval].read_text())


def _meta(interval="5m"):
    return _payload(interval)["chart"]["result"][0]["meta"]


# The moment the fixture is read at in these tests: five seconds after its last trade,
# inside the session it was saved in.
READ_AT = _meta()["regularMarketTime"] + 5


class Clock:
    """A clock a test moves by hand."""

    def __init__(self, at=0.0):
        self.at = at

    def __call__(self):
        return self.at


class Yahoo:
    """Stands in for the chart endpoint and counts what it was asked."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, symbol, chart_range, interval, **_kwargs):
        self.calls.append((symbol, chart_range, interval))
        if self.fail is not None:
            raise self.fail
        return _payload(interval)


@pytest.fixture(autouse=True)
def nothing_held():
    PL.clear()
    yield
    PL.clear()


def _read(getter, clock=None, fresh=False, at=READ_AT, ticker="LLY", symbol=None):
    return PL.read(ticker, symbol, fresh=fresh, getter=getter,
                   clock=clock or Clock(), wall=lambda: at)


# --- the fixture is what the tests say it is ---------------------------------
def test_the_fixture_was_read_mid_session_and_ends_on_a_last_trade_point():
    result = _payload("5m")["chart"]["result"][0]
    meta, stamps = result["meta"], result["timestamp"]
    regular = meta["currentTradingPeriod"]["regular"]
    assert regular["start"] <= stamps[-1] < regular["end"]
    assert (stamps[-1] - regular["start"]) % 300 != 0       # off the five minute grid
    quote = result["indicators"]["quote"][0]
    assert quote["volume"][-1] == 0
    assert quote["open"][-1] == quote["high"][-1] == quote["low"][-1] == quote["close"][-1]
    # What the meta does and does not carry about the market.
    assert "marketState" not in meta and "exchangeDataDelayedBy" not in meta
    assert {"currentTradingPeriod", "regularMarketTime", "exchangeTimezoneName",
            "gmtoffset", "fullExchangeName"} <= set(meta)


# --- the bars ------------------------------------------------------------------
def test_the_last_trade_is_folded_into_the_bar_it_falls_in():
    result = _payload("5m")["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    bars = _read(Yahoo())["bars"]["5m"]

    stamps = [bar["as_of"] for bar in bars]
    assert stamps == sorted(stamps) and len(stamps) == len(set(stamps))
    # Every bar starts on the five minute grid: no stick at the second of the last trade.
    assert all(int(stamp[-2:]) % 5 == 0 for stamp in stamps)
    last = bars[-1]
    assert last["close"] == pytest.approx(quote["close"][-1])
    assert last["low"] <= last["close"] <= last["high"]
    # One point fewer than Yahoo sent with a close: the trade joined a bar, it did not
    # become one.
    sent = sum(1 for close in quote["close"] if close is not None)
    assert len(bars) == sent - 1
    # The bar it joined keeps its own open and volume.
    assert last["open"] == pytest.approx(quote["open"][-2])
    assert last["volume"] == quote["volume"][-2]


def test_a_last_trade_with_no_bar_under_it_becomes_that_bar():
    start = 1_795_444_200                      # 09:30 in New York on 2026-11-23
    meta = {"gmtoffset": -18000,
            "currentTradingPeriod": {"regular": {"start": start, "end": start + 23400}}}
    rows = [{"as_of": "2026-11-23 09:30", "open": 10.0, "high": 11.0, "low": 9.5,
             "close": 10.5, "volume": 100},
            {"as_of": "2026-11-23 09:37", "open": 10.8, "high": 10.8, "low": 10.8,
             "close": 10.8, "volume": 0}]
    out = PL.settle_last_trade(rows, meta, "5m")
    assert [bar["as_of"] for bar in out] == ["2026-11-23 09:30", "2026-11-23 09:35"]
    assert out[1]["close"] == 10.8 and out[0]["close"] == 10.5

    # The same trade two minutes earlier falls inside the 09:30 bar and is folded in.
    rows[1] = dict(rows[1], as_of="2026-11-23 09:33", open=11.4, high=11.4, low=11.4,
                   close=11.4)
    out = PL.settle_last_trade(rows, meta, "5m")
    assert out == [{"as_of": "2026-11-23 09:30", "open": 10.0, "high": 11.4, "low": 9.5,
                    "close": 11.4, "volume": 100}]

    # Hourly bars are counted from the open, so they start on the half hour.
    rows[1] = dict(rows[1], as_of="2026-11-23 10:47")
    assert PL.settle_last_trade(rows, meta, "60m")[-1]["as_of"] == "2026-11-23 10:30"

    # The closing print sits on the closing time and is left as the bar the stored
    # series also keeps.
    rows[1] = dict(rows[1], as_of="2026-11-23 16:00")
    assert PL.settle_last_trade(rows, meta, "5m")[-1]["as_of"] == "2026-11-23 16:00"


def test_bars_from_the_other_side_of_a_clock_change_are_left_out():
    result = _payload("60m")["chart"]["result"][0]
    offsets = {period["gmtoffset"] for group in result["meta"]["tradingPeriods"]
               for period in group}
    assert offsets == {-14400, -18000}          # the month spans the change

    # Read plainly, the October sessions come out an hour early.
    plain, _ = yahoo.parse_chart(_payload("60m"), "LLY", "60m")
    assert plain[0]["as_of"].endswith("08:30")

    bars = _read(Yahoo())["bars"]["60m"]
    assert bars[0]["as_of"] == "2026-11-02 09:30"
    assert {bar["as_of"][11:] for bar in bars} <= {
        "09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"}


# --- the live daily bar -----------------------------------------------------------
def test_the_live_daily_bar_is_the_session_added_up():
    out = _read(Yahoo())
    daily, bars = out["live_daily"], out["bars"]["5m"]
    session = [bar for bar in bars if bar["as_of"].startswith("2026-11-23")]

    assert daily["as_of"] == "2026-11-23"
    assert daily["bars"] == len(session) > 0
    assert daily["open"] == session[0]["open"]
    assert daily["high"] == max(bar["high"] for bar in session)
    assert daily["low"] == min(bar["low"] for bar in session)
    assert daily["close"] == session[-1]["close"]
    assert daily["volume"] == sum(bar["volume"] for bar in session)
    assert daily["first_bar"] == "2026-11-23 09:30"
    # The figures themselves, seven and a half minutes into the session: two bars, the
    # second closed by the last trade at 09:37:31 and not by its own 1358.40.
    assert daily["bars"] == 2 and daily["last_bar"] == "2026-11-23 09:35"
    assert daily["open"] == pytest.approx(1345.11, abs=0.005)
    assert daily["high"] == pytest.approx(1360.58, abs=0.005)
    assert daily["low"] == pytest.approx(1344.00, abs=0.005)
    assert daily["close"] == pytest.approx(1357.395, abs=0.0005)
    assert daily["volume"] == 144900 + 12995
    # The close is the last trade Yahoo reports, to the cent.
    assert daily["close"] == pytest.approx(_meta()["regularMarketPrice"], abs=0.005)
    # A session still open is said to be.
    assert daily["complete"] is False
    assert daily["session_end"] == "2026-11-23T21:00:00Z"
    # The same bars read after the bell are a finished session.
    PL.clear()
    late = _read(Yahoo(), at=_meta()["currentTradingPeriod"]["regular"]["end"] + 60)
    assert late["live_daily"]["complete"] is True


def test_live_daily_arithmetic_and_a_missing_field_stays_null():
    bars = [
        {"as_of": "2026-11-20 15:55", "open": 9.0, "high": 9.9, "low": 8.8, "close": 9.1,
         "volume": 500},
        {"as_of": "2026-11-23 09:30", "open": 10.0, "high": 10.6, "low": 9.9,
         "close": 10.4, "volume": 100},
        {"as_of": "2026-11-23 09:35", "open": 10.4, "high": 11.2, "low": 10.1,
         "close": 11.0, "volume": None},
        {"as_of": "2026-11-23 09:40", "open": 11.0, "high": 11.1, "low": 9.7,
         "close": 9.8, "volume": 250},
    ]
    daily = PL.live_daily(bars, {}, 0)
    assert (daily["as_of"], daily["open"], daily["high"], daily["low"], daily["close"],
            daily["volume"], daily["bars"]) == ("2026-11-23", 10.0, 11.2, 9.7, 9.8, 350, 3)
    # No session hours in the meta: whether it is finished is not known, and not guessed.
    assert daily["complete"] is None and daily["session_end"] is None

    bare = [{"as_of": "2026-11-23 09:30", "open": None, "high": None, "low": None,
             "close": 5.0, "volume": None}]
    daily = PL.live_daily(bare, {}, 0)
    assert daily["close"] == 5.0
    assert daily["open"] is daily["high"] is daily["low"] is daily["volume"] is None
    assert PL.live_daily([], {}, 0) is None


# --- the market ------------------------------------------------------------------
def test_market_state_is_the_session_hours_against_the_clock():
    meta = _meta()
    regular = meta["currentTradingPeriod"]["regular"]

    during = PL.market(meta, READ_AT)
    assert during["regular_open"] is True and during["phase"] == "regular"
    assert during["traded_this_session"] is True
    assert during["exchange"] == "NYSE"
    assert during["exchange_timezone"] == "America/New_York"
    assert during["regular_start"] == "2026-11-23T14:30:00Z"
    assert during["regular_end"] == "2026-11-23T21:00:00Z"
    assert during["seconds_to_close"] == regular["end"] - READ_AT
    assert during["seconds_to_open"] is None
    # The delay is not stated, so it is null; the age of the last trade is measured.
    assert during["stated_delay_minutes"] is None
    assert during["quote_age_seconds"] == 5

    before = PL.market(meta, regular["start"] - 90)
    assert before["regular_open"] is False and before["phase"] == "pre"
    assert before["seconds_to_open"] == 90 and before["quote_age_seconds"] is None

    assert PL.market(meta, regular["end"])["regular_open"] is False     # half-open hours
    assert PL.market(meta, regular["end"] + 60)["phase"] == "post"

    # Hours that say open with no trade inside them: a holiday, a halt or the bell.
    quiet = dict(meta, regularMarketTime=regular["start"] - 3600)
    assert PL.market(quiet, READ_AT)["regular_open"] is True
    assert PL.market(quiet, READ_AT)["traded_this_session"] is False
    assert PL.market(quiet, READ_AT)["quote_age_seconds"] is None


# --- the hold --------------------------------------------------------------------
def test_an_answer_is_held_for_the_hold_and_fresh_asks_again():
    getter, clock = Yahoo(), Clock(1000.0)

    first = _read(getter, clock)
    assert first["ok"] is True and first["held"] is False
    assert sorted(getter.calls) == [("LLY", "1mo", "60m"), ("LLY", "5d", "5m")]

    clock.at += PL.HOLD_S - 1
    again = _read(getter, clock)
    assert again["held"] is True and len(getter.calls) == 2
    assert again["bars"] == first["bars"]

    clock.at += 2                              # past the hold
    assert _read(getter, clock)["held"] is False and len(getter.calls) == 4

    # The Refresh button: asked again at once, whatever the hold says.
    assert _read(getter, clock, fresh=True)["held"] is False and len(getter.calls) == 6

    # Held by symbol, so one company's answer is never another's.
    _read(getter, clock, ticker="ROG", symbol="RHHBY")
    assert getter.calls[-1][0] == "RHHBY" and len(getter.calls) == 8


def test_the_hold_is_about_a_minute_and_under_the_pages_tick():
    assert 45 <= PL.HOLD_S < price_chart.LIVE_TICK_S == 60
    assert PL.FAIL_HOLD_S < price_chart.LIVE_TICK_S


# --- failure ---------------------------------------------------------------------
def test_a_yahoo_failure_is_ok_false_with_the_reason_and_never_raises():
    down = Yahoo(fail=urllib.error.URLError("no route to host"))
    clock = Clock(50.0)
    out = _read(down, clock)
    assert out["ok"] is False
    assert "URLError" in out["reason"] and "no route to host" in out["reason"]
    assert out["bars"] == {"5m": [], "60m": []}
    assert out["live_daily"] is None and out["market"] is None
    assert out["fetched_at"] is None

    # A failure is held too, so a page being drawn does not wait on Yahoo every rerun.
    clock.at += PL.FAIL_HOLD_S - 1
    assert _read(down, clock)["ok"] is False and len(down.calls) == 2
    clock.at += 2
    _read(down, clock)
    assert len(down.calls) == 4


def test_an_error_payload_and_a_broken_one_are_soft_too():
    refused = lambda *a, **k: {"chart": {"result": None, "error": {  # noqa: E731
        "code": "Not Found", "description": "No data found, symbol may be delisted"}}}
    out = _read(refused)
    assert out["ok"] is False and "Not Found" in out["reason"]
    PL.clear()
    assert _read(lambda *a, **k: "not json at all")["ok"] is False


def test_a_failure_after_a_good_read_keeps_the_last_good_bars_and_their_time():
    clock = Clock(0.0)
    good = _read(Yahoo(), clock, at=READ_AT)
    clock.at += 5
    out = _read(Yahoo(fail=TimeoutError("timed out")), clock, fresh=True, at=READ_AT + 5)
    assert out["ok"] is False and "TimeoutError" in out["reason"]
    assert out["bars"] == good["bars"]
    assert out["fetched_at"] == good["fetched_at"]          # said to be as old as it is
    assert out["market"]["regular_open"] is True


# --- the route, and what it must not touch --------------------------------------
def _counts(path):
    conn = sqlite3.connect(str(path))
    try:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in tables}
    finally:
        conn.close()


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def book(tmp_path, monkeypatch):
    path = tmp_path / "book.db"
    db.init(path)
    seed.load_companies(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    getter = Yahoo()
    monkeypatch.setattr(yahoo, "fetch_chart", getter)
    return TestClient(main.app), path, getter


def test_the_route_answers_with_bars_the_session_and_the_market(book):
    client, _path, getter = book
    body = client.get("/companies/lly/prices/live").json()
    assert body["ok"] is True and body["ticker"] == "LLY" and body["symbol"] == "LLY"
    assert body["source"] == "yahoo_chart" and body["currency"] == "USD"
    assert set(body["bars"]) == {"5m", "60m"} and body["bars"]["5m"]
    assert set(body["bars"]["5m"][0]) == {"as_of", "open", "high", "low", "close",
                                          "volume"}
    assert body["live_daily"]["as_of"] == "2026-11-23"
    assert body["market"]["exchange"] == "NYSE"
    assert body["fetched_at"].endswith("Z")

    # A foreign name is asked for by its US line, as the stored series was.
    assert client.get("/companies/ROG/prices/live").json()["symbol"] == "RHHBY"
    assert getter.calls[-1][0] == "RHHBY"
    assert client.get("/companies/ZZZZ/prices/live").status_code == 404


def test_calling_the_live_route_leaves_the_book_untouched(book):
    client, path, getter = book
    # Settle the file first: the first connection to a new database is what moves it
    # into write-ahead mode, and that is the fixture's doing, not the route's.
    db.get_connection(path).close()
    before_counts, before_sha = _counts(path), _sha(path)
    before_mtime = path.stat().st_mtime_ns
    assert before_counts["companies"] > 0

    for ticker in ("LLY", "ROG", "AZN"):
        assert client.get(f"/companies/{ticker}/prices/live").json()["ok"] is True
        assert client.get(f"/companies/{ticker}/prices/live?fresh=1").json()["ok"] is True
    assert len(getter.calls) == 12              # Yahoo was really asked, each time

    assert _counts(path) == before_counts
    assert _sha(path) == before_sha
    assert path.stat().st_mtime_ns == before_mtime
    # Named, because these are the three the design turns on: no run is opened, no
    # snapshot is taken and no bar is filed.
    for table in ("refresh_runs", "snapshots", "prices", "intraday_bars"):
        assert _counts(path)[table] == 0
    # The stamp the response cache keeps every valuation against has not moved either.
    wal = Path(str(path) + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_a_yahoo_failure_on_the_route_is_a_200_that_says_so(book, monkeypatch):
    client, _path, _getter = book
    monkeypatch.setattr(yahoo, "fetch_chart", Yahoo(
        fail=urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)))
    response = client.get("/companies/LLY/prices/live?fresh=1")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and "429" in body["reason"]
    assert body["bars"] == {"5m": [], "60m": []}


def test_the_live_route_is_never_kept_by_the_response_cache():
    assert RC.cacheable("/companies/LLY/prices/live", "") is False
    assert RC.cacheable("/companies/LLY/prices/live", "fresh=1") is False
    assert RC.cacheable("/companies/LLY/prices", "") is True      # the stored series is


def test_the_fetchers_still_ask_yahoo_through_the_one_request(monkeypatch, tmp_path):
    path = tmp_path / "book.db"
    db.init(path)
    seed.load_companies(path)
    asked = []
    monkeypatch.setattr(yahoo, "fetch_chart",
                        lambda *args, **kwargs: asked.append(args) or {"chart": {}})
    yahoo.PricesFetcher("ROG", path).fetch()
    yahoo.FiveMinuteBarsFetcher("LLY", path).fetch()
    assert asked == [("RHHBY", "10y", "1d"), ("LLY", "60d", "5m")]


# --- the page's half: laying live over stored --------------------------------------
STORED = [
    {"as_of": "2026-11-20 15:50", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1},
    {"as_of": "2026-11-20 15:55", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2},
    {"as_of": "2026-11-20 16:00", "open": 1.2, "high": 1.2, "low": 1.2, "close": 1.2},
]
LIVE = [
    {"as_of": "2026-11-23 09:35", "open": 2.1, "high": 2.4, "low": 2.0, "close": 2.3},
    {"as_of": "2026-11-20 15:55", "open": 1.1, "high": 1.9, "low": 1.0, "close": 1.8},
    {"as_of": "2026-11-23 09:30", "open": 2.0, "high": 2.2, "low": 1.9, "close": 2.1},
]


def test_merge_live_wins_no_duplicates_and_the_order_is_by_time():
    merged = price_chart.merge_live(STORED, LIVE)
    stamps = [bar["as_of"] for bar in merged]
    assert stamps == ["2026-11-20 15:50", "2026-11-20 15:55", "2026-11-20 16:00",
                      "2026-11-23 09:30", "2026-11-23 09:35"]
    assert len(stamps) == len(set(stamps))
    # Where both hold a bar, the live one is the one drawn.
    assert merged[1]["close"] == 1.8 and merged[1]["high"] == 1.9
    # A stored bar the live read does not reach is kept as it was.
    assert merged[0] is STORED[0] and merged[2] is STORED[2]
    # Either side alone, and neither.
    assert price_chart.merge_live(STORED, []) == STORED
    assert [b["as_of"] for b in price_chart.merge_live([], LIVE)] == sorted(
        b["as_of"] for b in LIVE)
    assert price_chart.merge_live(None, None) == []
    # Neither list is changed by the merge.
    assert len(STORED) == 3 and LIVE[0]["as_of"] == "2026-11-23 09:35"


def test_merge_with_the_real_bars_runs_unbroken_into_the_session():
    live = _read(Yahoo())["bars"]["5m"]
    stored = [bar for bar in live if bar["as_of"] < "2026-11-20 12:00"]
    stored[-1] = dict(stored[-1], close=1.0)          # a bar caught half formed
    merged = price_chart.merge_live(stored, live)
    assert [bar["as_of"] for bar in merged] == [bar["as_of"] for bar in live]
    assert merged == live                              # live won the bar both hold
    assert price_chart.live_gap(stored, live) is None


def test_a_gap_between_stored_and_live_is_found_and_said_plainly():
    live = [{"as_of": "2026-11-16 09:30", "close": 2.0}]
    stale = [{"as_of": "2026-11-10 16:00", "close": 1.0}]
    gap = price_chart.live_gap(stale, live)
    assert gap == {"stored_ends": "2026-11-10 16:00", "live_begins": "2026-11-16 09:30"}
    words = price_chart.live_gap_words(gap)
    assert "Stored bars end 2026-11-10 16:00" in words and "not data" in words

    # Friday's close into Monday's open is no gap: there was no session between them.
    friday = [{"as_of": "2026-11-13 16:00", "close": 1.0}]
    assert price_chart.live_gap(friday, live) is None
    # Overlapping, or one side empty, is no gap either.
    assert price_chart.live_gap(live, live) is None
    assert price_chart.live_gap([], live) is None and price_chart.live_gap(stale, []) is None
    assert price_chart.live_gap_words(None) == ""

    # The daily series: stored to Wednesday, live session on Monday.
    daily_gap = price_chart.live_gap([{"as_of": "2026-11-18", "close": 1.0}],
                                     [{"as_of": "2026-11-23", "close": 2.0}])
    assert daily_gap == {"stored_ends": "2026-11-18", "live_begins": "2026-11-23"}


def test_the_live_daily_bar_gives_way_only_to_a_close_read_after_the_bell():
    stored = [{"as_of": "2026-11-19", "close": 1.0}, {"as_of": "2026-11-20", "close": 2.0}]
    done = {"as_of": "2026-11-20", "close": 2.1, "complete": True,
            "session_end": "2026-11-20T21:00:00Z"}
    forming = {"as_of": "2026-11-23", "close": 3.0, "complete": False,
               "session_end": "2026-11-23T21:00:00Z"}

    # No stored bar for the day: the live one is all there is.
    assert price_chart.live_daily_applies(stored, forming, "2026-11-23 13:34:00") is True
    # A stored bar read after the session ended is the finished close and stands.
    assert price_chart.live_daily_applies(stored, done, "2026-11-23 13:34:00") is False
    # A stored bar read while the session ran is a last trade, not a close: live wins.
    assert price_chart.live_daily_applies(stored, done, "2026-11-20 17:00:00") is True
    # A session still open always wins, and so does one whose end is not known.
    open_now = dict(done, complete=False)
    assert price_chart.live_daily_applies(stored, open_now, "2026-11-23 13:34:00") is True
    unknown = dict(done, complete=None, session_end=None)
    assert price_chart.live_daily_applies(stored, unknown, "2026-11-23 13:34:00") is True
    assert price_chart.live_daily_applies(stored, done, None) is True
    # Nothing to apply.
    assert price_chart.live_daily_applies(stored, None) is False
    assert price_chart.live_daily_applies(stored, {"as_of": "2026-11-23"}) is False


def test_the_chart_reads_each_minute_while_open_and_not_at_all_when_closed():
    open_now = {"market": {"regular_open": True, "seconds_to_open": None}}
    opens_soon = {"market": {"regular_open": False, "seconds_to_open": 1800}}
    opens_now = {"market": {"regular_open": False, "seconds_to_open": 2}}
    closed = {"market": {"regular_open": False, "seconds_to_open": None}}
    far = {"market": {"regular_open": False, "seconds_to_open": 60 * 60 * 40}}

    assert price_chart.poll_seconds(open_now) == 60
    assert price_chart.poll_seconds(opens_soon) == 1805      # one timer, set for the bell
    assert price_chart.poll_seconds(opens_now) == 15
    assert price_chart.poll_seconds(closed) is None
    assert price_chart.poll_seconds(far) is None
    assert price_chart.poll_seconds({"ok": False, "market": None}) is None
    assert price_chart.poll_seconds(None) is None
    assert [price_chart.poll_kind(s) for s in (60, 1805, None)] == ["tick", "wake", "off"]


def test_the_words_say_whose_prices_when_and_which_bar_is_live():
    live = _read(Yahoo())
    status = price_chart.live_status(live)
    assert status.startswith("Yahoo, read ") and "UTC" in status
    assert "NYSE open, re-read every minute" in status

    note = price_chart.live_note(live)
    assert "Live prices are Yahoo's, read at" in note
    assert "writes nothing to the book" in note
    assert "open until 21:00 UTC" in note
    assert "Yahoo does not state a delay on this feed; the last trade was 5 seconds" in note

    daily = price_chart.live_bar_words(live, "1d", [live["live_daily"]])
    assert daily.startswith("2026-11-23 is live: the session so far") and "EST" in daily
    assert "not a close" in daily
    # Intraday: only the bars the stored series does not hold are called live, from
    # the first of them. Where the stored series already runs to the last bar, nothing
    # is claimed.
    five = live["bars"]["5m"]
    on_file = [bar for bar in five if bar["as_of"] < "2026-11-23"]
    intraday = price_chart.live_bar_words(live, "5m", five, on_file)
    assert intraday == ("live from 2026-11-23 09:30: Yahoo's bars, not in the stored "
                        "history")
    assert price_chart.live_bar_words(live, "5m", five, five) == ""
    assert price_chart.live_bar_words(live, "1d", []) == ""

    PL.clear()
    late = _read(Yahoo(), at=_meta()["currentTradingPeriod"]["regular"]["end"] + 600)
    assert "NYSE closed" in price_chart.live_status(late)
    assert "is closed" in price_chart.live_note(late)
    finished = price_chart.live_bar_words(late, "1d", [late["live_daily"]])
    assert "finished session" in finished and "not yet a stored close" in finished

    PL.clear()
    down = _read(Yahoo(fail=urllib.error.URLError("down")))
    assert price_chart.live_status(down) == "Yahoo did not answer"
    assert "The chart shows the stored bars only" in price_chart.live_note(down)

    for text in (status, note, daily, intraday, finished, price_chart.live_note(late),
                 price_chart.live_note(down), price_chart.live_gap_words(
                     {"stored_ends": "a", "live_begins": "b"})):
        assert chr(0x2014) not in text          # the em dash the house style bars
        assert not any(word in text.lower() for word in BANNED)


def test_what_the_tab_draws_for_the_real_session():
    """The daily view end to end with the real bars: the stored series ends on Friday's
    close, read after the bell, and Monday's session goes on as one live bar."""
    live = _read(Yahoo())
    stored = [{"as_of": "2026-11-19", "open": 1369.38, "high": 1382.0, "low": 1341.46,
               "close": 1351.12, "volume": 3198300},
              {"as_of": "2026-11-20", "open": 1362.38, "high": 1372.05, "low": 1341.76,
               "close": 1347.11, "volume": 3540200}]
    assert price_chart.live_daily_applies(stored, live["live_daily"],
                                          "2026-11-23 13:34:00") is True
    merged = price_chart.merge_live(stored, [live["live_daily"]])
    assert [bar["as_of"] for bar in merged] == ["2026-11-19", "2026-11-20", "2026-11-23"]
    assert merged[1] is stored[1]                       # Friday's stored close stands
    assert price_chart.live_gap(stored, [live["live_daily"]]) is None
    series = price_chart.series_data(merged, price_chart.CANDLE)
    assert series[-1]["time"] == "2026-11-23"
    assert series[-1]["close"] == pytest.approx(live["live_daily"]["close"])
    assert dt.date.fromisoformat(series[-1]["time"]).weekday() == 0
