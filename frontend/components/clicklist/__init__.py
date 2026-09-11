"""A bidirectional Streamlit component: a list of rows, each one clickable as a whole.

The forecast tab's book is a ranked list of what each modelled asset is worth a share,
and the row is the natural way to pick the product the rest of the page then shows.
A Streamlit button per row is a separate widget with its own chrome, and a plain link
reloads the page onto the first tab. This renders the rows itself and returns the
clicked row's id to Python, so the row is the hit area and hovering it says it is live.
Same pattern as ``prodcards``, in one column, for any list a page wants to pick from.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("clicklist", path=str(_DIR))


def click_list(rows: list, *, tokens: dict, selected=None, css: str = "",
               key=None):
    """Render ``rows`` (each {id, html}) as a clickable column.

    ``css`` is the stylesheet the rows' own markup needs, since an iframe inherits none
    of the host page's. Returns ``{"id", "nonce"}`` for the last click, or None; the
    nonce lets a repeat click on the same row still register as a change.
    """
    return _component(rows=rows, tokens=tokens, selected=selected, css=css, key=key,
                      default=None)
