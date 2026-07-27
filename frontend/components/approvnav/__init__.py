"""A bidirectional Streamlit component: the approvals timeline, made to open a product.

``st.tabs`` cannot be switched from Python and a link reload lands on the first tab, so
a click on an approval could not reach that product's fact sheet without a full page
navigation. This renders the timeline's SVG, and on a click it switches the parent app
to the Portfolio tab, client-side and same-origin, and returns the clicked approval's
key to Python, which reruns onto that company and opens its profile. No reload.

The same shape as ``covnav``: one SVG in, one clicked key out, keyed by a nonce so a
repeat click on the same approval still registers as a change.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("approvnav", path=str(_DIR))


def approvals_nav(svg: str, *, muted: str = "#7E9098", key=None):
    """Render the approvals timeline ``svg``, whose marks carry ``data-nav`` keys.
    Returns ``{"key", "nonce"}`` for the last click, or None."""
    return _component(svg=svg, muted=muted, key=key, default=None)
