"""A bidirectional Streamlit component: the front door, three doors, nothing else.

The page has one question and it is which engine you want. It used to answer as much of
that question as it could before you clicked, with a distribution and a leader board and
the week's signals on each card, and that made the first thing anyone saw a dashboard
they had not asked for. So the figures are gone. What is left is a poster per engine: a
drawn motif, a name, and the line that says what the cohort is for.

Nothing here is a measurement, so nothing here is computed. The motifs are generated in
the component itself from constants, and the only arguments are the three engine names.

A Streamlit button under each card would be a separate widget with its own chrome, which
reads as a control beneath a poster rather than the poster being the thing you click. So
the card is its own hit area and hovering it shows it is live.

Same pattern as ``prodcards``: tokens passed in because the host page's CSS variables do
not cross into the iframe, and a nonce on every value so a repeat click still registers
as a change.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("enginepick", path=str(_DIR))


def engine_pick(panels: list, *, tokens: dict, key=None):
    """Render the front door and report the click.

    ``panels`` is [{engine, label, tagline}]. Returns ``{"engine": key, "nonce"}`` for a
    card, or None when nothing has been clicked.
    """
    return _component(panels=panels, tokens=tokens, key=key, default=None)
