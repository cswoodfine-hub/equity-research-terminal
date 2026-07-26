"""The interactive price figure builder: the tests read the Plotly figure it returns.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures synthetic.
The frontend is put on the path the same way ``test_trend.py`` does it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import price_chart  # noqa: E402
from components import tokens as TK  # noqa: E402

ROWS = [
    {"as_of": "2026-07-13", "open": 100.0, "high": 104.0, "low": 99.0, "close": 103.0},
    {"as_of": "2026-07-14", "open": 103.0, "high": 106.0, "low": 102.0, "close": 101.0},
    {"as_of": "2026-07-15", "open": 101.0, "high": 108.0, "low": 100.5, "close": 107.0},
]


def _types(fig):
    return [t.type for t in fig.data]


def test_line_mode_is_a_scatter_and_never_a_candlestick():
    fig = price_chart.figure(ROWS, mode=price_chart.LINE, ticker="LLY")
    assert "scatter" in _types(fig)
    assert "candlestick" not in _types(fig)


def test_candlestick_mode_draws_candles_in_the_direction_colours():
    fig = price_chart.figure(ROWS, mode=price_chart.CANDLE, ticker="LLY")
    candles = [t for t in fig.data if t.type == "candlestick"]
    assert len(candles) == 1
    assert candles[0].increasing.line.color == TK.UP
    assert candles[0].decreasing.line.color == TK.DOWN


def test_a_tag_becomes_a_marker_carrying_its_body_on_the_matching_bar():
    tags = [{"id": 1, "entity_id": "2026-07-14", "body": "Q2 print"}]
    fig = price_chart.figure(ROWS, tags, mode=price_chart.LINE)
    marks = [t for t in fig.data if t.name == "tags"]
    assert len(marks) == 1
    assert "Q2 print" in marks[0].customdata           # full body on hover
    assert marks[0].y == (101.0,)                       # placed at that bar's close
    assert marks[0].marker.color == TK.FLAG


def test_a_tag_on_a_bar_that_is_not_in_the_window_is_not_drawn():
    tags = [{"id": 9, "entity_id": "2020-01-01", "body": "off the chart"}]
    fig = price_chart.figure(ROWS, tags, mode=price_chart.LINE)
    assert not [t for t in fig.data if t.name == "tags"]


def test_the_figure_wears_the_dark_theme_and_a_fixed_height():
    fig = price_chart.figure(ROWS, mode=price_chart.LINE)
    assert fig.layout.paper_bgcolor == TK.GROUND
    assert fig.layout.plot_bgcolor == TK.GROUND
    assert fig.layout.height == 540
    assert fig.layout.dragmode == "pan"
    assert fig.layout.xaxis.rangeslider.visible is True
