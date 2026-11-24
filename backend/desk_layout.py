"""The Trading tab's saved boards: named arrangements of panels, kept on this machine.

A board is which panels are up, in what order, each for which company. It is the
reader's own working surface and nothing the book computes, so it is kept the way
``my_portfolio`` keeps its settings: one JSON file under ``backend/cache/``, which git
ignores. Two things follow from where it sits and both are on purpose.

- It is outside ``data/`` and outside the database. ``response_cache`` stamps every held
  read with the newest change to either, so a board saved there would have every
  company's valuation worked out again to protect reads it cannot have changed.
- It is this machine's and no other's. A copy of the app running elsewhere starts with
  no boards, and one hosted where the disk is not kept loses them on a restart.

What a panel *is* belongs to the frontend (``frontend/trading_view.PANELS``), which makes
a saved board safe to draw and says what it left out. This module holds the shape only:
names, counts and types, so a file cannot grow without limit or carry anything but a
board.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import db

MAX_BOARDS = 24
MAX_PANELS = 24                  # per board, as stored; the page draws fewer
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-]{0,39}$")
_KIND = re.compile(r"^[a-z][a-z_]{0,39}$")
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def path() -> Path:
    """Where the boards are kept. ``ER_TOOL_LAYOUTS`` moves it, for a test or a copy."""
    return Path(os.getenv("ER_TOOL_LAYOUTS") or db.BACKEND_DIR / "cache" / "trading_layouts.json")


def clean_name(name) -> str | None:
    """The name as it is kept, or None where it is not one: letters, digits, spaces and
    ``. _ -``, forty characters at most."""
    text = " ".join(str(name or "").split())
    return text if _NAME.match(text) else None


_ID = re.compile(r"^p[0-9]{1,4}$")
# A place and a size on the board's grid, in cells: a column, a row, a width, a height.
# The frontend brings each to what fits its grid; here a value only has to be a whole
# number in a range no board can need more than.
_PLACE = {"x": 64, "y": 4000, "w": 64, "h": 64}


def _cell(value, most: int):
    ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= most
    return value if ok else None


def clean_board(layout) -> dict | None:
    """A board reduced to its shape, or None where it is not a board. Nothing is
    repaired: a panel that is not a kind and a company is left out, and a place that is
    not a whole number in range is left out for the frontend to fill. A board saved
    before panels had a place keeps its "columns" and "wide", which say how it was
    drawn then."""
    if not isinstance(layout, dict) or not isinstance(layout.get("panels"), list):
        return None
    panels = []
    for raw in layout["panels"][:MAX_PANELS]:
        if not isinstance(raw, dict) or not isinstance(raw.get("panel"), str):
            continue
        if not _KIND.match(raw["panel"]):
            continue
        ticker = raw.get("ticker")
        entry = {"panel": raw["panel"],
                 "ticker": ticker if isinstance(ticker, str) and _TICKER.match(ticker) else None}
        if isinstance(raw.get("id"), str) and _ID.match(raw["id"]):
            entry["id"] = raw["id"]
        for key, most in _PLACE.items():
            if _cell(raw.get(key), most) is not None:
                entry[key] = raw[key]
        if isinstance(raw.get("wide"), bool):
            entry["wide"] = raw["wide"]
        panels.append(entry)
    board = {"ask": layout.get("ask") is not False, "panels": panels}
    if layout.get("columns") in (1, 2, 3):
        board["columns"] = layout["columns"]
    return board


def load() -> dict:
    """{"boards": {name: board}, "current": name or None, "problem": why or None}. A
    file that is missing is no boards. One that cannot be read is no boards and the
    reason, and it is left as it is: nothing here overwrites what it could not read
    until the reader saves again."""
    file = path()
    try:
        held = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"boards": {}, "current": None, "problem": None}
    except (OSError, ValueError) as exc:
        return {"boards": {}, "current": None,
                "problem": f"the saved boards could not be read: {exc}"}
    boards = {}
    for name, layout in (held.get("boards") or {}).items() if isinstance(held, dict) else ():
        kept_name, kept = clean_name(name), clean_board(layout)
        if kept_name and kept is not None and len(boards) < MAX_BOARDS:
            boards[kept_name] = kept
    current = held.get("current") if isinstance(held, dict) else None
    return {"boards": boards, "current": current if current in boards else None,
            "problem": None}


def _write(boards: dict, current) -> None:
    """The whole file at once, by way of a second file beside it, so a write that is cut
    short leaves the boards as they were and never half a file."""
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    spare = file.with_name(file.name + ".writing")
    spare.write_text(json.dumps({"version": 1, "current": current, "boards": boards},
                                indent=1, sort_keys=True), encoding="utf-8")
    os.replace(spare, file)


def save(name, layout) -> dict:
    """Keep a board under a name and make it the one that opens next time.
    {"ok": True, ...the boards as ``load`` gives them} or {"ok": False, "reason"}."""
    kept_name, kept = clean_name(name), clean_board(layout)
    if not kept_name:
        return {"ok": False, "reason": "A board's name is letters, digits, spaces and "
                                       ". _ - only, forty characters at most."}
    if kept is None:
        return {"ok": False, "reason": "That is not a board: it has no list of panels."}
    held = load()
    if held["problem"]:
        return {"ok": False, "reason": held["problem"]}
    boards = held["boards"]
    if kept_name not in boards and len(boards) >= MAX_BOARDS:
        return {"ok": False, "reason": f"{MAX_BOARDS} boards are saved, which is the "
                                       "limit. Delete one first."}
    boards[kept_name] = kept
    try:
        _write(boards, kept_name)
    except OSError as exc:
        return {"ok": False, "reason": f"the board could not be written: {exc}"}
    return {"ok": True, **load()}


def remove(name) -> dict:
    """Forget a board. Removing one that is not there is not an error."""
    held = load()
    if held["problem"]:
        return {"ok": False, "reason": held["problem"]}
    kept_name = clean_name(name)
    if kept_name in held["boards"]:
        del held["boards"][kept_name]
        current = held["current"] if held["current"] != kept_name else None
        try:
            _write(held["boards"], current)
        except OSError as exc:
            return {"ok": False, "reason": f"the board could not be deleted: {exc}"}
    return {"ok": True, **load()}
