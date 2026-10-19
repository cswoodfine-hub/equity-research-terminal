"""The catalyst calendar, as months rather than as a table.

A day grid is the obvious shape for a calendar and the wrong one here. A third of the
dates are month-only: ClinicalTrials.gov gives "2026-08" for a primary completion and
nothing finer, so putting those on the first of the month would draw a precision the
registry does not have. Months are the honest cell size, and a day is shown inside one
only when the source gives a day.

The grid runs forward from the current month and shows every month in the window,
including the empty ones. A run of quiet months is the shape of a calendar: leaving
them out would put September next to December and lose the gap between them.

Pure: builds HTML from a list of catalysts and knows nothing about the API.
"""

from __future__ import annotations

import datetime as dt
import html

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DEFAULT_MONTHS = 12
MAX_TITLE = 58
# Bumped when the copy changes. A running server does not re-import a module that sits
# under a dot-directory, as a worktree does, so the page reloads one behind this.
REVISION = 2
# Where the rows come from, the last sentence of the caption and of the empty state.
SOURCES = ("Readouts come from the primary completion dates of Phase 1/2, Phase 2 and "
           "Phase 3 trials, regulatory dates from filings announcing an FDA acceptance, "
           "and both are rebuilt on every refresh.")


def _month_key(value: str) -> str:
    """The YYYY-MM a catalyst belongs to, whatever precision it carries."""
    return (value or "")[:7]


def _day(value: str) -> str:
    """The day of the month, or "" when the source only gave a month."""
    if len(value or "") < 10:
        return ""
    try:
        return str(int(value[8:10]))
    except ValueError:
        return ""


def _shorten(title: str, limit: int = MAX_TITLE) -> str:
    title = (title or "").strip()
    # The registry prefixes almost every readout with its phase, which the badge
    # already carries, so the words are spent twice in a narrow cell.
    for prefix in ("Phase 3, ", "Phase 2, ", "Phase 1, "):
        if title.startswith(prefix):
            title = title[len(prefix):]
            break
    return title if len(title) <= limit else title[: limit - 1] + "…"


def months_from(today: dt.date, count: int) -> list[str]:
    year, month = today.year, today.month
    out = []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def within(catalysts, months: int = DEFAULT_MONTHS, today=None) -> list:
    """The catalysts that fall inside the months the grid draws.

    The fetch window is a day count and the grid is a month count, so the two do not end
    on the same day. Filtering here means the caption counts what is on screen and an
    item can never be fetched and then quietly not drawn.
    """
    today = today or dt.date.today()
    span = set(months_from(today, months))
    return [c for c in catalysts if _month_key(c.get("expected_date")) in span]


def render(catalysts, months: int = DEFAULT_MONTHS, today=None) -> str:
    """HTML for the calendar. Empty when there is nothing in the window."""
    today = today or dt.date.today()
    catalysts = within(catalysts, months, today)
    if not catalysts:
        return ""

    by_month: dict[str, list] = {}
    for item in catalysts:
        by_month.setdefault(_month_key(item.get("expected_date")), []).append(item)
    for entries in by_month.values():
        # Dated entries first and in order, then the month-only ones, which belong to
        # the month as a whole rather than to a point inside it.
        entries.sort(key=lambda c: (not _day(c.get("expected_date")),
                                    c.get("expected_date") or ""))

    this_month = f"{today.year:04d}-{today.month:02d}"
    cells = []
    for key in months_from(today, months):
        entries = by_month.get(key, [])
        year, month = int(key[:4]), int(key[5:7])
        classes = ["cal-month"]
        if key == this_month:
            classes.append("now")
        if not entries:
            classes.append("empty")

        rows = []
        for item in entries:
            day = _day(item.get("expected_date"))
            kind = html.escape(item.get("catalyst_type") or "")
            confidence = item.get("date_confidence") or ""
            # The cell truncates, so the full title lives in a panel that appears on
            # hover. A registry title runs past 120 characters and the distinguishing
            # part is often at the end, which is exactly what a truncation removes:
            # two Retatrutide studies read identically until the comparator.
            full = html.escape((item.get("title") or "").strip())
            when = html.escape(item.get("expected_date") or "")
            precision = ("month only, the registry gives no day"
                         if confidence == "month" else confidence)
            marked = ' none" title="month only' if confidence == "month" else '"'
            rows.append(
                # The styled popup is clipped once a busy month scrolls, so the same
                # words ride on a native tooltip too. A reader never loses the full
                # title to a scrollbar.
                f'<div class="cal-item" title="{when} · {kind} · {full}">'
                f'<span class="cal-day{marked}">{day or "—"}</span>'
                f'<span class="cal-title">{html.escape(_shorten(item.get("title")))}'
                f'</span>'
                f'<span class="cal-kind">{kind}</span>'
                f'<span class="cal-pop"><b>{when}</b>'
                f'<span class="cal-pop-k">{kind} · {html.escape(precision)}</span>'
                f'{full}</span>'
                f'</div>')

        cells.append(
            f'<div class="{" ".join(classes)}">'
            f'<div class="cal-head"><span>{MONTHS[month - 1]} {year % 100:02d}</span>'
            f'{f"<span class=cal-n>{len(entries)}</span>" if entries else ""}</div>'
            # The entries scroll inside the month rather than stretching it. One busy
            # month used to set the height of every box in the grid.
            f'<div class="cal-body">{"".join(rows)}</div></div>')

    return f'<div class="cal">{"".join(cells)}</div>'


def expander_label(catalysts, months: int = DEFAULT_MONTHS, today=None) -> str:
    """"Calendar, 24 months · 72 dated events": the fold the grid sits in, counting what
    the grid draws rather than what was fetched."""
    n = len(within(catalysts, months, today))
    return f"Calendar, {months} months · {n} dated {'event' if n == 1 else 'events'}"


def caption(catalysts, months: int = DEFAULT_MONTHS, today=None) -> str:
    """One line on what is in the grid and how precisely it is dated (company-scorecard.md
    8.5). It used to say every row came from a Phase 3 date, while the grid also held
    Phase 2 and Phase 1/2 readouts: the derivation takes a large Phase 2 study, and a
    company's own lead phase when it has nothing at Phase 3."""
    catalysts = within(catalysts, months, today)
    if not catalysts:
        return ""
    month_only = sum(1 for c in catalysts if (c.get("date_confidence") or "") == "month")
    text = (f"{len(catalysts)} ahead in the next {months} months. ")
    if month_only:
        text += (f"{month_only} carry a month and no day, which is all the registry "
                 "gives, so they sit in the month rather than on a date in it. ")
    return text + SOURCES
