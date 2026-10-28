"""The lightweight-charts price builder: pure functions from bars and tags to series
data, markers and the component HTML. The tests read what it returns.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures synthetic.
The frontend is put on the path the same way ``test_trend.py`` does it.
"""

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import price_chart  # noqa: E402
from components import tokens as TK  # noqa: E402

DAILY = [
    {"as_of": "2026-07-13", "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0},
    {"as_of": "2026-07-14", "open": 103.0, "high": 106.0, "low": 102.0, "close": 101.0},
    {"as_of": "2026-07-15", "open": 101.0, "high": 108.0, "low": 100.5, "close": 107.0},
]
INTRADAY = [
    {"as_of": "2026-07-15 09:30", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5},
    {"as_of": "2026-07-15 09:35", "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5},
]


def test_candlestick_series_carries_full_ohlc():
    data = price_chart.series_data(DAILY, price_chart.CANDLE)
    assert data[0] == {"time": "2026-07-13", "open": 100.0, "high": 104.0,
                       "low": 99.0, "close": 103.0}
    assert len(data) == 3


def test_line_series_is_time_and_close_only():
    data = price_chart.series_data(DAILY, price_chart.LINE)
    assert data[0] == {"time": "2026-07-13", "value": 103.0}


def test_a_candle_missing_part_of_its_ohlc_is_dropped_not_faked():
    bars = DAILY + [{"as_of": "2026-07-16", "open": None, "high": 110.0,
                     "low": 106.0, "close": 109.0}]
    assert len(price_chart.series_data(bars, price_chart.CANDLE)) == 3   # the null bar out
    assert len(price_chart.series_data(bars, price_chart.LINE)) == 4     # line needs close only


def test_intraday_time_is_a_utc_epoch_not_a_date_string():
    data = price_chart.series_data(INTRADAY, price_chart.LINE, intraday=True)
    expected = int(dt.datetime(2026, 7, 15, 9, 30, tzinfo=dt.timezone.utc).timestamp())
    assert data[0]["time"] == expected
    assert data[1]["time"] - data[0]["time"] == 300   # five minutes apart


def test_an_approval_event_is_a_marker_snapped_to_the_nearest_bar():
    events = [{"date": "2026-07-14", "label": "Zepbound", "kind": "approval"}]
    marks = price_chart.event_markers(DAILY, events)
    assert len(marks) == 1
    assert marks[0]["time"] == "2026-07-14" and marks[0]["text"] == "Zepbound"
    assert marks[0]["color"] == TK.UP and marks[0]["position"] == "belowBar"


def test_an_loe_event_takes_the_down_style_above_the_bar():
    events = [{"date": "2026-07-15", "label": "Keytruda LOE", "kind": "loe"}]
    marks = price_chart.event_markers(DAILY, events)
    assert marks[0]["color"] == TK.DOWN and marks[0]["position"] == "aboveBar"


def test_an_event_off_the_chart_is_dropped():
    # A future loss of exclusivity, years past the price history, has no bar to sit on.
    marks = price_chart.event_markers(
        DAILY, [{"date": "2039-01-01", "label": "future LOE", "kind": "loe"}])
    assert marks == []


def test_the_html_bundles_the_library_and_paints_the_chosen_series():
    html = price_chart.chart_html(DAILY, mode=price_chart.CANDLE, ticker="LLY",
                                  currency="USD")
    assert "LightweightCharts" in html and "createChart" in html   # the bundled library
    assert "/* chart-mode: Candlestick */" in html                 # the candle series
    assert TK.GROUND in html and TK.UP in html                     # themed to the palette
    line = price_chart.chart_html(DAILY, mode=price_chart.LINE)
    assert "/* chart-mode: Line */" in line
    assert "addLineSeries({ color:" in line                        # our line call, not candles


# --- a day that carries several events ---------------------------------------

def test_a_day_with_several_events_gets_one_marker_that_counts_the_rest():
    events = [{"date": "2026-07-14", "label": "Verzenio", "kind": "approval"},
              {"date": "2026-07-14", "label": "Taltz LOE", "kind": "loe"},
              {"date": "2026-07-14", "label": "pos 0.25 to 0.92", "kind": "model"}]
    marks = price_chart.event_markers(DAILY, events)
    assert len(marks) == 1, "one bar, one marker"
    assert marks[0]["text"] == "pos 0.25 to 0.92 +2", "the model move leads and counts the rest"
    assert marks[0]["color"] == TK.FLAG


def test_an_approval_leads_a_day_the_analyst_did_not_touch():
    events = [{"date": "2026-07-14", "label": "a trial slipped", "kind": "change"},
              {"date": "2026-07-14", "label": "Verzenio", "kind": "approval"}]
    marks = price_chart.event_markers(DAILY, events)
    assert marks[0]["text"] == "Verzenio +1"
    assert marks[0]["shape"] == "arrowUp"


def test_events_on_different_days_keep_their_own_markers():
    events = [{"date": "2026-07-13", "label": "Verzenio", "kind": "approval"},
              {"date": "2026-07-15", "label": "Taltz LOE", "kind": "loe"}]
    marks = price_chart.event_markers(DAILY, events)
    assert [m["text"] for m in marks] == ["Verzenio", "Taltz LOE"]


# --- the fair value line -----------------------------------------------------

POINTS = [
    {"as_of": "2026-07-13", "fair_value": None, "stated": False, "carried": False},
    {"as_of": "2026-07-14", "fair_value": 80.0, "stated": True, "carried": False},
    {"as_of": "2026-07-15", "fair_value": 80.0, "stated": False, "carried": True},
]


def test_the_fair_value_line_marks_the_days_it_was_stated():
    line = price_chart.forecast_series(POINTS)
    assert [p["value"] for p in line] == [80.0, 80.0]
    assert line[0]["color"] == TK.FLAG, "stated"
    assert line[1]["color"] == TK.MUTED, "carried"


def test_the_line_does_not_reach_back_before_the_first_stated_day():
    line = price_chart.forecast_series(POINTS)
    assert line[0]["time"] == "2026-07-14", "2026-07-13 had no view, so it has no line"


def test_the_fair_value_line_is_left_off_an_intraday_view():
    assert price_chart.forecast_series(POINTS, intraday=True) == [], (
        "the model states a view once a day, not once a bar")


def test_the_fair_value_line_is_clipped_to_the_loaded_bars():
    """The record runs longer than the window on screen, and the chart fits the whole of
    what it is given: an unclipped line would stretch a five-day view to six months."""
    longer = [{"as_of": "2026-01-02", "fair_value": 70.0, "stated": True}] + POINTS
    line = price_chart.forecast_series(longer, bars=DAILY)
    assert [p["time"] for p in line] == ["2026-07-14", "2026-07-15"], (
        "January is outside the loaded bars and never reaches the chart")


def test_no_bars_means_no_clipping():
    longer = [{"as_of": "2026-01-02", "fair_value": 70.0, "stated": True}] + POINTS
    line = price_chart.forecast_series(longer)
    assert line[0]["time"] == "2026-01-02", "nothing to clip against, so nothing is cut"
    assert line[-1]["time"] == "2026-07-15"


def test_the_line_carries_no_whitespace_before_it_starts_or_after_it_ends():
    """Whitespace breaks a line that has started and stopped. Thousands of empty bars to
    draw a fortnight is a payload the component pays for on every render."""
    span = ([{"as_of": f"2026-07-{d:02d}", "fair_value": None, "stated": False}
             for d in (1, 2)]
            + [{"as_of": "2026-07-03", "fair_value": 80.0, "stated": True},
               {"as_of": "2026-07-04", "fair_value": None, "stated": False},
               {"as_of": "2026-07-05", "fair_value": 90.0, "stated": True}]
            + [{"as_of": "2026-07-06", "fair_value": None, "stated": False}])
    line = price_chart.forecast_series(span)
    assert [p["time"] for p in line] == ["2026-07-03", "2026-07-04", "2026-07-05"]
    assert "value" not in line[1], "the gap in the middle still breaks the line"


def test_a_record_with_nothing_stated_draws_nothing():
    blank = [{"as_of": "2026-07-13", "fair_value": None, "stated": False}]
    assert price_chart.forecast_series(blank) == []
