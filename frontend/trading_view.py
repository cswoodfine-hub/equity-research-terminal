"""The Trading tab's board: which panels exist, how a set of them is laid out, and the
markup of the panels no other page draws.

Pure. Every function takes plain values and returns plain values or a markup string;
none touches Streamlit, the network or a clock, so the tests run them on dicts. The
Streamlit side is ``trading_page.py``.

A board is a list of panels. Each is one of the kinds in ``PANELS`` and is drawn for the
top bar's company unless it is pinned to another, which is how two companies come to sit
side by side. A panel kind appears in ``PANELS`` only once it is built: the picker offers
what works, and the design note (docs/design/trading-tab.md) carries the rest of the list.

A panel leads with a figure, not a list. What is dated, said or changed is drawn on a time
grid first (``charts.unit_lanes``), so when and how much is read at a glance; the few
items that matter are named under it; and the full list is folded beneath, one click
away. Seventy rows of text answer neither question until they have been read to the end.

Nothing here is a signal, an order or advice. A figure a source does not have is printed
as "no free data" and never as a nought.
"""

from __future__ import annotations

import datetime as dt
import html
import re

from components import charts as CH
from components import tokens as TK

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
    {"id": "price", "title": "Price chart", "group": "Market", "wide": True,
     "cost": "live", "private": False,
     "reads": ("/companies/{ticker}/prices", "/companies/{ticker}/prices/live",
               "/companies/{ticker}/approvals"),
     "about": "The daily price with Yahoo's live read over it, and approvals marked."},
    {"id": "fundamentals", "title": "Fundamentals", "group": "Fiscal", "wide": True,
     "cost": "heavy", "private": False,
     "reads": ("/companies/{ticker}/report", "/companies/{ticker}/street",
               "/companies/{ticker}/cashflow", "/companies/{ticker}/runway",
               "/companies/{ticker}/relative", "/screen"),
     "about": "The figures a price is set on: growth, the street's view, valuation, cash."},
    {"id": "news", "title": "Company news", "group": "News", "wide": False,
     "cost": "light", "private": False, "reads": ("/companies/{ticker}/news",),
     "about": "Releases, 8-K headlines and the daily pulse's items, by month and source."},
    {"id": "results", "title": "Latest results", "group": "Fiscal", "wide": False,
     "cost": "light", "private": False, "reads": ("/companies/{ticker}/report",),
     "about": "The last reported period: what it was, and how it landed against the street."},
    {"id": "trend", "title": "Growth and margin", "group": "Fiscal", "wide": False,
     "cost": "light", "private": False,
     "reads": ("/companies/{ticker}/statements?basis=annual",),
     "about": "Revenue growth and net margin by year, with the latest period's figures."},
    {"id": "filings", "title": "Filings", "group": "Fiscal", "wide": False,
     "cost": "light", "private": False, "reads": ("/companies/{ticker}/filings",),
     "about": "Two years of filings by month and form, the newest opening on EDGAR."},
    {"id": "ask", "title": "Ask the book", "group": "Free-form", "wide": False,
     "cost": "light", "private": False, "reads": ("/ask/status",),
     "about": "A question about the company or the book, answered from the book's reads."},
)
BY_ID = {panel["id"]: panel for panel in PANELS}

MAX_PANELS = 12          # a board past this is a page nobody reads to the end
MAX_LIVE = 4             # each live price is two Yahoo requests a minute while in session
COLUMNS = (1, 2, 3)      # "lay out N across", and how a board saved before the grid is read
DEFAULT_COLUMNS = 2
# What a reader sees before they have chosen anything.
DEFAULT_PANELS = ("price", "fundamentals", "ask")
ASK = "ask"              # the Ask box as a panel: one a board, and never named to the model

# A ticker as the book writes one: LLY, NOVO-B.CO, 4568.T. Anything else is not sent on.
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
PANEL_ID = re.compile(r"^p[0-9]{1,4}$")

# ---------------------------------------------------------------------------- the grid
# A board is a grid twelve columns wide, as deep as its panels need. A panel has a place
# (x, y: the column and row of its top left cell) and a size (w, h: columns and rows).
# The reader moves a panel by its heading and sizes it by a corner; the page sends the
# new place, and ``place`` settles the rest around it: a panel it lands on is pushed
# down, and every panel then rises as far as the one above it allows, so the board has
# no holes and no two panels overlap.
GRID_COLS = 12
ROW_PX = 24              # a row's height; the gap is added between rows
GAP_PX = 16              # between columns and between rows, the house's 16 px
MAX_H = 30               # rows; a panel taller than this is a page of its own
MAX_Y = 400              # rows; a place further down is a saved file gone wrong
HEAD_PX = 46             # a panel's rule and the gap under it, above its body
# The size a new panel opens at, and the smallest it can be made, in cells.
# The defaults fit one 1440 by 900 screen under the app's bar: 17 rows is 664 px.
SIZES = {"price": {"w": 12, "h": 11, "min_w": 4, "min_h": 8},
         "fundamentals": {"w": 12, "h": 6, "min_w": 4, "min_h": 4},
         "ask": {"w": 4, "h": 17, "min_w": 3, "min_h": 8}}
SIZE = {"w": 6, "h": 9, "min_w": 3, "min_h": 5}


def esc(text) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def clean_ticker(value):
    """The ticker in the book's form, or None where it is not one."""
    text = str(value or "").strip().upper()
    return text if TICKER.match(text) else None


def size_of(kind: str) -> dict:
    return SIZES.get(kind, SIZE)


