"""A bidirectional Streamlit component that draws nothing: it hears clicks on markup the
page has already drawn and returns the clicked drug to Python.

The clinical scorecard of Comps > Indications is a chart and a ranked table drawn as
markdown in the page itself and sized by CSS to the screen (theme.py, --sc-h). Moving
them into a frame, as ``uvboard`` and ``catnav`` do, would hand their height to a script
and their stylesheet to a copy. So this frame stays empty and hidden, and listens on the
parent document instead (the frame is same-origin, as covnav's tab click relies on): a
click or Enter on an element carrying ``data-drug`` inside ``scope`` returns
``{"asset", "from", "nonce"}``, the nonce letting a repeat click on the same drug still
register as a change. A markdown link would reload the page onto a new session and the
first tab; this reruns the session and keeps the tab.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("drugclick", path=str(_DIR))


def drug_click(scope: str, *, key=None):
    """Listen for clicks on ``[data-drug]`` elements under the CSS selector ``scope``.

    Returns ``{"asset", "from", "nonce"}`` for the last click, or None: ``asset`` is the
    element's ``data-drug`` value, ``from`` is "chart" for an SVG mark, else "table"."""
    return _component(scope=scope, key=key, default=None)
