"""The one measurement every signal goes through (signal_test.py)."""

import datetime as dt
import inspect

import pytest

import db
import signal_test as S


def _days(n, start=dt.date(2024, 1, 1)):
    out, day = [], start
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += dt.timedelta(days=1)
    return out


DAYS = _days(460)
BENCH = (DAYS, [100.0] * len(DAYS))


def _series(closes, spread=0.01, volume=1_000_000):
    return {"days": list(DAYS), "close": list(closes),
            "high": [c * (1 + spread / 2) for c in closes],
            "low": [c * (1 - spread / 2) for c in closes],
            "volume": [volume] * len(closes)}


def _stepped(steps, base=20.0):
    """A flat share that moves by a fraction at each (bar index, fraction)."""
    closes, level = [], base
    moves = dict(steps)
    for i in range(len(DAYS)):
        if i in moves:
            level *= 1 + moves[i]
        closes.append(level)
    return closes


def _book(move=0.20, same_for_all=False, spread=0.01, volume=1_000_000):
    """Fifteen shares and thirty events, one every ten bars. Each event's share moves by
    ``move`` five bars after its entry; with ``same_for_all`` every share moves then."""
    events, steps = [], {c: [] for c in range(1, 16)}
    for k in range(30):
        cid, bar = 1 + k % 15, 30 + 10 * k
        events.append({"company_id": cid, "day": DAYS[bar]})
        size = move + 0.01 * (k % 5) * (1 if move > 0 else -1)
        for target in (steps if same_for_all else [cid]):
            steps[target].append((bar + 1 + 5, size))
    prices = {cid: _series(_stepped(s), spread, volume) for cid, s in steps.items()}
    return prices, events


def test_entry_is_the_close_of_the_session_after_the_event():
    """A share that jumps on the event day and the day after has nothing left to give:
    the jump was before the first close a reader could have traded at."""
    closes = [10.0] * len(DAYS)
    for i in range(51, len(DAYS)):
        closes[i] = 15.0                       # the jump lands on the bar after the event
    prices = {1: _series(closes), 2: _series([10.0] * len(DAYS))}
    got = S.measure(prices, BENCH, [{"company_id": 1, "day": DAYS[50]}], horizon=21)
    assert got["measured"] == 1
    assert got["median_against_xbi"] == pytest.approx(0.0)
    assert got["first"] == DAYS[51]


def test_an_event_on_a_friday_enters_on_the_monday():
    friday = next(d for d in DAYS[40:] if dt.date.fromisoformat(d).weekday() == 4)
    assert dt.date.fromisoformat(S.entry_day(DAYS, friday)).weekday() == 0
    # A weekend date is not a session; the next one is.
    saturday = (dt.date.fromisoformat(friday) + dt.timedelta(days=1)).isoformat()
    assert S.entry_day(DAYS, saturday) == S.entry_day(DAYS, friday)


def test_the_spread_estimate_returns_a_spread_that_is_all_the_range_holds():
    """With no movement but the bid and the ask, the estimator gives the spread back."""
    series = _series([50.0] * len(DAYS), spread=0.02)
    assert S.spread(series, 100) == pytest.approx(0.02, rel=1e-6)
    assert S.spread(_series([50.0] * len(DAYS), spread=0.0), 100) == pytest.approx(0.0)
    assert S.spread(series, 3) is None                 # too few bars behind it


def test_a_share_too_thin_to_trade_is_left_out_and_counted():
    prices, events = _book(volume=10)                  # 10 shares a day at about $20
    got = S.measure(prices, BENCH, events, horizon=21)
    assert got["measured"] == 0
    assert got["dropped"] == {"too_thin_to_trade": 30}


def test_a_move_that_only_the_event_shares_make_passes():
    prices, events = _book()
    got = S.measure(prices, BENCH, events, horizon=21, basis="written_first")
    net = got["over_placebo_net"]
    assert got["measured"] == 30 and net["companies"] == 15 and net["months"] >= 12
    assert got["on_side_of_xbi"] == 1.0
    assert net["mean"] > 0.15 and net["t_by_month"] > 2 and net["t_by_company"] > 2
    assert got["passes_backtest"] is True
    assert got["verdict"].startswith("passes the backtest on the book's own names")
    assert got["survivors_only"] is True


