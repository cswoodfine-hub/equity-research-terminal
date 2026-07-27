"""A bidirectional Streamlit component: the product cards, clickable as whole cards.

A Streamlit button under each card is a separate widget with its own chrome, which reads
as a control rather than as the card being the thing you click. This renders the card
grid itself and returns the clicked product's asset id to Python, so the card is the hit
area and hovering it shows it is live. Same pattern as ``covnav``, minus the tab switch:
the profile opens on the same tab, so a plain rerun is enough.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("prodcards", path=str(_DIR))


def product_cards(cards: list, *, tokens: dict, selected=None, key=None):
    """Render ``cards`` (each {asset_id, html}) as a clickable grid.

    Returns ``{"asset_id", "nonce"}`` for the last click, or None. The nonce lets a repeat
    click on the same card still register as a change, so reopening a profile the analyst
    just closed works.
    """
    return _component(cards=cards, tokens=tokens, selected=selected, key=key,
                      default=None)
