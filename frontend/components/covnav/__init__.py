"""A bidirectional Streamlit component: the coverage small-multiples grid, made to
navigate on a click without a page reload.

Streamlit's ``st.tabs`` cannot be switched from Python and a plain link reload lands on
the first tab, so a coverage-panel click could not reach Key insights for the clicked
company without a full navigation. This component renders the grid's SVG, and on a panel
click it switches the parent app to the Key insights tab (client-side, same origin) and
returns the clicked ticker to Python, which reruns onto that company. No reload, no new
page.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("covnav", path=str(_DIR))


def coverage_nav(svg: str, *, muted: str = "#7E9098", key=None):
    """Render the coverage grid ``svg`` (panels are anchors carrying ?ticker=…). Returns
    ``{"ticker", "nonce"}`` for the last click, or None; the nonce lets a repeat click on
    the same company still register as a change."""
    return _component(svg=svg, muted=muted, key=key, default=None)
