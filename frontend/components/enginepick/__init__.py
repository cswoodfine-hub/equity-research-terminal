"""A bidirectional Streamlit component: the landing page, clickable as whole panels.

The front door has one job, which is to ask which part of the terminal you want and
answer as much of the question as it can before you click. A Streamlit button under each
panel is a separate widget with its own chrome, which reads as a control beneath a poster
rather than as the poster being the thing you click. This renders the hero, the three
engine panels and the signal strip, and returns what was clicked, so a panel is its own
hit area and hovering it shows it is live.

Same pattern as ``prodcards``: server-built HTML, tokens passed in because the host page's
CSS variables do not cross into the iframe, and a nonce on every value so a repeat click
still registers as a change.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("enginepick", path=str(_DIR))


def engine_pick(panels: list, *, hero: str, signals_html: str, tokens: dict, key=None):
    """Render the landing page and report the click.

    ``panels`` is [{engine, html}]; ``hero`` and ``signals_html`` are complete markup.
    Returns ``{"engine": key, "nonce"}`` for a panel, ``{"ticker": tk, "nonce"}`` for a
    signal row, or None when nothing has been clicked.
    """
    return _component(panels=panels, hero=hero, signals_html=signals_html,
                      tokens=tokens, key=key, default=None)
