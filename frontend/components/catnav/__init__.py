"""A bidirectional Streamlit component: the Catalysts tab's timeline and range chart, made
to select a gate.

The redesigned Catalysts tab (frontend/catalysts_view.py) draws every pipeline line's next
gate twice: as a disc on the timeline by therapy area and as a bar on the range chart. A
click on either selects that gate for the card beside them. Markdown cannot run a click
handler and a link reloads the page onto a new session, so this renders the frame's markup
itself and returns the clicked gate to Python. Cloned from ``uvboard``: markup in, one key
out, a nonce so a repeat click on the same gate still registers as a change. The range
chart's two views (the next 24 months, later or undated) switch inside the frame, with no
rerun.

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
    """Render ``markup`` (elements carrying ``data-gate`` are the hit areas).

    Returns ``{"gate", "from", "nonce"}`` for the last click, or None: ``gate`` is the
    asset id of the selected line's gate and ``from`` names the part clicked ("the
    timeline" or "the range chart")."""
    return _component(markup=markup, css=css, tokens=tokens, key=key, default=None)
