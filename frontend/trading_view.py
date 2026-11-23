"""The Trading tab's board: which panels exist, how a set of them is laid out, and the
markup of the panels no other page draws.

Pure. Every function takes plain values and returns plain values or a markup string;
none touches Streamlit, the network or a clock, so the tests run them on dicts. The
Streamlit side is ``trading_page.py``.

A board is a list of panels. Each is one of the kinds in ``PANELS`` and is drawn for the
top bar's company unless it is pinned to another, which is how two companies come to sit
side by side. A panel kind appears in ``PANELS`` only once it is built: the picker offers
what works, and the design note (docs/design/trading-tab.md) carries the rest of the list.

Nothing here is a signal, an order or advice. A figure a source does not have is printed
as "no free data" and never as a nought.
"""

from __future__ import annotations

import html
import re

NO_DATA = "no free data"

# The order the picker lists them in: the market first, then what was said and filed,
# then what is dated ahead, then the book's own reading of it, which is the least proven.
GROUPS = ("Market", "News", "Fiscal", "Catalysts", "The book's view", "Positioning",
          "Your record", "Free-form")

# cost: "free" is a read the page has already made, "light" is one read of the book,
# "heavy" runs the forecast when the cache is cold, "live" asks a source outside the book.
COSTS = ("free", "light", "heavy", "live")

# One entry a kind of panel. ``reads`` is what it asks the API, with {ticker} for the
# panel's company. ``private`` marks a panel built on the reader's own holdings: it is
# drawn on their screen and is never named to the model (see ``showing``).
PANELS = (
    {"id": "changes", "title": "What changed", "group": "News", "wide": False,
     "cost": "free", "private": False, "reads": ("/changes?ticker={ticker}",),
     "about": "The company's changes rated high in the last 30 days, newest first."},
    {"id": "news", "title": "Company news", "group": "News", "wide": False,
     "cost": "light", "private": False, "reads": ("/companies/{ticker}/news",),
     "about": "Headlines, press releases and the daily pulse's items for the company."},
    {"id": "catalysts", "title": "Dated ahead", "group": "Catalysts", "wide": False,
     "cost": "light", "private": False,
     "reads": ("/catalysts?within_days={days}&ticker={ticker}",),
     "about": "Every dated catalyst in the next 24 months, by month."},
)
BY_ID = {panel["id"]: panel for panel in PANELS}

MAX_PANELS = 12          # a board past this is a page nobody reads to the end
MAX_LIVE = 4             # each live price is two Yahoo requests a minute while in session
COLUMNS = (1, 2, 3)
DEFAULT_COLUMNS = 2
# What a reader sees before they have chosen anything.
DEFAULT_PANELS = ("changes", "news", "catalysts")

# A ticker as the book writes one: LLY, NOVO-B.CO, 4568.T. Anything else is not sent on.
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def clean_ticker(value):
    """The ticker in the book's form, or None where it is not one."""
    text = str(value or "").strip().upper()
    return text if TICKER.match(text) else None


def item(panel: str, ticker=None, wide=None) -> dict:
    """One panel on a board. ``ticker`` None follows the top bar; ``wide`` None takes the
    kind's own width."""
    return {"panel": panel, "ticker": ticker, "wide": wide}


def default_layout() -> dict:
    return {"columns": DEFAULT_COLUMNS, "ask": True,
            "panels": [item(panel) for panel in DEFAULT_PANELS]}


