"""Mount for SVG components.

One place decides how an SVG string reaches the page. ``st.html`` injects into the
main DOM, so the token stylesheet applies and CSS hover works with no server round
trip. Every SVG carries its own viewBox and width, which is what defeats the
hidden-tab measurement defect: nothing is measured at render time.
"""

from __future__ import annotations

import streamlit as st


def show(svg: str, css_class: str = "chart-mount") -> None:
    """Render one SVG component. An empty string renders nothing, so callers can
    pass a builder's output straight through and let the empty state beside it
    speak instead."""
    if not svg:
        return
    st.html(f'<div class="{css_class}">{svg}</div>')
