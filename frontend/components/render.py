"""Mount for SVG components.

One place decides how an SVG string reaches the page. Markdown injection is the
path, not ``st.html``: st.html sanitises its input and the sanitiser eats the
SVG wholesale, which surfaced as every component chart silently absent from the
DOM. Markdown with unsafe_allow_html has carried this app's hand-built SVG since
the first rail and keeps the token stylesheet and CSS hover working, because the
markup lands in the main document. Every SVG carries its own viewBox and width,
which is what defeats the hidden-tab measurement defect: nothing is measured at
render time.
"""

from __future__ import annotations

import streamlit as st


def show(svg: str, css_class: str = "chart-mount") -> None:
    """Render one SVG component. An empty string renders nothing, so callers can
    pass a builder's output straight through and let the empty state beside it
    speak instead."""
    if not svg:
        return
    st.markdown(f'<div class="{css_class}">{svg}</div>', unsafe_allow_html=True)
