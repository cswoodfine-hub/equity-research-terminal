"""A bidirectional Streamlit component: the Catalysts tab's dated readout list, made to
open what a reader clicks.

The page (frontend/catalysts_readouts.py) is drawn here whole: the header, the list and the
rail. The area chips filter the list inside the frame, with no rerun, and the filter stays
across reruns. A click on a row of a priced gate returns ``{"gate", "from", "nonce"}``; on
any other readout ``{"ev", "nonce"}``; on an index row ``{"more", "area", "nonce"}``.
Markdown cannot run a click handler and a link reloads the page onto a new session, so this
renders the markup itself and returns the click to Python. Cloned from ``uvboard``: markup
in, one key out, a nonce so a repeat click on the same thing still registers as a change.
The page fills the room the app's scroller leaves around the frame, read from the parent
page.

An iframe inherits none of the page's CSS, so the frame's stylesheet arrives as ``css``
(tokens, research.css and catalysts.css), the token values as ``tokens`` and the bundled
fonts are copied from the parent's @font-face rules.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("catnav", path=str(_DIR))


def cat_nav(markup: str, *, css: str, tokens: dict, key=None):
    """Render ``markup``: elements carrying ``data-gate``, ``data-ev`` or ``data-more`` are
    the hit areas, a ``.cr-chip`` filters the list to its area in place.

    Returns ``{"gate", "from", "nonce"}``, ``{"ev", "nonce"}`` or ``{"more", "area",
    "nonce"}`` for the last click, or None: ``gate`` is the asset id of the clicked gate,
    ``ev`` the catalyst id of a readout, ``more`` the index key."""
    return _component(markup=markup, css=css, tokens=tokens, key=key, default=None)
