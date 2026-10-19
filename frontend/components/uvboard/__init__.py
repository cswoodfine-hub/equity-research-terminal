"""A bidirectional Streamlit component: the Universe tab's hero band, made to open a company.

The redesigned Universe tab (frontend/universe_cc.py) draws a price against value map and
a company board side by side, and a click on a bubble or a board row opens that company's
detail. Markdown cannot run a click handler and a link reloads the page onto a new
session, so this renders the band's markup itself and returns the clicked company to
Python, which opens the dialog. Cloned from ``clicklist`` and ``covnav``: markup in, one
key out, a nonce so a repeat click on the same company still registers as a change.

An iframe inherits none of the page's CSS, so the band's stylesheet arrives as ``css``
(tokens, research.css and universe.css), the token values as ``tokens`` and the bundled
fonts are copied from the parent's @font-face rules.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("uvboard", path=str(_DIR))


def uv_board(markup: str, *, css: str, tokens: dict, key=None):
    """Render ``markup`` (elements carrying ``data-ticker`` are the hit areas).

    Returns ``{"ticker", "from", "nonce"}`` for the last click, or None: ``from`` names
    the part clicked, read off the nearest ``data-from`` ("the news", "the board", "the
    ribbon"), else "the map" or "the board"."""
    return _component(markup=markup, css=css, tokens=tokens, key=key, default=None)
