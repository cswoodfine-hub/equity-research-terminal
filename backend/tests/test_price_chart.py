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


def test_a_tag_becomes_a_marker_snapped_to_the_nearest_bar():
    tags = [{"id": 1, "entity_id": "2026-07-14", "body": "Q2 print"}]
    marks = price_chart.markers_for(DAILY, tags)
    assert len(marks) == 1
    assert marks[0]["time"] == "2026-07-14" and marks[0]["text"] == "Q2 print"
    assert marks[0]["color"] == TK.FLAG


def test_a_tag_off_the_chart_is_dropped():
    marks = price_chart.markers_for(DAILY, [{"id": 9, "entity_id": "2020-01-01", "body": "x"}])
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
