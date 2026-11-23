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
    {"id": "changes", "title": "What changed", "group": "News", "wide": False,
     "cost": "free", "private": False, "reads": ("/changes?ticker={ticker}",),
     "about": "What the book detected changing in the last 30 days, by day and rating."},
    {"id": "news", "title": "Company news", "group": "News", "wide": False,
     "cost": "light", "private": False, "reads": ("/companies/{ticker}/news",),
     "about": "Releases, 8-K headlines and the daily pulse's items, by month and source."},
    {"id": "catalysts", "title": "Dated ahead", "group": "Catalysts", "wide": False,
     "cost": "light", "private": False,
     "reads": ("/catalysts?within_days={days}&ticker={ticker}",),
     "about": "Every dated catalyst in the next 24 months, by month and phase."},
)
BY_ID = {panel["id"]: panel for panel in PANELS}

MAX_PANELS = 12          # a board past this is a page nobody reads to the end
MAX_LIVE = 4             # each live price is two Yahoo requests a minute while in session
COLUMNS = (1, 2, 3)
DEFAULT_COLUMNS = 2
# What a reader sees before they have chosen anything.
DEFAULT_PANELS = ("price", "changes", "news", "catalysts")

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
        if (not isinstance(raw, dict) or not isinstance(raw.get("panel"), str)
                or raw["panel"] not in BY_ID):
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


def heading(entry: dict, ticker: str) -> tuple:
    """The panel's section rule: what it is, and whose. The company rides in the basis
    tag, and a pinned one says so, since it will not follow the top bar."""
    kind = BY_ID[entry["panel"]]
    whose = company_of(entry, ticker)
    return kind["title"], (f"{whose} · pinned" if entry.get("ticker") else whose)


def showing(panels, ticker: str) -> list:
    """What is on screen, as the Ask box may be told it: the kind of each panel and its
    company, and nothing a panel shows. A private panel is left out, because naming it
    beside a ticker would say the reader holds that stock."""
    out, seen = [], set()
    for entry in panels or []:
        kind = BY_ID.get(entry.get("panel")) if isinstance(entry, dict) else None
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
DATED_SHOWN = 60


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


def dated_rows(catalysts) -> list:
    """The dated events ahead, soonest first. A row with no date is not a dated event."""
    rows = [c for c in (catalysts or []) if isinstance(c, dict) and c.get("expected_date")]
    return sorted(rows, key=lambda c: str(c["expected_date"]))


def dated_html(rows) -> str:
    """What is dated ahead, one line an event: the date, the event, how exactly it is
    dated, and what kind it is. A month the registry gives with no day is shown as the
    month and marked, never as the first of it."""
    if not rows:
        return ""
    lines = []
    for c in rows[:DATED_SHOWN]:
        when = str(c.get("expected_date") or "")
        month_only = _month_only(c)
        title = re.sub(r"\s+", " ", str(c.get("title") or "")).strip()
        lines.append(_row(when[:7] if month_only else when[:10],
                          title or "untitled in the source",
                          c.get("catalyst_type") or "kind not stated",
                          url=c.get("source_url"),
                          why="month only" if month_only else "",
                          hover=title))
    return '<div class="feed td-list">' + "".join(lines) + "</div>"


def dated_basis(rows, months: int) -> str:
    total = len(rows)
    if not total:
        return ""
    shown = min(DATED_SHOWN, total)
    return (f"{total} in {months} months" if shown == total
            else f"{shown} of {total} in {months} months")


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


def figure_width(columns: int, beside: bool) -> int:
    """About how wide a panel is in pixels on the 1440 px page the app is sized for, so
    a figure is drawn at the size it is shown and its type is not scaled to a blur."""
    board = 1408 * (2.05 / 3.05 if beside else 1.0) - (16 if beside else 0)
    columns = columns if columns in COLUMNS else DEFAULT_COLUMNS
    return int(max(260, min(1380, (board - 16 * (columns - 1)) / columns - 8)))


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


