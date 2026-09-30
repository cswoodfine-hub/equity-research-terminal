"""A bidirectional Streamlit component: the Comps tab's valuation view.

One iframe holds the whole workspace: the context bar, the conclusion banner, the KPI
strip, drivers and risks, the two charts and the comparable-company table, with the
company panel, the peer drawer and the methodology drawer at its right. The payload of
``GET /comps/valuation`` arrives once, whole, and every change of peer set, basis,
currency, preset, filter, exclusion or bridge input is recomputed by ``core.js`` inside
the frame. Python hears three things only (design spec 7.5 and 12.9): a change of focal
company, ``{"action": "focus", "ticker", "nonce"}``, a reload, ``{"action": "reload",
"nonce"}``, and a link to one indication of the landscape, ``{"action": "indication",
"indication_id", "ticker", "nonce"}``. The nonce makes a repeat of the same action a
fresh value.

The same component draws the valuation bridge on the Forecast tab (spec 12.5):
``mode="bridge"`` is that one section and nothing else, under its own key, reading the
peer set and metric chosen in Comps from the browser storage both frames share. A
bridge frame sends nothing back.

Three rules the wrapper keeps:

- Strict JSON. Streamlit serialises args with plain ``json.dumps``, so a NaN would go
  out as a bare ``NaN`` and the frame's ``JSON.parse`` would throw. ``_jsonable`` turns
  a non-finite float into None and a numpy scalar into a Python one, and a
  ``json.dumps(allow_nan=False)`` pass fails loud if anything slipped through.
- A digest of the payload and one of the focal context, so the frame can skip its
  rebuild when a render message was re-sent only because the frame's width or height
  moved.
- A fixed key per mode, so a new focal company or a reload does not remount the iframe:
  sort, scroll and open panels survive the rerun. ``tab_index=0`` lets a keyboard user
  Tab in.

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


# The revision of the design spec this wrapper implements. The app checks it on import:
# a running server does not re-import a module that sits under a dot-directory, as a
# worktree does, so a script newer than the wrapper in memory reloads the wrapper rather
# than call it with arguments it does not take.
REVISION = 3

MODES = ("full", "bridge")
# Per mode: the component key and the first frame height. The full view is fitted to
# the viewport by the frame; the bridge is a block in the Forecast tab's flow and sets
# its own height from its content.
_DEFAULTS = {"full": ("compsval", 900), "bridge": ("compsval_bridge", 360)}


def _without_detail(clean: dict) -> dict:
    """The payload with every company's ``detail`` record left out. The bridge reads a
    peer multiple and the focal company's per-share inputs, never the side panel's
    record, and that record is two fifths of the payload."""
    companies = clean.get("companies")
    if not isinstance(companies, list):
        return clean
    out = dict(clean)
    out["companies"] = [
        {k: v for k, v in record.items() if k != "detail"}
        if isinstance(record, dict) else record
        for record in companies]
    return out


def comps_valuation(payload: dict, *, focal: str, engine: str, tokens: dict, live: bool,
                    context=None, mode: str = "full", height=None, key=None):
    """Render the valuation view, or its bridge alone, and return the frame's last
    action.

    ``payload`` is the ``GET /comps/valuation`` body, all 70 companies. ``focal`` is the
    app-wide company (``company_pick``), ``engine`` the open engine ('' when a shared
    link named none), ``tokens`` the ``COMPS_TOKENS`` map the frame installs as custom
    properties, and ``live`` False while the time machine is set, which the view does
    not follow and says so.

    ``context`` is the ``GET /companies/{ticker}/comps-context`` body for the focal
    company, or ``{"ticker", "error"}`` when that read failed; None leaves the two
    evidence groups of Drivers and risks pending. ``mode`` is ``"full"`` or
    ``"bridge"``. The bridge takes no context and no ``detail`` records. ``height`` is
    the first frame height, used for the loading skeleton and as the fallback when the
    frame cannot measure the page; ``key`` and ``height`` default per mode.

    Returns ``{"action": "focus", "ticker", "nonce"}``, ``{"action": "reload",
    "nonce"}``, ``{"action": "indication", "indication_id", "ticker", "nonce"}``, or
    None before the first action. A bridge frame never sets a value.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    default_key, default_height = _DEFAULTS[mode]
    clean = _jsonable(payload or {})
    if mode == "bridge":
        clean = _without_detail(clean)
        context = None
    digest = _digest(clean)
    clean_context = None if context is None else _jsonable(context)
    context_digest = "" if clean_context is None else _digest(clean_context)
    return _component(payload=clean, digest=digest, focal=focal or "",
                      engine=engine or "", tokens=_jsonable(dict(tokens or {})),
                      live=bool(live), shared_css=SHARED_CSS,
                      height=int(default_height if height is None else height),
                      mode=mode, context=clean_context, context_digest=context_digest,
                      key=key or default_key, default=None, tab_index=0)
