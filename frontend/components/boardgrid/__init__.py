"""The Trading tab's board as something to take hold of: move a panel by its heading,
size it by any corner.

Streamlit lays the panels out on a CSS grid (``trading_view.grid_css``) and has no way to
drag one. This is a frame of no height whose script works on the page that holds it,
which it can reach because a component's frame is served from the page's own origin
(``universe_page.click_pending_tab`` and ``covnav`` reach it the same way). It draws its
handles in a layer of its own laid over the panels, and never touches the elements
Streamlit draws, so nothing it does can upset the page's own rendering. While the reader
drags, an outline shows the place and size the panel will take, snapped to the grid's
cells. On release it sends that place, and Python settles the board round it
(``trading_view.place``) and draws it again.
"""

from __future__ import annotations

from pathlib import Path

import streamlit.components.v1 as components

REVISION = 1
_DIR = Path(__file__).resolve().parent
_component = components.declare_component("boardgrid", path=str(_DIR))


def board_grid(*, panels, cols: int, row_px: int, gap_px: int, theme: dict, key=None):
    """Draw the handles over the board and return the last place the reader set, as
    ``{"token", "n", "id", "x", "y", "w", "h"}``, or None before the first.

    ``token`` is new each time the frame loads and ``n`` counts within it, so a caller
    can tell a new placing from the same one returned again on a later run.
    ``panels`` are ``trading_view.grid_spec``'s rows.
    """
    return _component(panels=panels, cols=cols, row_px=row_px, gap_px=gap_px,
                      theme=theme, key=key, default=None)