# --- dated ahead: when, and at what phase ----------------------------------------------
# The phase a readout is at, read from the start of its registry title ("Phase 3, a study
# of ..."), which is where the calendar's derivation writes it. A seamless phase sits at
# the phase it reaches, as everywhere in the app. A regulatory date is a decision.
_PHASE = re.compile(r"^\s*Phase\s+(1/2|2/3|1|2|3)\b", re.I)
_PHASE_LANE = {"1": "p1", "1/2": "p2", "2": "p2", "2/3": "p3", "3": "p3"}
_DECISION = ("pdufa", "fda", "decision", "adcomm", "advisory", "regulatory", "approval")
DATED_LANES = (
    {"key": "p3", "label": "Phase 3", "colour": TK.PHASE_RAMP["Phase 3"]},
    {"key": "p2", "label": "Phase 2", "colour": TK.PHASE_RAMP["Phase 2"]},
    {"key": "p1", "label": "Phase 1", "colour": TK.PHASE_RAMP["Phase 1"]},
    {"key": "decision", "label": "Decision", "colour": TK.PHASE_RAMP["filed"]},
    {"key": "other", "label": "Other", "colour": TK.MUTED},
)
_ALWAYS_DATED = ("p3", "p2", "p1")       # an empty Phase 3 lane is a finding
_LANE_RANK = {lane["key"]: n for n, lane in enumerate(DATED_LANES)}


def dated_lane(row: dict) -> str:
    kind = str(row.get("catalyst_type") or "").lower()
    if any(word in kind for word in _DECISION):
        return "decision"
    found = _PHASE.match(str(row.get("title") or ""))
    return _PHASE_LANE[found.group(1)] if found else "other"


def _month_only(row: dict) -> bool:
    """Whether the source dates this to a month and no day: it says so, or the date it
    gives has no day in it."""
    return ((row.get("date_confidence") or "") == "month"
            or bool(_MONTH_DATE.match(str(row.get("expected_date") or "").strip())))


def dated_when(row: dict) -> str:
    """The date as far as the source gives it: "15 Dec 2026", or "Dec 2026" where the
    registry gives a month and no day."""
    d = _day(row.get("expected_date"))
    if d is None:
        return NO_DATA
    month = f"{MONTHS[d.month - 1]} {d.year}"
    return month if _month_only(row) else f"{d.day} {month}"


def dated_wait(row: dict, today: dt.date) -> str:
    """How far off, in the unit the date is given in. A month with no day is counted in
    months: a count of days to the first of it would be a day nobody published."""
    d = _day(row.get("expected_date"))
    if d is None:
        return ""
    if _month_only(row):
        months = (d.year - today.year) * 12 + d.month - today.month
        return ("this month" if months <= 0 else "next month" if months == 1
                else f"in {months} months")
    days = (d - today).days
    return "today" if days <= 0 else "tomorrow" if days == 1 else f"in {days} days"


def dated_figure(rows, today: dt.date, months: int, width: int) -> str:
    """What is dated ahead on a grid of months and phases, a square an event."""
    items = [{"date": _day(r.get("expected_date")), "lane": dated_lane(r),
              "tip": " · ".join(part for part in (
                  dated_when(r), _one_line(r.get("catalyst_type")),
                  _one_line(r.get("title"))) if part)}
             for r in rows or []]
    used = {it["lane"] for it in items}
    lanes = [lane for lane in DATED_LANES
             if lane["key"] in used or lane["key"] in _ALWAYS_DATED]
    return CH.unit_lanes(items, lanes, month_start(today), month_start(today, months - 1),
                         step="month", width=width, cap=5,
                         label="dated events ahead by month and phase")


