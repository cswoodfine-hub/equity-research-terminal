"""A bidirectional Streamlit component: the Comps tab's valuation view.

One iframe holds the whole workspace: the context bar, the conclusion banner, the KPI
strip, the comparable-company table, the two charts, the bridge and the panels under
them. The payload of ``GET /comps/valuation`` arrives once, whole, and every change of
peer set, basis, currency, preset, filter, exclusion or bridge input is recomputed by
``core.js`` inside the frame. Python hears two things only (design spec 7.5): a change
of focal company, ``{"action": "focus", "ticker", "nonce"}``, and a reload,
``{"action": "reload", "nonce"}``. The nonce makes a repeat of the same action a fresh
value.

Three rules the wrapper keeps:

- Strict JSON. Streamlit serialises args with plain ``json.dumps``, so a NaN would go
  out as a bare ``NaN`` and the frame's ``JSON.parse`` would throw. ``_jsonable`` turns
  a non-finite float into None and a numpy scalar into a Python one, and a
  ``json.dumps(allow_nan=False)`` pass fails loud if anything slipped through.
- A digest of the payload, so the frame can skip its rebuild when a render message was
  re-sent only because the frame's width or height moved.
- A fixed key, so a new focal company or a reload does not remount the iframe: sort,
  scroll and open panels survive the rerun. ``tab_index=0`` lets a keyboard user Tab in.

The shared research stylesheet (``assets/research.css``) is read once at import and
passed as ``shared_css``; the frame writes it ahead of its own sheets, so the Streamlit
tabs and this view read the same primitives from one file.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import streamlit.components.v1 as components

_DIR = Path(__file__).resolve().parent
_component = components.declare_component("compsval", path=str(_DIR))

# Read once: the file does not change while the app runs, and a rerun should not touch
# the disk for it.
SHARED_CSS = (_DIR.parent.parent / "assets" / "research.css").read_text()


def _jsonable(value):
    """Strict JSON for the iframe: NaN and infinities become None, numpy scalars become
    their Python values, tuples become lists and every key a string. Nothing is
    rounded or filled: a missing value stays None."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (bytes, bytearray)):
        return _jsonable(value.item())  # a numpy scalar
    return value


def _digest(clean: dict) -> str:
    """Twelve hex characters of the payload's canonical JSON. ``allow_nan=False`` makes
    a non-finite number an error here, in development and in tests, rather than a
    ``JSON.parse`` failure inside the frame."""
    blob = json.dumps(clean, sort_keys=True, allow_nan=False, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def comps_valuation(payload: dict, *, focal: str, engine: str, tokens: dict, live: bool,
                    height: int = 900, key: str = "compsval"):
    """Render the valuation view and return the frame's last action.

    ``payload`` is the ``GET /comps/valuation`` body, all 70 companies. ``focal`` is the
    app-wide company (``company_pick``), ``engine`` the open engine ('' when a shared
    link named none), ``tokens`` the ``COMPS_TOKENS`` map the frame installs as custom
    properties, and ``live`` False while the time machine is set, which the view does
    not follow and says so. ``height`` is the first frame height, used for the loading
    skeleton and as the fallback when the frame cannot measure the page.

    Returns ``{"action": "focus", "ticker", "nonce"}``, ``{"action": "reload",
    "nonce"}``, or None before the first action.
    """
    clean = _jsonable(payload or {})
    digest = _digest(clean)
    return _component(payload=clean, digest=digest, focal=focal or "",
                      engine=engine or "", tokens=_jsonable(dict(tokens or {})),
                      live=bool(live), shared_css=SHARED_CSS, height=int(height),
                      key=key, default=None, tab_index=0)
