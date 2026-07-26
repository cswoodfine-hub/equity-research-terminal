"""A bidirectional Streamlit component: the lightweight-charts price chart, with
trendline drawing on top.

The one-way ``st.components.v1.html`` embed can render a chart but cannot hear a click,
so drawing had to become a declared component with its own frontend that speaks the
Streamlit message protocol. In draw mode you click two points to add a line, drag an end
to move it, and double-click a line to delete it; the lines round-trip back to Python as
``{t1, p1, t2, p2}`` so they can be persisted and drawn again.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("drawchart", path=str(_DIR))


def draw_chart(*, data, markers, mode, intraday, lines, draw_mode, theme, view_key,
               height: int = 560, key=None):
    """Render the chart and return the current set of drawn lines.

    ``data`` and ``markers`` are the series and event markers already built by
    ``price_chart``. ``lines`` are the persisted drawings passed in and the default the
    component returns until the user changes them. ``view_key`` changes when the interval
    or window changes, telling the frontend to refit rather than keep the old pan/zoom.
    """
    return _component(data=data, markers=markers, mode=mode, intraday=intraday,
                      lines=lines, draw_mode=draw_mode, theme=theme, view_key=view_key,
                      height=height, key=key, default=lines)
