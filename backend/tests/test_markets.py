"""The standing market level, and the two rules that keep it honest.

A date per cell, because the four sources publish on four calendars, and a refusal
rather than a guess wherever a window holds one observation.
"""

import pytest

import db
import fx
import markets
from fetchers import rates_fred


def _db(tmp_path, name="m.db"):
    path = str(tmp_path / name)
    db.init(path)
    rates_fred.clear_cache()
    return path


def _rate(path, series, as_of, value):
    conn = db.get_connection(path)
    conn.execute("INSERT INTO market_rates (series, as_of, value, source)"
                 " VALUES (?, ?, ?, 'fred')", (series, as_of, value))
    conn.commit()
    conn.close()
    rates_fred.clear_cache()


def test_every_cell_carries_the_day_its_own_source_published(tmp_path):
    """The indexed Treasury series lags two days behind the nominal one. One date over
    the strip would be wrong for whichever series did not publish that day."""
    path = _db(tmp_path)
    _rate(path, "DGS10", "2026-09-18", 0.0501)
    _rate(path, "DFII10", "2026-09-16", 0.0268)
    cells = {c["series"]: c for c in markets.rates(path)}
    assert cells["DGS10"]["as_of"] == "2026-09-18"
    assert cells["DFII10"]["as_of"] == "2026-09-16"
    # A series never fetched is absent, not zero.
    assert cells["T10YIE"]["value"] is None
    assert cells["T10YIE"]["no_change_reason"] == "series not fetched"


def test_one_observation_is_a_level_and_never_a_move(tmp_path):
    path = _db(tmp_path)
    _rate(path, "DGS10", "2026-09-18", 0.0501)
    cell = {c["series"]: c for c in markets.rates(path)}["DGS10"]
    assert cell["value"] == pytest.approx(0.0501)
    assert cell["change_bp"] is None
    assert cell["no_change_reason"] == "one observation in the window"


def test_a_rate_move_is_stated_in_basis_points_from_a_named_day(tmp_path):
    path = _db(tmp_path)
    _rate(path, "DGS10", "2026-06-22", 0.0451)
    _rate(path, "DGS10", "2026-09-18", 0.0501)
    cell = {c["series"]: c for c in markets.rates(path, days=90)}["DGS10"]
    assert cell["change_bp"] == pytest.approx(50.0)
    assert cell["change_from"] == "2026-06-22"


def test_the_window_is_counted_back_from_the_data_not_from_today(tmp_path):
    """Counted from today, a Monday run would report a different window from the
    Friday refresh that filled it, and the strip would drift over a weekend."""
    path = _db(tmp_path)
    _rate(path, "DGS10", "2026-01-02", 0.0400)      # outside a 90-day window
    _rate(path, "DGS10", "2026-06-22", 0.0451)
    _rate(path, "DGS10", "2026-09-18", 0.0501)
    cell = {c["series"]: c for c in markets.rates(path, days=90)}["DGS10"]
    assert cell["change_from"] == "2026-06-22"
    # Widen it and the older point comes into range.
    wide = {c["series"]: c for c in markets.rates(path, days=365)}["DGS10"]
    assert wide["change_from"] == "2026-01-02"


def test_the_credit_series_names_the_owner_that_licences_it(tmp_path):
    """Read internally to set a discount rate, shown with its owner named, and never
    exported: FRED cannot licence ICE's index onward."""
    path = _db(tmp_path)
    cells = {c["series"]: c for c in markets.rates(path)}
    assert cells["BAMLC0A3CAEY"]["restricted_to"] == "ICE Data Indices, LLC"
    assert cells["DGS10"]["restricted_to"] is None


def test_the_crosses_are_the_currencies_the_universe_reports_in(tmp_path):
    """Read off the companies table, so a company added to the seed brings its
    currency onto the strip without a second edit. USD against USD is not a cross."""
    path = _db(tmp_path)
    conn = db.get_connection(path)
    for ticker, currency in (("LLY", "USD"), ("NVO", "DKK"), ("SNY", "EUR"),
                             ("ROG", "CHF"), ("GSK", "GBP")):
        conn.execute("INSERT INTO companies (ticker, name, reporting_currency)"
                     " VALUES (?, ?, ?)", (ticker, ticker, currency))
    conn.commit()
    conn.close()
    assert markets.reporting_currencies(path) == ["CHF", "DKK", "EUR", "GBP"]

    fx.store(path, "2026-07-24", {"EUR": 1.1377, "DKK": 0.1522, "USD": 1.0})
    fx.store(path, "2026-09-21", {"EUR": 1.1490, "DKK": 0.1537, "USD": 1.0})
    cells = {c["base"]: c for c in markets.crosses(path, days=90)}
    assert cells["EUR"]["rate"] == pytest.approx(1.1490)
    assert cells["EUR"]["as_of"] == "2026-09-21"
    assert cells["EUR"]["change_pct"] == pytest.approx(1.1490 / 1.1377 - 1.0)
    # Stored for no currency, so refused rather than filled from a neighbour.
    assert cells["CHF"]["rate"] is None
    assert cells["CHF"]["no_change_reason"] == "no rate stored"


def test_a_benchmark_reports_its_own_date_however_far_behind_it_is(tmp_path):
    """benchmark_prices is written once by beta and is not in the refresh, so its
    newest close can sit weeks behind the rates beside it. Stale must read as stale."""
    path = _db(tmp_path)
    conn = db.get_connection(path)
    for as_of, close in (("2026-06-04", 7584.0), ("2026-09-02", 7669.02)):
        conn.execute("INSERT INTO benchmark_prices (symbol, as_of, close)"
                     " VALUES ('^GSPC', ?, ?)", (as_of, close))
    conn.commit()
    conn.close()
    _rate(path, "DGS10", "2026-09-18", 0.0501)

    built = markets.build(path, days=90)
    bench = built["benchmarks"][0]
    assert bench["symbol"] == "^GSPC"
    assert bench["as_of"] == "2026-09-02"
    assert bench["change_pct"] == pytest.approx(7669.02 / 7584.0 - 1.0)
    # The rate beside it is sixteen days newer, and says so.
    assert built["rates"][0]["as_of"] == "2026-09-18"


def test_the_window_cannot_be_asked_for_more_days_than_are_kept(tmp_path):
    """market_rates keeps KEEP_DAYS of observations. A longer window would carry a
    label the data cannot answer to."""
    path = _db(tmp_path)
    assert markets.build(path, days=100_000)["days"] == rates_fred.KEEP_DAYS
    assert markets.build(path, days=1)["days"] == 5
    assert markets.build(path, days=None)["days"] == markets.DEFAULT_DAYS