def test_a_move_every_share_makes_is_the_market_and_does_not_pass():
    """The placebo is the same days in the other shares, so a rally is not a signal."""
    prices, events = _book(same_for_all=True)
    got = S.measure(prices, BENCH, events, horizon=21)
    assert got["median_against_xbi"] > 0.15            # it beat XBI handsomely
    assert abs(got["over_placebo"]["mean"]) < 0.02     # and its placebo not at all
    assert got["passes_backtest"] is False
    assert got["verdict"].startswith("does not pass")


def test_the_cost_of_a_round_trip_is_one_spread():
    prices, events = _book(spread=0.03)
    got = S.measure(prices, BENCH, events, horizon=21)
    assert got["median_spread"] == pytest.approx(0.03, rel=1e-6)
    assert got["over_placebo_net"]["mean"] == pytest.approx(
        got["over_placebo"]["mean"] - 0.03, abs=1e-9)


def test_a_claim_to_lag_is_scored_on_its_own_side():
    prices, events = _book(move=-0.20)
    short = S.measure(prices, BENCH, events, side="underperform", horizon=21)
    long = S.measure(prices, BENCH, events, side="outperform", horizon=21)
    assert short["passes_backtest"] is True and long["passes_backtest"] is False
    assert "borrow cost on the short is not charged" in short["costs"]


def test_a_rule_found_by_searching_needs_the_higher_bar(monkeypatch):
    prices, events = _book()
    assert S.measure(prices, BENCH, events, horizon=21, basis="searched")["t_needed"] == 3.0
    monkeypatch.setattr(S, "T_SEARCHED", 1e9)
    found = S.measure(prices, BENCH, events, horizon=21, basis="searched")
    written = S.measure(prices, BENCH, events, horizon=21, basis="written_first")
    assert found["passes_backtest"] is False and written["passes_backtest"] is True


def test_too_few_events_is_said_and_not_scored():
    prices, events = _book()
    got = S.measure(prices, BENCH, events[:5], horizon=21)
    assert got["passes_backtest"] is False
    assert got["verdict"].startswith("too few to say: 5 events")


def test_events_after_the_rule_was_written_are_counted_apart():
    prices, events = _book()
    got = S.measure(prices, BENCH, events, horizon=21, written=DAYS[200])
    assert got["forward"]["since"] == DAYS[200]
    assert got["forward"]["n"] == sum(1 for e in events
                                      if S.entry_day(DAYS, e["day"]) > DAYS[200])
    assert "since the rule was written" in got["verdict"]


def test_a_window_that_has_not_closed_is_not_measured():
    prices, events = _book()
    got = S.measure(prices, BENCH, [{"company_id": 1, "day": DAYS[-5]}], horizon=21)
    assert got["measured"] == 0 and got["dropped"] == {"window_not_over": 1}


def test_the_measurement_is_the_same_twice():
    prices, events = _book()
    assert S.measure(prices, BENCH, events, horizon=21) == S.measure(
        prices, BENCH, events, horizon=21)


# --- the register -----------------------------------------------------------------------
def test_the_shipped_register_reads_and_every_row_states_its_rule():
    rows = S.register()
    assert rows, "data/signals.csv is empty"
    names = [r["name"] for r in rows]
    assert len(names) == len(set(names))
    for r in rows:
        assert r["rule"] and r["note"] and r["horizon_days"] > 0, r["name"]
    # Every source the code can measure is on the register, so nothing is measured
    # under a rule nobody wrote down.
    assert set(S.SOURCES) <= set(names)


def test_a_row_the_register_cannot_read_is_refused(tmp_path):
    path = tmp_path / "signals.csv"
    path.write_text("name,rule,side,horizon_days,basis,written,status,note\n"
                    "x,some rule,sideways,21,written_first,2026-01-01,registered,n\n")
    with pytest.raises(ValueError):
        S.register(path)


def test_no_event_source_reads_a_column_that_is_not_dated():
    """A source that reads how a thing stands today is using hindsight."""
    for name, source in S.SOURCES.items():
        text = inspect.getsource(source)
        for column in S.UNDATED_COLUMNS:
            assert column not in text, f"{name} reads {column}, which carries no date"


# --- where the events come from -----------------------------------------------------------
@pytest.fixture
def book(tmp_path):
    path = str(tmp_path / "signals.db")
    db.init(path)
    conn = db.get_connection(path)
    for t in ("AAA", "BBB", "CCC"):
        conn.execute("INSERT INTO companies (ticker, name) VALUES (?, ?)", (t, t + " Inc"))
    conn.commit()
    yield conn
    conn.close()