def dated_next(rows, today: dt.date) -> str:
    """The nearest events, named: how far off, the date, and what it is. Within one
    period the later phase leads, since that is the one a reader came for."""
    ahead = sorted(rows or [], key=lambda r: (str(r.get("expected_date") or "")[:7]
                                              if _month_only(r)
                                              else str(r.get("expected_date") or ""),
                                              _LANE_RANK[dated_lane(r)]))
    if not ahead:
        return ""
    cells = []
    for r in ahead[:LEADS]:
        title = _one_line(r.get("title")) or "untitled in the source"
        cells.append(f'<div title="{esc(title)}"><span class="k">{esc(dated_wait(r, today))}'
                     f'</span><div class="row"><span class="v">{esc(dated_when(r))}</span>'
                     f'</div><span class="n">{esc(title)}</span></div>')
    return '<div class="tiles td-next">' + "".join(cells) + "</div>"


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


# --- what changed: how much, how material, and the ones to read -------------------------
CHANGE_DAYS = 30
CHANGE_LANES = (
    # Amber is the app's "material change" and is spent on the top rating alone.
    {"key": "high", "label": "High", "colour": TK.FLAG},
    {"key": "medium", "label": "Medium", "colour": TK.TEXT},
    {"key": "low", "label": "Low", "colour": TK.MUTED},
)
_RATING = {lane["key"]: n for n, lane in enumerate(CHANGE_LANES)}


def change_kind(row: dict) -> str:
    """The kind of change in words: "date slip", not "date_slip"."""
    return _one_line(str(row.get("change_type") or row.get("kind") or "").replace("_", " "))


def changes_figure(rows, today: dt.date, width: int) -> str:
    """Thirty days of detected changes on a grid of days and ratings."""
    items = [{"date": r.get("date"), "lane": r.get("significance"),
              "tip": f'{str(r.get("date") or "")[:10]} · {change_kind(r)} · '
                     f'{_one_line(r.get("headline"))}'}
             for r in rows or []]
    return CH.unit_lanes(items, CHANGE_LANES, today - dt.timedelta(days=CHANGE_DAYS - 1),
                         today, step="day", width=width, cap=6,
                         label="detected changes by day and rating")


def changes_leads(rows, ticker: str = "") -> str:
    """The three to read: the highest rated, newest first."""
    ranked = sorted(rows or [], key=lambda r: str(r.get("date") or ""), reverse=True)
    ranked.sort(key=lambda r: _RATING.get(r.get("significance"), len(_RATING)))
    out = []
    for r in ranked[:LEADS]:
        text = _one_line(r.get("headline"))
        if ticker and text.startswith(ticker + " "):
            text = text[len(ticker) + 1:]
        out.append({"tone": r.get("significance"), "tag": change_kind(r) or "change",
                    "date": str(r.get("date") or "")[:10],
                    "text": text[:1].upper() + text[1:], "url": r.get("url"),
                    "hover": _one_line(r.get("reason"))})
    return leads_html(out)


def kinds_html(rows, shown: int = 6) -> str:
    """What the changes were, counted by kind, the commonest first."""
    counts: dict = {}
    for r in rows or []:
        kind = change_kind(r)
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        return ""
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    cells = [f'<span class="td-kind"><b>{n}</b>{esc(kind)}</span>'
             for kind, n in ranked[:shown]]
    rest = sum(n for _kind, n in ranked[shown:])
    if rest:
        cells.append(f'<span class="td-kind"><b>{rest}</b>other</span>')
    return '<div class="td-kinds">' + "".join(cells) + "</div>"


# --- price: the window on screen and the figures that describe it -----------------------
PRICE_SPANS = (("1M", 31), ("3M", 92), ("6M", 183), ("1Y", 365), ("5Y", 1826))
DEFAULT_SPAN = "1Y"
SPAN_DAYS = dict(PRICE_SPANS)


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
    """The strip above the chart: last, as of, the window's change and its range. The
    change carries its sign and a true minus; a fall takes the down colour and the sign
    says the same."""
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
             ("as of", stats.get("as_of") or NO_DATA, missing),
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