def area_px(h: int) -> int:
    """How tall a panel of ``h`` rows is on the page."""
    return h * ROW_PX + (h - 1) * GAP_PX


def body_px(h: int) -> int:
    """How tall a panel's scrolling body is: its area less its rule."""
    return max(80, area_px(h) - HEAD_PX)


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _clamp(value, low, high):
    return max(low, min(high, value))


def _fit(entry: dict) -> dict:
    """A panel's size and place made to fit the grid and its kind's minimum."""
    size = size_of(entry["panel"])
    w = _clamp(_int(entry.get("w")) or size["w"], size["min_w"], GRID_COLS)
    h = _clamp(_int(entry.get("h")) or size["h"], size["min_h"], MAX_H)
    x = _clamp(_int(entry.get("x")) or 0, 0, GRID_COLS - w)
    y = _clamp(_int(entry.get("y")) or 0, 0, MAX_Y)
    return dict(entry, x=x, y=y, w=w, h=h)


def _overlap(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def reading_order(panels) -> list:
    """Top to bottom, then left to right: the order a reader meets the panels in, and the
    order the page lays them out in for a screen reader."""
    return sorted(panels or [], key=lambda p: (p["y"], p["x"]))


def settle(panels, first=None) -> list:
    """No two panels overlapping and no hole above any of them.

    ``first`` is the id of the panel the reader has just put somewhere: it keeps that
    place, and a panel in its way is pushed down below it. Then each panel, top first,
    rises as far as the panels already above it allow.
    """
    panels = [_fit(p) for p in panels or []]
    lead = [p for p in panels if p["id"] == first]
    rest = reading_order([p for p in panels if p["id"] != first])
    placed = []
    for p in lead + rest:
        while True:
            hit = [q for q in placed if _overlap(p, q)]
            if not hit:
                break
            p = dict(p, y=max(q["y"] + q["h"] for q in hit))
        placed.append(p)
    risen = []
    for p in reading_order(placed):
        y = p["y"]
        while y > 0 and not any(_overlap(dict(p, y=y - 1), q) for q in risen):
            y -= 1
        risen.append(dict(p, y=y))
    return reading_order(risen)


def _next_id(panels) -> str:
    used = [int(p["id"][1:]) for p in panels or [] if PANEL_ID.match(str(p.get("id") or ""))]
    return f"p{max(used, default=0) + 1}"


def item(panel: str, ticker=None, **place) -> dict:
    """One panel. ``ticker`` None follows the top bar; a place left out is filled in by
    ``normalise``."""
    entry = {"panel": panel, "ticker": ticker}
    entry.update({k: v for k, v in place.items() if k in ("id", "x", "y", "w", "h")})
    return entry


def packed(kinds, columns: int) -> list:
    """Panels laid out ``columns`` across in the order given, a wide kind on a row of its
    own. How a board is laid out afresh, and how one saved before the grid is read."""
    columns = columns if columns in COLUMNS else DEFAULT_COLUMNS
    span = GRID_COLS // columns
    out, x, y, row_h = [], 0, 0, 0
    for entry in kinds:
        size = size_of(entry["panel"])
        w = GRID_COLS if entry.get("wide") or size["w"] == GRID_COLS else span
        h = _int(entry.get("h")) or size["h"]
        if x + w > GRID_COLS:
            x, y, row_h = 0, y + row_h, 0
        out.append(dict({k: v for k, v in entry.items() if k != "wide"},
                        x=x, y=y, w=w, h=h))
        x, row_h = x + w, max(row_h, h)
    return out


def default_layout() -> dict:
    """The price and the fundamentals under it on the left two thirds, the Ask box down
    the right: the board as it was drawn when the box sat in a column of its own."""
    return {"panels": settle([
        item("price", id="p1", x=0, y=0, w=8, h=11),
        item("fundamentals", id="p2", x=0, y=11, w=8, h=6),
        item(ASK, id="p3", x=8, y=0, w=4, h=17)])}


def normalise(layout) -> tuple:
    """A layout made safe to draw, and what was left out of it, in words.

    A saved board outlives the code that saved it: a panel kind can be renamed or
    withdrawn, a file can be edited by hand. Nothing unknown is guessed at. It is dropped
    and the reader is told, so a board never draws a panel it cannot name. A board saved
    before panels had a place on the grid is laid out the way it was drawn then.
    """
    left_out = []
    if not isinstance(layout, dict):
        return default_layout(), ["the saved board could not be read, so the default is shown"]
    kept, live, ids = [], 0, set()
    for raw in layout.get("panels") or []:
        if (not isinstance(raw, dict) or not isinstance(raw.get("panel"), str)
                or raw["panel"] not in BY_ID):
            name = raw.get("panel") if isinstance(raw, dict) else raw
            left_out.append(f"a panel this version does not have: {str(name)[:40]}")
            continue
        kind = BY_ID[raw["panel"]]
        if kind["id"] == ASK and any(e["panel"] == ASK for e in kept):
            left_out.append(f"{kind['title']}: a board holds one")
            continue
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
        entry = item(kind["id"], ticker, **{k: raw[k] for k in ("x", "y", "w", "h")
                                            if _int(raw.get(k)) is not None})
        pid = raw.get("id")
        if isinstance(pid, str) and PANEL_ID.match(pid) and pid not in ids:
            entry["id"] = pid
            ids.add(pid)
        if isinstance(raw.get("wide"), bool):
            entry["wide"] = raw["wide"]
        kept.append(entry)
    for entry in kept:
        if "id" not in entry:
            entry["id"] = _next_id(kept)
    placed = [e for e in kept if all(k in e for k in ("x", "y", "w", "h"))]
    if not placed and kept:
        kept = packed(kept, layout.get("columns"))
    else:
        bottom = max((e["y"] + e["h"] for e in placed), default=0)
        loose = packed([e for e in kept if e not in placed], DEFAULT_COLUMNS)
        kept = placed + [dict(e, y=e["y"] + bottom) for e in loose]
    panels = settle([{k: v for k, v in e.items() if k != "wide"} for e in kept])
    return {"panels": panels}, left_out


def _find(panels, pid):
    return next((n for n, p in enumerate(panels) if p["id"] == pid), None)


def place(layout: dict, pid: str, x, y, w, h) -> dict:
    """The board with one panel put at a place and a size, the rest settled round it. A
    place off the grid or a size below the kind's minimum is brought to the nearest that
    fits; an id that is not on the board changes nothing."""
    panels = [dict(p) for p in (layout or {}).get("panels") or []]
    n = _find(panels, pid)
    if n is None or not all(_int(v) is not None for v in (x, y, w, h)):
        return dict(layout or {}, panels=panels)
    panels[n] = _fit(dict(panels[n], x=x, y=y, w=w, h=h))
    return dict(layout, panels=settle(panels, first=pid))


def first_free(panels, w: int, h: int) -> tuple:
    """The first place, reading from the top left, where a panel of ``w`` by ``h`` cells
    fits without covering another."""
    bottom = max((p["y"] + p["h"] for p in panels or []), default=0)
    for y in range(bottom + 1):
        for x in range(GRID_COLS - w + 1):
            spot = {"x": x, "y": y, "w": w, "h": h}
            if not any(_overlap(spot, p) for p in panels or []):
                return x, y
    return 0, bottom


def added(layout: dict, kind: str, ticker=None) -> tuple:
    """The board with one more panel in the first place it fits, and why not where it
    was refused: an unknown kind, a full board, a fifth live chart."""
    panels = list((layout or {}).get("panels") or [])
    size = size_of(kind)
    x, y = first_free(panels, size["w"], size["h"])
    entry = item(kind, ticker, id=_next_id(panels), x=x, y=y, w=size["w"], h=size["h"])
    return normalise(dict(layout or {}, panels=panels + [entry]))


def removed(layout: dict, pid: str) -> dict:
    panels = [p for p in (layout or {}).get("panels") or [] if p["id"] != pid]
    return dict(layout or {}, panels=settle(panels))


def moved(layout: dict, pid: str, step: int) -> dict:
    """The board with one panel a place earlier (-1) or later (+1) in reading order: it
    takes the place of the panel before it, or the panel after it takes its place. A move
    off either end is no move. The keyboard's way to do what a drag does."""
    order = reading_order((layout or {}).get("panels") or [])
    n = _find(order, pid)
    if n is None or not 0 <= n + step < len(order):
        return dict(layout or {}, panels=order)
    mover, into = (order[n], order[n - 1]) if step < 0 else (order[n + 1], order[n])
    return place(dict(layout, panels=order), mover["id"], into["x"], into["y"],
                 mover["w"], mover["h"])


def changed(layout: dict, pid: str, ticker=None) -> dict:
    """The board with one panel's company set. A company that is not a ticker is no pin:
    the panel follows the top bar."""
    panels = [dict(p) for p in (layout or {}).get("panels") or []]
    n = _find(panels, pid)
    if n is not None:
        panels[n]["ticker"] = clean_ticker(ticker)
    return dict(layout or {}, panels=panels)


def laid_out(layout: dict, columns: int) -> dict:
    """The board laid out afresh ``columns`` across, in the order it is read now, each
    panel at its kind's own height."""
    order = [item(p["panel"], p.get("ticker"), id=p["id"])
             for p in reading_order((layout or {}).get("panels") or [])]
    return dict(layout or {}, panels=settle(packed(order, columns)))


def grid_css(panels) -> str:
    """Where each panel sits on the grid, as a stylesheet. The grid itself is in
    theme.py; this places each panel's box (Streamlit's wrapper round the panel's keyed
    container) by its id, so the page draws the board where the reader left it before
    any script has run."""
    rules = []
    for p in panels or []:
        if not PANEL_ID.match(str(p.get("id") or "")):
            continue
        rules.append(
            f'.st-key-td_grid > [data-testid="stLayoutWrapper"]:has(> .st-key-td_p_{p["id"]})'
            f'{{grid-column:{p["x"] + 1} / span {p["w"]};grid-row:{p["y"] + 1} / span {p["h"]};}}')
    return '<div class="td-gridcss"><style>' + "".join(rules) + "</style></div>"


def grid_spec(panels) -> list:
    """What the drag and resize frame needs of each panel: its id, place, size and the
    smallest it can be made."""
    return [{"id": p["id"], "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
             "min_w": size_of(p["panel"])["min_w"], "min_h": size_of(p["panel"])["min_h"],
             "title": BY_ID[p["panel"]]["title"]}
            for p in panels or []]


def company_of(entry: dict, ticker: str) -> str:
    """The company a panel is drawn for: its own where pinned, else the top bar's."""
    return entry.get("ticker") or ticker


def heading(entry: dict, ticker: str) -> tuple:
    """The panel's section rule: what it is, and whose. The company rides in the basis
    tag, and a pinned one says so, since it will not follow the top bar."""
    kind = BY_ID[entry["panel"]]
    whose = company_of(entry, ticker)
    return kind["title"], (f"{whose} · pinned" if entry.get("ticker") else whose)


def showing(panels, ticker: str) -> list:
    """What is on screen, as the Ask box may be told it: the kind of each panel and its
    company, in reading order, and nothing a panel shows. A private panel is left out,
    because naming it beside a ticker would say the reader holds that stock."""
    out, seen = [], set()
    for entry in reading_order(panels) if all("y" in p for p in panels or []) else panels or []:
        kind = BY_ID.get(entry.get("panel")) if isinstance(entry, dict) else None
        if not kind or kind["private"] or kind["id"] == ASK:
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


# ------------------------------------------------------------------------------ markup
# Where a news row came from, as the reader should hear it. The pulse is a summary
# written by a model and is labelled as one wherever it is shown (CLAUDE.md); a source
# not listed here prints under its own stored name, never under a guess.
NEWS_SOURCES = {
    "press_ir": "Company release",
    "press_page": "Company release",
    "edgar_8k": "8-K",
    "fda_press": "FDA press release",
    "fda_drugs": "FDA drugs feed",
    "fda_safety": "FDA safety notice",
    "pulse": "Daily pulse (AI summary)",
}
NEWS_SHOWN = 40


def _link(url) -> str:
    """The address where it is a web address, else nothing: a row links only to http."""
    text = str(url or "").strip()
    return text if re.match(r"^https?://", text, re.I) else ""


def _row(date, title, tag, url="", why="", hover="") -> str:
    """One line of a list, in the feed's own four columns (theme.py, .fitem): when, what,
    a qualifier, and a tag. A row with a source opens it."""
    link = _link(url)
    tip = f' title="{esc(hover)}"' if hover else ""
    open_tag = (f'<a class="fitem link" href="{esc(link)}" target="_blank" '
                f'rel="noopener noreferrer"{tip}>' if link else f'<div class="fitem"{tip}>')
    return (f'{open_tag}<span class="d">{esc(date)}</span><span class="t">{esc(title)}</span>'
            f'<span class="why">{esc(why)}</span><span class="s">{esc(tag)}</span>'
            f'{"</a>" if link else "</div>"}')


def news_rows(payload) -> list:
    """The company's news as the API holds it, newest first, each with a title."""
    rows = [r for r in ((payload or {}).get("news") or [])
            if isinstance(r, dict) and str(r.get("title") or "").strip()]
    return sorted(rows, key=lambda r: str(r.get("published_at") or ""), reverse=True)


def news_basis(rows) -> str:
    """"40 of 57, newest first": how much of the list is on the panel."""
    total = len(rows)
    if not total:
        return ""
    return f"{min(NEWS_SHOWN, total)} of {total}, newest first"


def news_html(rows) -> str:
    """The news list. Empty where there is none, so the caller can say so in words."""
    if not rows:
        return ""
    lines = []
    for r in rows[:NEWS_SHOWN]:
        source = str(r.get("source") or "")
        lines.append(_row(str(r.get("published_at") or "")[:10],
                          re.sub(r"\s+", " ", str(r["title"])).strip(),
                          NEWS_SOURCES.get(source, source or "source not stated"),
                          url=r.get("url")))
    return '<div class="feed td-list">' + "".join(lines) + "</div>"


def left_out_html(left_out) -> str:
    """What a saved board asked for and did not get, said once above the panels."""
    if not left_out:
        return ""
    return ('<div class="byline td-left-out">Left off the board: '
            + "; ".join(esc(reason) for reason in left_out) + ".</div>")


# ----------------------------------------------------------------------------- figures
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
LEADS = 3                    # the items named under a figure


_MONTH_DATE = re.compile(r"^(\d{4})-(\d{2})$")


def _day(value):
    """A date from what the API sent, or None. A date given as a month ("2026-12", how
    the calendar stores a readout the registry dates to a month) is placed at the first
    of it, which is only ever used to find its month: it is never printed as a day."""
    text = str(value or "").strip()
    month = _MONTH_DATE.match(text)
    try:
        if month:
            return dt.date(int(month.group(1)), int(month.group(2)), 1)
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        return None


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def month_start(day: dt.date, offset: int = 0) -> dt.date:
    """The first of the month ``offset`` months from ``day``'s."""
    index = day.year * 12 + day.month - 1 + offset
    return dt.date(index // 12, index % 12 + 1, 1)


BOARD_PX = 1408                 # the page's width at 1440 px, the width the app is sized for


def figure_width(w: int) -> int:
    """About how wide a panel ``w`` columns wide is in pixels, so a figure is drawn at the
    size it is shown and its type is not scaled to a blur."""
    w = _clamp(_int(w) or SIZE["w"], 1, GRID_COLS)
    return int(max(220, (BOARD_PX + GAP_PX) * w / GRID_COLS - GAP_PX - 8))


def fold_html(summary: str, inner: str) -> str:
    """The full list, one click away under the figure."""
    if not inner:
        return ""
    return (f'<details class="note-d td-all"><summary>{esc(summary)}</summary>{inner}'
            "</details>")


def leads_html(items) -> str:
    """The few items that matter, named: a tag for the kind, the date, the headline. Each
    {tone, tag, date, text, url?, hover?}; a lead with a source opens it."""
    if not items:
        return ""
    out = []
    for it in items:
        link = _link(it.get("url"))
        tip = f' title="{esc(it["hover"])}"' if it.get("hover") else ""
        tone = re.sub(r"[^a-z0-9_]", "", str(it.get("tone") or "plain"))
        open_tag = (f'<a class="td-lead td-{tone}" href="{esc(link)}" target="_blank" '
                    f'rel="noopener noreferrer"{tip}>' if link
                    else f'<div class="td-lead td-{tone}"{tip}>')
        out.append(f'{open_tag}<span class="k">{esc(it.get("tag"))}</span>'
                   f'<span class="d">{esc(it.get("date"))}</span>'
                   f'<span class="t">{esc(it.get("text"))}</span>'
                   f'{"</a>" if link else "</div>"}')
    return '<div class="td-leads">' + "".join(out) + "</div>"


# --- company news: how much, from whom, and the newest ---------------------------------
NEWS_MONTHS = 12
NEWS_LANES = (
    {"key": "company", "label": "Company", "colour": TK.TEXT},
    {"key": "filing", "label": "8-K", "colour": TK.MUTED},
    {"key": "fda", "label": "FDA", "colour": TK.FDA},
    # Amber is "uncurated, look at this": a model's summary of the trade press is that.
    {"key": "pulse", "label": "Pulse (AI)", "colour": TK.FLAG},
    {"key": "other", "label": "Other", "colour": TK.RULE_STRONG},
)
_NEWS_LANE = {"press_ir": "company", "press_page": "company", "edgar_8k": "filing",
              "fda_press": "fda", "fda_drugs": "fda", "fda_safety": "fda", "pulse": "pulse"}
_ALWAYS_NEWS = ("company", "filing")


def news_lane(row: dict) -> str:
    return _NEWS_LANE.get(str(row.get("source") or ""), "other")


def news_figure(rows, today: dt.date, width: int) -> str:
    """A year of the company's news on a grid of months and sources."""
    items = [{"date": r.get("published_at"), "lane": news_lane(r),
              "tip": f'{str(r.get("published_at") or "")[:10]} · '
                     f'{NEWS_SOURCES.get(str(r.get("source") or ""), r.get("source") or "")}'
                     f' · {_one_line(r.get("title"))}'}
             for r in rows or []]
    used = {it["lane"] for it in items}
    lanes = [lane for lane in NEWS_LANES
             if lane["key"] in used or lane["key"] in _ALWAYS_NEWS]
    return CH.unit_lanes(items, lanes, month_start(today, 1 - NEWS_MONTHS), today,
                         step="month", width=width, cap=6,
                         label="company news by month and source")


def news_leads(rows) -> str:
    """The newest three, named, each opening its source."""
    return leads_html([
        {"tone": news_lane(r), "date": str(r.get("published_at") or "")[:10],
         "tag": NEWS_SOURCES.get(str(r.get("source") or ""),
                                 r.get("source") or "source not stated"),
         "text": _one_line(r.get("title")), "url": r.get("url")}
        for r in (rows or [])[:LEADS]])


def news_older(rows, today: dt.date) -> int:
    """How many rows are older than the figure reaches, so it can be said."""
    start = month_start(today, 1 - NEWS_MONTHS)
    return sum(1 for r in rows or []
               if (_day(r.get("published_at")) or start) < start)


# --- price: the window on screen and the figures that describe it -----------------------
PRICE_SPANS = (("1M", 31), ("3M", 92), ("6M", 183), ("1Y", 365), ("5Y", 1826))
DEFAULT_SPAN = "6M"
SPAN_DAYS = dict(PRICE_SPANS)
# A candle a day up to six months, a week for a year and a month for five: about 25 to
# 130 candles whatever the window, so a candle is always wide enough to read its body.
BAR_OF = {"1M": "day", "3M": "day", "6M": "day", "1Y": "week", "5Y": "month"}
BAR_WORDS = {"day": "daily", "week": "weekly", "month": "monthly"}


def candles(bars, step: str) -> list:
    """Daily bars as candles of a day, a week or a month: the first open, the highest
    high, the lowest low, the last close and the volume added up. A candle is dated by its
    first session. A bar with no close is left out; a candle missing an open, a high or a
    low takes none rather than one made up."""
    if step == "day":
        return [b for b in bars or [] if b.get("close") is not None]
    out, key = [], None
    for b in bars or []:
        d = _day(b.get("as_of"))
        if d is None or b.get("close") is None:
            continue
        k = d.isocalendar()[:2] if step == "week" else (d.year, d.month)
        if k != key:
            key = k
            out.append({"as_of": str(b["as_of"])[:10], "open": b.get("open"),
                        "high": b.get("high"), "low": b.get("low"), "close": b["close"],
                        "volume": b.get("volume")})
            continue
        c = out[-1]
        c["close"] = b["close"]
        c["high"] = (None if c["high"] is None or b.get("high") is None
                     else max(c["high"], b["high"]))
        c["low"] = (None if c["low"] is None or b.get("low") is None
                    else min(c["low"], b["low"]))
        c["volume"] = ((c["volume"] or 0) + (b.get("volume") or 0)
                       if c["volume"] is not None or b.get("volume") is not None else None)
    return out


def price_window(points, span: str) -> list:
    """The bars inside the window, counted back from the newest bar and not from today:
    a book last refreshed on Friday still shows a full month on Monday."""
    bars = [p for p in points or [] if isinstance(p, dict) and _day(p.get("as_of"))]
    if not bars:
        return []
    bars.sort(key=lambda p: str(p["as_of"]))
    since = _day(bars[-1]["as_of"]) - dt.timedelta(days=SPAN_DAYS.get(span, 365))
    return [p for p in bars if _day(p["as_of"]) >= since]


def price_stats(bars) -> dict:
    """The window in four figures. Each is None where the bars do not give it: a change
    needs a first close above nought, a range needs a high and a low or the closes."""
    closes = [p["close"] for p in bars or [] if p.get("close") is not None]
    if not closes:
        return {"last": None, "as_of": None, "change": None, "low": None, "high": None,
                "bars": 0}
    lows = [p["low"] for p in bars if p.get("low") is not None] or closes
    highs = [p["high"] for p in bars if p.get("high") is not None] or closes
    first, last = closes[0], closes[-1]
    return {"last": last, "as_of": str(bars[-1].get("as_of") or "")[:10],
            "change": (last - first) / first * 100 if first else None,
            "low": min(lows), "high": max(highs), "bars": len(closes)}


def _money(value) -> str:
    return NO_DATA if value is None else f"{value:,.2f}"


def price_stats_html(stats: dict, span: str) -> str:
    """The strip beside the window's control: the last close, the window's change and its
    range. The change carries its sign and a true minus; a fall takes the down colour and
    the sign says the same."""
    change = stats.get("change")
    if change is None:
        moved, tone = NO_DATA, " none"
    else:
        moved = f'{"+" if change >= 0 else chr(0x2212)}{abs(change):.1f}%'
        tone = " risk" if change < 0 else ""
    missing = " none" if stats.get("last") is None else ""
    span_range = (f'{_money(stats.get("low"))} to {_money(stats.get("high"))}'
                  if stats.get("low") is not None else NO_DATA)
    cells = (("last", _money(stats.get("last")), missing),
             (f"{span} change", moved, tone),
             (f"{span} range", span_range, missing))
    return ('<div class="stats stats-tight td-stats">' + "".join(
        f'<span class="stat"><span class="k">{esc(k)}</span>'
        f'<span class="v{cls}">{esc(v)}</span></span>' for k, v, cls in cells) + "</div>")


def price_events(approvals) -> list:
    """Approvals and loss-of-exclusivity dates as the chart's markers want them. A row
    with no name or no date is not an event."""
    events = []
    for row in approvals or []:
        name = row.get("brand_name") or row.get("generic_name")
        if not name:
            continue
        if row.get("approval_date"):
            events.append({"date": row["approval_date"], "label": name, "kind": "approval"})
        if row.get("loe"):
            events.append({"date": row["loe"], "label": f"{name} LOE", "kind": "loe"})
    return events


# --- filings: what was filed, when, and the newest ---------------------------------------
FILING_MONTHS = 24
FILINGS_SHOWN = 40
# A filing's row is the kind of report it is. Annual and quarterly are the scheduled
# ones and take the text colour, the annual one filled and the quarterly an outline; a
# current report (8-K, 6-K) is an event and takes Slate. The row's label says which.
FILING_LANES = (
    {"key": "annual", "label": "Annual", "colour": TK.TEXT},
    {"key": "quarterly", "label": "Quarterly", "colour": TK.TEXT},
    {"key": "current", "label": "Current", "colour": TK.MUTED},
    {"key": "other", "label": "Other", "colour": TK.MUTED},
)
_FILING_LANE = {"10-K": "annual", "20-F": "annual", "40-F": "annual", "10-Q": "quarterly",
                "8-K": "current", "6-K": "current"}
# What a form is, for a filing whose title on file is only the form's own name.
_FILING_WORDS = {"annual": "Annual report", "quarterly": "Quarterly report",
                 "current": "Current report", "other": "Filing"}
_ALWAYS_FILED = ("annual", "quarterly", "current")
_HOLLOW_FILED = ("quarterly", "other")


def filing_lane(row: dict) -> str:
    """The row a form sits in. An amended form ("10-K/A") sits with the form it amends."""
    form = str(row.get("form_type") or "").upper().split("/")[0].strip()
    return _FILING_LANE.get(form, "other")


def filings_rows(payload) -> list:
    """The company's filings as the API holds them, newest first, each with a form."""
    rows = [r for r in ((payload or {}).get("filings") or [])
            if isinstance(r, dict) and str(r.get("form_type") or "").strip()]
    return sorted(rows, key=lambda r: str(r.get("filed_date") or ""), reverse=True)


def filings_figure(rows, today: dt.date, width: int) -> str:
    """Two years of filings on a grid of months and forms."""
    items = [{"date": r.get("filed_date"), "lane": filing_lane(r),
              "hollow": filing_lane(r) in _HOLLOW_FILED,
              "tip": f'{str(r.get("filed_date") or "")[:10]} · {_one_line(r.get("form_type"))}'
                     + (f' · {_one_line(r.get("title"))}'
                        if _one_line(r.get("title")) not in ("", _one_line(r.get("form_type")))
                        else "")}
             for r in rows or []]
    used = {it["lane"] for it in items}
    lanes = [lane for lane in FILING_LANES
             if lane["key"] in used or lane["key"] in _ALWAYS_FILED]
    return CH.unit_lanes(items, lanes, month_start(today, 1 - FILING_MONTHS), today,
                         step="month", width=width, cap=5,
                         label="filings by month and form")


def filings_leads(rows) -> str:
    """The newest three, each opening the filing on EDGAR where the address is on file."""
    out = []
    for r in (rows or [])[:LEADS]:
        form, title = _one_line(r.get("form_type")), _one_line(r.get("title"))
        out.append({"tone": "company" if filing_lane(r) in ("annual", "quarterly")
                    else "filing",
                    "tag": form, "date": str(r.get("filed_date") or "")[:10],
                    "text": title if title and title != form
                    else _FILING_WORDS[filing_lane(r)], "url": r.get("url")})
    return leads_html(out)


def filings_html(rows) -> str:
    if not rows:
        return ""
    lines = [_row(str(r.get("filed_date") or "")[:10],
                  _one_line(r.get("title")) or _one_line(r.get("form_type")),
                  _one_line(r.get("form_type")), url=r.get("url"))
             for r in rows[:FILINGS_SHOWN]]
    return '<div class="feed td-list">' + "".join(lines) + "</div>"


def filings_basis(rows) -> str:
    total = len(rows or [])
    return f"{min(FILINGS_SHOWN, total)} of {total}, newest first" if total else ""


def filings_older(rows, today: dt.date) -> int:
    start = month_start(today, 1 - FILING_MONTHS)
    return sum(1 for r in rows or [] if (_day(r.get("filed_date")) or start) < start)


# --- fundamentals: the figures a price is set on ---------------------------------------
def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value == value else None


def money(value) -> str:
    """A sum in its reporting currency's units: 24.4bn, 612m. Nothing is a dash."""
    value = _num(value)
    if value is None:
        return NO_DATA
    sign, value = ("\u2212" if value < 0 else ""), abs(value)
    if value >= 1e9:
        return f"{sign}{value / 1e9:,.1f}bn"
    if value >= 1e6:
        return f"{sign}{value / 1e6:,.0f}m"
    return f"{sign}{value:,.0f}"


def pct(value, digits: int = 1, signed: bool = True) -> str:
    """A fraction as a percentage with a true minus: 0.386 is +38.6%."""
    value = _num(value)
    if value is None:
        return NO_DATA
    sign = ("+" if value >= 0 else "\u2212") if signed else ("\u2212" if value < 0 else "")
    return f"{sign}{abs(value) * 100:.{digits}f}%"


def _tone(value):
    value = _num(value)
    return None if value is None or value == 0 else ("up" if value > 0 else "down")


def tile(k: str, v: str, d: str = "", tone=None, n: str = "", tip: str = "") -> dict:
    return {"k": k, "v": v, "d": d, "tone": tone, "n": n, "tip": tip}


def _street_rows(street) -> dict:
    """The street read's rows by (metric, period)."""
    out = {}
    for r in (street or {}).get("rows") or []:
        if isinstance(r, dict):
            out[(r.get("metric"), str(r.get("period") or ""))] = r
    return out


def _street_value(row):
    s = (row or {}).get("street") if isinstance((row or {}).get("street"), dict) else None
    return _num((s or {}).get("value")), s or {}


def forward_eps(street, today: dt.date) -> list:
    """The street's EPS by fiscal year from this one on: [(year, value, note)]."""
    out = []
    for (metric, period), row in _street_rows(street).items():
        year = re.match(r"^FY(\d{4})$", period)
        if metric != "EPS" or not year or int(year.group(1)) < today.year:
            continue
        value, s = _street_value(row)
        if value is not None:
            out.append((int(year.group(1)), value, str(s.get("note") or "")))
    return sorted(out)


def fundamentals(today: dt.date, report=None, street=None, cash=None, runway=None,
                 screen=None, relative=None, close=None, price_currency=None) -> list:
    """The board's fundamentals as groups of tiles: [(group, [tile])]. Every figure is a
    read's own or a ratio of two of them, said as such; a figure no read gives is left out
    of an optional tile and printed as "no free data" in a core one."""
    groups = []
    rep = (report or {}).get("report") and report or {}
    filed = rep.get("filed") or {}
    beat = rep.get("street") or {}
    screen = screen or {}

    # Growth: the last reported quarter, or the last year where no report is on file.
    if filed:
        label = rep["report"].get("label") or filed.get("label") or "last period"
        g = [tile(f"Revenue, {label}", money(filed.get("revenue")),
                  f"{pct(filed.get('revenue_growth'))} on a year"
                  if _num(filed.get("revenue_growth")) is not None else "",
                  _tone(filed.get("revenue_growth"))),
             tile("Net margin", pct(filed.get("net_margin"), signed=False),
                  f"net income {pct(filed.get('net_income_growth'))} on a year"
                  if _num(filed.get("net_income_growth")) is not None else "",
                  _tone(filed.get("net_income_growth")))]
        if _num(beat.get("eps")) is not None:
            g.append(tile("EPS against street", f"{beat['eps']:,.2f}",
                          f"{pct((beat.get('surprise_pct') or 0) / 100)} on "
                          f"{beat.get('consensus_eps'):,.2f}"
                          if _num(beat.get("consensus_eps")) is not None
                          and _num(beat.get("surprise_pct")) is not None else "",
                          {"beat": "up", "miss": "down"}.get(beat.get("result")),
                          n=str(beat.get("result") or "")))
        day = rep.get("day") or {}
        if _num(day.get("move")) is not None:
            g.append(tile("Day of results", pct(day["move"]),
                          f"{pct(day.get('abnormal'))} on {day.get('benchmark')}"
                          if _num(day.get("abnormal")) is not None else "",
                          _tone(day["move"]), n=str(day.get("session") or "")))
    else:
        g = [tile("Revenue, last year", money(screen.get("revenue")),
                  f"{pct(screen.get('revenue_growth'))} on a year"
                  if _num(screen.get("revenue_growth")) is not None else "",
                  _tone(screen.get("revenue_growth"))),
             tile("Net margin, last year", pct(screen.get("net_margin"), signed=False))]
    groups.append(("Growth", g))

    # Outlook: what the company says, what the street expects, where the street prices it.
    o = []
    for guide in rep.get("guidance") or []:
        if guide.get("metric") == "Revenue" and _num(guide.get("value")) is not None:
            o.append(tile(f"Guidance, {guide.get('label') or 'revenue'}", money(guide["value"]),
                          f"{guide.get('direction') or 'set'} "
                          f"{pct(guide.get('change'))}" if _num(guide.get("change")) is not None
                          else str(guide.get("direction") or ""),
                          _tone(guide.get("change")), n=f"as of {guide.get('as_of')}"))
            break
    eps = forward_eps(street, today)
    if eps:
        year, value, note = eps[0]
        after = eps[1] if len(eps) > 1 else None
        grows = (after[1] / value - 1) if after and value > 0 else None
        o.append(tile(f"Street EPS FY{year}", f"{value:,.2f}",
                      f"{pct(grows)} in FY{after[0]}" if grows is not None else "",
                      _tone(grows), n=note.split(",")[0]))
    target_row = _street_rows(street).get(("PriceTarget", "12M"))
    target, ts = _street_value(target_row)
    if target is not None:
        up = (target / close - 1) if _num(close) and ts.get("currency") in (None, price_currency) \
            else None
        o.append(tile("Street target", f"{target:,.2f}",
                      f"{pct(up)} on the close" if up is not None else "", _tone(up),
                      n=str(ts.get("note") or "").split(";")[0]))
    if o:
        groups.append(("Outlook", o))

    # Valuation and the balance sheet.
    vb = []
    if eps and _num(close) and eps[0][1] > 0 and price_currency in (None, "USD"):
        vb.append(tile("Price over street EPS", f"{close / eps[0][1]:.1f}\u00d7",
                       n=f"on FY{eps[0][0]}"))
    cash = cash or {}
    if _num(cash.get("fcf")) is not None:
        vb.append(tile(f"Free cash flow FY{cash.get('fiscal_year')}", money(cash["fcf"]),
                       f"{pct(cash.get('fcf_margin'), signed=False)} of revenue"
                       if _num(cash.get("fcf_margin")) is not None else "",
                       _tone(cash["fcf"]) if cash["fcf"] < 0 else None))
    if _num(cash.get("net_debt_ebitda")) is not None:
        vb.append(tile("Net debt to EBITDA", f"{cash['net_debt_ebitda']:.1f}\u00d7",
                       n=f"net debt {money(cash.get('net_debt'))}"))
    run = runway or {}
    if _num(run.get("runway_months")) is not None:
        vb.append(tile("Cash runway", f"{run['runway_months']:.1f} months",
                       n=f"{money(run.get('available'))} at {run.get('cash_as_of')}",
                       tone="down" if run["runway_months"] < 12 else None))
    if _num(screen.get("loe_share_5y")) is not None:
        vb.append(tile("Revenue at LOE, 5 years", pct(screen["loe_share_5y"], signed=False),
                       n="loses exclusivity by then", tone="down" if screen["loe_share_5y"] >= 0.25
                       else None))
    if vb:
        groups.append(("Valuation and balance sheet", vb))

    # The price against the sector.
    windows = (relative or {}).get("windows") or {}
    rel = [tile(f"Against {relative.get('benchmark')}, {label}",
                f"{'+' if w['relative_pct'] >= 0 else chr(0x2212)}"
                f"{abs(w['relative_pct']) * 100:.1f} pts",
                f"{pct(w.get('company_pct'))} on {pct(w.get('benchmark_pct'))}",
                _tone(w["relative_pct"]))
           for key, label in (("3m", "3m"), ("1y", "1y"))
           for w in [windows.get(key) or {}]
           if _num(w.get("relative_pct")) is not None and w.get("covers_window")]
    if rel:
        groups.append(("The price", rel))
    return groups


def tiles_html(groups) -> str:
    """The tiles in one grid, in the groups' order (growth, the outlook, valuation and the
    balance sheet, the price), which is also the order they are read in: the figure first
    and large, the change beside it in its colour with its sign, a note under it. A grid
    of their own each, the groups were twice as tall for the same figures."""
    cells = []
    for _group, tiles in groups or []:
        for t in tiles or []:
            none = " none" if t["v"] == NO_DATA else ""
            tone = f' {t["tone"]}' if t.get("tone") in ("up", "down") else ""
            tip = f' title="{esc(t["tip"] or t["k"])}"' if t.get("tip") else f' title="{esc(t["k"])}"'
            cells.append(f'<div{tip}><span class="k">{esc(t["k"])}</span>'
                         f'<div class="row"><span class="v{none}">{esc(t["v"])}</span>'
                         + (f'<span class="d{tone}">{esc(t["d"])}</span>' if t.get("d") else "")
                         + "</div>"
                         + (f'<span class="n">{esc(t["n"])}</span>' if t.get("n") else "")
                         + "</div>")
    return f'<div class="tiles td-ftiles">{"".join(cells)}</div>' if cells else ""


# --- the Ask box ------------------------------------------------------------------------
def ask_empty_html(company: str) -> str:
    """What the box opens on: no suggested questions, one line on what it is for."""
    return ('<div class="td-ask-empty"><div class="t">Ask about '
            f'{esc(company)}, or anything in the book.</div><div class="d">Every figure '
            "in an answer is read from the book, and the reads are listed under it."
            "</div></div>")


def ask_question_html(question) -> str:
    return f'<div class="td-ask-q">{esc(_one_line(question))}</div>'


def ask_failed_html(reason) -> str:
    return ('<div class="td-ask-fail">No answer: '
            f'{esc(_one_line(reason) or "the model returned nothing")}</div>')