def normalise(layout) -> tuple:
    """A layout made safe to draw, and what was left out of it, in words.

    A saved board outlives the code that saved it: a panel kind can be renamed or
    withdrawn, a file can be edited by hand. Nothing unknown is guessed at. It is dropped
    and the reader is told, so a board never draws a panel it cannot name.
    """
    left_out = []
    if not isinstance(layout, dict):
        return default_layout(), ["the saved board could not be read, so the default is shown"]
    columns = layout.get("columns")
    if columns not in COLUMNS:
        columns = DEFAULT_COLUMNS
    kept, live = [], 0
    for raw in layout.get("panels") or []:
        if not isinstance(raw, dict) or raw.get("panel") not in BY_ID:
            name = raw.get("panel") if isinstance(raw, dict) else raw
            left_out.append(f"a panel this version does not have: {str(name)[:40]}")
            continue
        kind = BY_ID[raw["panel"]]
        if len(kept) >= MAX_PANELS:
            left_out.append(f"{kind['title']}: a board holds {MAX_PANELS} panels")
            continue
        if kind["cost"] == "live":
            if live >= MAX_LIVE:
                left_out.append(f"{kind['title']}: a board holds {MAX_LIVE} live panels")
                continue
            live += 1
        pinned = raw.get("ticker")
        ticker = clean_ticker(pinned) if pinned else None
        if pinned and not ticker:
            left_out.append(f"{kind['title']}: {str(pinned)[:20]} is not a ticker, so it "
                            "follows the top bar")
        wide = raw.get("wide") if isinstance(raw.get("wide"), bool) else None
        kept.append(item(kind["id"], ticker, wide))
    return {"columns": columns, "ask": layout.get("ask") is not False,
            "panels": kept}, left_out


def from_ids(ids, columns=DEFAULT_COLUMNS, ask=True) -> dict:
    """A board of the named kinds in the registry's order, each following the top bar."""
    wanted = set(ids or [])
    return {"columns": columns, "ask": ask,
            "panels": [item(panel["id"]) for panel in PANELS if panel["id"] in wanted]}


def is_wide(entry: dict) -> bool:
    if isinstance(entry.get("wide"), bool):
        return entry["wide"]
    return bool(BY_ID[entry["panel"]]["wide"])


def pack(panels, columns: int) -> list:
    """The board as rows. A wide panel takes a row to itself; the others fill a row left
    to right in the order given, so the order a reader set is the order they read in."""
    columns = columns if columns in COLUMNS else DEFAULT_COLUMNS
    rows, run = [], []
    for entry in panels or []:
        if is_wide(entry) or columns == 1:
            if run:
                rows.append(run)
                run = []
            rows.append([entry])
            continue
        run.append(entry)
        if len(run) == columns:
            rows.append(run)
            run = []
    if run:
        rows.append(run)
    return rows


def company_of(entry: dict, ticker: str) -> str:
    """The company a panel is drawn for: its own where pinned, else the top bar's."""
    return entry.get("ticker") or ticker


def heading(entry: dict, ticker: str) -> str:
    """The panel's title rule: what it is and whose, with a pinned company marked."""
    kind = BY_ID[entry["panel"]]
    whose = company_of(entry, ticker)
    pin = '<span class="td-pin">pinned</span>' if entry.get("ticker") else ""
    return (f'<div class="td-head"><span class="td-title">{esc(kind["title"])}</span>'
            f'<span class="td-co">{esc(whose)}</span>{pin}</div>')


def showing(panels, ticker: str) -> list:
    """What is on screen, as the Ask box may be told it: the kind of each panel and its
    company, and nothing a panel shows. A private panel is left out, because naming it
    beside a ticker would say the reader holds that stock."""
    out, seen = [], set()
    for entry in panels or []:
        kind = BY_ID.get(entry.get("panel"))
        if not kind or kind["private"]:
            continue
        pair = (kind["id"], company_of(entry, ticker))
        if pair not in seen and clean_ticker(pair[1]):
            seen.add(pair)
            out.append({"panel": pair[0], "ticker": pair[1]})
    return out


def picker_options() -> list:
    """The kinds a reader can add, grouped as the picker lists them: (group, [kinds])."""
    return [(group, [panel for panel in PANELS if panel["group"] == group])
            for group in GROUPS if any(panel["group"] == group for panel in PANELS)]