def _form4(conn, company_id, accession, filed, code="P", officer=1, ten=0, form="4",
           derivative=0, side="A", shares=1000.0, price=5.0, row=0):
    conn.execute(
        "INSERT INTO insider_transactions (company_id, accession, row_index, form_type,"
        " filed_date, is_officer, is_ten_percent_owner, transaction_code, shares,"
        " price_per_share, acquired_disposed, is_derivative, url)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'u')",
        (company_id, accession, row, form, filed, officer, ten, code, shares, price, side,
         derivative))


def test_officer_purchases_are_the_first_filing_in_thirty_days(book):
    _form4(book, 1, "a1", "2026-01-05")
    _form4(book, 1, "a2", "2026-01-20")                 # inside thirty days: the same event
    _form4(book, 1, "a3", "2026-03-15")                 # a new one
    _form4(book, 2, "b1", "2026-01-07", ten=1)          # a ten percent holder on the form
    _form4(book, 2, "b2", "2026-01-08", officer=0)      # a director alone
    _form4(book, 2, "b3", "2026-01-09", code="S", side="D")
    _form4(book, 2, "b4", "2026-01-10", derivative=1)
    _form4(book, 2, "b5", "2026-01-11", form="4/A")
    _form4(book, 2, "b6", "2026-01-12", price=None)     # no price stated
    book.commit()
    assert S.officer_purchases(book) == [{"company_id": 1, "day": "2026-01-05"},
                                         {"company_id": 1, "day": "2026-03-15"}]


def _fin(conn, company_id, metric, period_end, value, fy=None, fp=None, kind="instant"):
    conn.execute(
        "INSERT INTO financials (company_id, period_end, period_type, metric, value,"
        " unit, fiscal_year, fiscal_period) VALUES (?, ?, ?, ?, ?, 'USD', ?, ?)",
        (company_id, period_end, kind, metric, value, fy, fp))


def test_a_short_runway_is_dated_when_its_figures_were_public(book):
    # AAA: 50 of cash against 100 a year burnt: six months, at a year end.
    _fin(book, 1, "CashAndEquivalents", "2025-12-31", 50e6)
    _fin(book, 1, "CashFlowOperating", "2025-12-31", -100e6, 2025, "12M", "FY")
    # and a quarter on: trailing burn is the year less last year's quarter plus this one.
    _fin(book, 1, "CashFlowOperating", "2025-03-31", -20e6, 2025, "3M", "Q")
    _fin(book, 1, "CashFlowOperating", "2026-03-31", -30e6, 2026, "3M", "Q")
    _fin(book, 1, "CashAndEquivalents", "2026-03-31", 40e6)
    _fin(book, 1, "ShortTermInvestments", "2026-03-31", 15e6)
    # BBB: three years of cash. CCC: makes money.
    _fin(book, 2, "CashAndEquivalents", "2025-12-31", 300e6)
    _fin(book, 2, "CashFlowOperating", "2025-12-31", -100e6, 2025, "12M", "FY")
    _fin(book, 3, "CashAndEquivalents", "2025-12-31", 10e6)
    _fin(book, 3, "CashFlowOperating", "2025-12-31", 80e6, 2025, "12M", "FY")
    book.commit()
    assert S.short_runway(book) == [{"company_id": 1, "day": "2026-03-31"},
                                    {"company_id": 1, "day": "2026-05-30"}]


def test_the_whole_register_is_built_and_a_signal_with_no_source_says_so(book, tmp_path):
    path = tmp_path / "signals.csv"
    path.write_text(
        "name,rule,side,horizon_days,basis,written,status,note\n"
        "officer_purchase,first officer purchase,outperform,21,searched,2026-01-01,registered,n\n"
        "something_new,a rule with no source,underperform,63,written_first,2026-01-01,dropped,n\n")
    _form4(book, 1, "a1", "2026-01-05")
    book.execute("INSERT INTO benchmark_prices (symbol, as_of, close) VALUES ('XBI', '2026-01-05', 50)")
    book.commit()
    db_path = book.execute("PRAGMA database_list").fetchone()["file"]
    out = S.build(db_path, path)
    assert out["tried"] == 2 and out["dropped"] == 1
    first, second = out["signals"]
    assert first["result"]["events"] == 1 and first["verdict"] == "nothing to measure"
    assert second["verdict"] == "registered; no event source is built for it yet"
    assert out["standard"]["t_searched"] == 3.0
    # The same signal at each liquidity floor, since what can be traded is the reader's.
    assert [f["floor"] for f in first["by_liquidity_floor"]] == list(S.FLOORS)
