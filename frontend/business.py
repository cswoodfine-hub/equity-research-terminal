"""From revenue to cash: the three statements as one figure, period by period.

The financials tab drew two charts side by side, growth against margin and where the
money went, and printed the statements under them as a grid. The two charts answered
half a question each and the grid answered it in full but had to be read a cell at a
time. This is the one figure: what the company sold, what that cost, what was left, and
what it did with the cash, for every period on file, on one time axis.

One grammar, used twice. **The line is what came in, the stack is where it went, and the
gap between them is what was kept.**

  income   the line is revenue. The stack is cost of sales, R&D, SG&A, then tax and
           everything else. The gap to the line, in green, is net income. Where the
           stack runs past the line the company lost money, and the overrun is marked.
  cash     the line is cash from operations. The stack is capital expenditure,
           acquisitions, buybacks and dividends. The gap is cash kept; an overrun was
           paid for out of the balance sheet.

A third view, on the same periods, is growth and margin as two lines: growth in the
colour of the revenue line it is the slope of, margin in the green of the gap it is the
depth of. Under the cash view, net debt, the balance sheet's one reading, is printed and
not drawn: it is a level and the band above it is flows, and one axis cannot hold both.

One view is drawn at a time, chosen on the page, and after the three of them the same
selector offers every line of the three statements on its own (``render_line``).

A null is never drawn as zero. A period with no revenue has no column; a cost the filer
does not tag is left out of its stack and a remainder absorbs it by name ("other
operating" or "other costs" above the line the stack is split at, "tax and other" below
it);
a quarter's cash is worked out of the year-to-date figures a 10-Q prints, and where a
figure in that chain is missing the quarter is left empty.

Pure functions from the statements payload to an SVG string: nothing here reads
Streamlit, the network or the database.
"""

from __future__ import annotations

import html
import math
import re

from components import tokens as TK
from theme import MINUS, categorical
from trend import _domain, _runs

MONO = "IBM Plex Mono, ui-monospace, Menlo, monospace"
UI = "Archivo, system-ui, sans-serif"

# Drawn at the width it is shown at on a 1440px page, so a declared size is the
# rendered size. A narrower page scales it down and a wider one up.
W = 1380
PAD_L = 54            # the scale's figures
PAD_R = 206           # the latest period's lines, named and valued
BAND_MAX = 250        # the tallest a band of columns may stand
RATE_H = 220          # growth and margin
# The three composite views, one drawn at a time. The page's selector offers these and
# then every line of the three statements on its own (``render_line``).
VIEWS = (("income", "Revenue to profit"), ("rates", "Growth and margin"),
         ("cash", "Where the cash went"))
CAPTION = 16          # a band's own caption line
LABELS = 18           # the period row under a band
LEVEL_ROW = 20        # net debt, printed

# What each segment is drawn in. Green is the measured, positive figure and violet is the
# pipeline, which is what R&D and a bought programme both are, as everywhere in the
# terminal. The rest were neutrals stepping from grey to the hairline colour, and the
# figure read as one grey slab with a violet stripe; they are now the cool end of the
# validated categorical palette (``theme.categorical``), blue and teal, alternating up a
# stack so no two neighbours share a hue, and every segment is named beside the latest
# period, so no colour is the only signal.
#
# There are two remainders, one above a line of the income statement and one below it.
# One was drawn at first, named "Tax and other", and Vertex's quarter to June 2024
# stood 4.5bn of it against 0.2bn of tax: an operating charge with no line of its own.
# The line is operating income where the filer tags it, which 52 of the 60 companies
# with quarterly revenue do. Lilly, Merck, Pfizer, J&J, Bristol and Biogen do not, and
# are split at income before tax, so the upper remainder there holds interest as well
# and is named for less. A period has one upper remainder or the other, never both,
# which is why the two share a fill: the blue at a lighter weight. The lower remainder
# is the teal at that weight, so the tax never reads as a gap between the costs and the
# profit.
_PALETTE = categorical(8)
BLUE, TEAL = _PALETTE[2], _PALETTE[1]
REMAINDER = (BLUE, 0.45)
COSTS = (("cogs", "Cost of sales", BLUE, 1.0),
         ("rd", "R&D", TK.PURPLE_BOOK, 1.0),
         ("sga", "SG&A", TEAL, 1.0),
         ("opex_other", "Other operating", *REMAINDER),
         ("pretax_other", "Other costs", *REMAINDER),
         ("other", "Tax and other", TEAL, 0.45))
USES = (("capex", "Capital expenditure", BLUE, 1.0),
        ("acquisitions", "Acquisitions", TK.PURPLE_BOOK, 1.0),
        ("buybacks", "Buybacks", TEAL, 1.0),
        ("dividends", "Dividends", TEAL, 0.45))

_MONTHS = {"3M": 3, "6M": 6, "9M": 9, "12M": 12}


# --- the figures ---------------------------------------------------------------------

def _line(statement: dict, key: str) -> list:
    for row in (statement or {}).get("lines") or []:
        if row.get("key") == key:
            return [cell.get("value") for cell in row.get("cells") or []]
    return []


def _plus(*values):
    """A sum of what is there, or None when nothing is."""
    real = [v for v in values if v is not None]
    return sum(real) if real else None


def discrete(values: list, periods: list) -> list:
    """Each period's own cash from the year-to-date figures a 10-Q prints.

    Newest first, as the statement returns it. A first quarter and a full year on an
    annual basis are already their own period. A six month, nine month or full year
    figure on a quarterly basis is cumulative, and its own quarter is it less the
    figure three months shorter that follows it. Where that neighbour is missing, or is
    not the period three months shorter, the quarter is left empty: a guess here would
    be a quarter's cash off by the size of another quarter.
    """
    cumulative = _is_cumulative(periods)
    out = []
    for i, value in enumerate(values):
        period = periods[i] if i < len(periods) else {}
        months = _MONTHS.get(period.get("months"))
        if value is None:
            out.append(None)
        elif not cumulative or months == 3:
            out.append(value)
        elif months is None:
            out.append(None)
        else:
            older = periods[i + 1] if i + 1 < len(periods) else {}
            before = values[i + 1] if i + 1 < len(values) else None
            known = before is not None and _MONTHS.get(older.get("months")) == months - 3
            out.append(value - before if known else None)
    return out


def _is_cumulative(periods: list) -> bool:
    """A quarterly cash flow statement: some period on it is a year-to-date."""
    return any(p.get("period_type") == "YTD" for p in periods)


def prepare(statements: dict, trend: list = None) -> dict:
    """The periods, oldest first, each with what the figure draws. Pure.

    Two remainders, split at a line of the income statement, each named as one.

    Where the filer tags operating income, ``opex_other`` is what is left of revenue
    after the three named costs and operating income: operating costs with no line of
    their own, a bought programme written off or a plant written down, and any of the
    three the filer does not tag. ``other`` is then operating income less net income:
    interest, tax and whatever else sits below the line.

    Where it tags income before tax and not operating income, the split is there.
    ``pretax_other`` is what is left after the named costs and income before tax, which
    is the same operating costs and the interest and other income with them, and
    ``other`` is income before tax less net income, which is the tax.

    Where it tags neither there is nothing to split at, and ``other`` is everything
    revenue left after the named costs and net income, as it was before the split.

    Any of them can be negative: a gain booked in operations, or interest income larger
    than the tax. No segment is drawn for a negative one.
    """
    income, cash, balance = (statements.get(k) or {} for k in ("income", "cashflow", "balance"))
    periods = income.get("periods") or []
    if not periods:
        return {"periods": [], "unit": "", "divisor": 1.0}
    rates = {point.get("period_end"): point for point in (trend or [])}
    cash_periods = cash.get("periods") or []
    cash_at = {p.get("period_end"): i for i, p in enumerate(cash_periods)}
    level_at = {p.get("period_end"): i for i, p in enumerate(balance.get("periods") or [])}
    flow = {key: discrete(_line(cash, name), cash_periods) for key, name in (
        ("cfo", "CashFlowOperating"), ("capex", "CapitalExpenditure"),
        ("bought", "AcquisitionsNet"), ("iprd", "AcquiredIprd"),
        ("buybacks", "ShareRepurchases"), ("dividends", "DividendsPaid"))}
    net_debt = _line(balance, "NetDebt")
    lines = {key: _line(income, name) for key, name in (
        ("revenue", "Revenues"), ("cogs", "CostOfRevenue"),
        ("rd", "ResearchAndDevelopmentExpense"),
        ("sga", "SellingGeneralAndAdministrative"), ("operating", "OperatingIncomeLoss"),
        ("pretax", "IncomeBeforeTax"), ("net", "NetIncomeLoss"))}

    def at(values, index):
        return values[index] if index is not None and index < len(values) else None

    out = []
    for i, period in enumerate(periods):
        end = period.get("period_end")
        row = {"label": period.get("label") or "", "period_end": end}
        for key, values in lines.items():
            row[key] = at(values, i)
        named = _plus(row["cogs"], row["rd"], row["sga"]) or 0.0
        revenue, net = row["revenue"], row["net"]
        row["opex_other"] = row["pretax_other"] = None
        split_at, upper = ((row["operating"], "opex_other") if row["operating"] is not None
                           else (row["pretax"], "pretax_other"))
        if split_at is not None:
            row[upper] = revenue - named - split_at if revenue is not None else None
            row["other"] = split_at - net if net is not None else None
        else:
            row["other"] = (revenue - named - net
                            if revenue is not None and net is not None else None)
        row["gross"] = (row["revenue"] - row["cogs"]
                        if row["revenue"] is not None and row["cogs"] is not None else None)
        c = cash_at.get(end)
        row["cfo"] = at(flow["cfo"], c)
        row["capex"] = at(flow["capex"], c)
        row["acquisitions"] = _plus(at(flow["bought"], c), at(flow["iprd"], c))
        row["buybacks"] = at(flow["buybacks"], c)
        row["dividends"] = at(flow["dividends"], c)
        row["net_debt"] = at(net_debt, level_at.get(end))
        rate = rates.get(end) or {}
        row["growth"] = rate.get("revenue_growth")
        row["margin"] = (rate.get("net_margin") if rate.get("net_margin") is not None
                         else row["net"] / row["revenue"]
                         if row["net"] is not None and row["revenue"] else None)
        out.append(row)
    out.reverse()
    top = max((abs(r[k]) for r in out for k in ("revenue", "cfo") if r[k] is not None),
              default=0.0)
    billions = top >= 1e9
    return {"periods": out, "unit": "bn" if billions else "m",
            "divisor": 1e9 if billions else 1e6}


# --- the drawing ---------------------------------------------------------------------

def _esc(text) -> str:
    return html.escape(str(text), quote=True)


def _num(value, divisor: float, places: int = 2) -> str:
    """A figure at the figure's scale, with a true minus. A dash where there is none."""
    if value is None:
        return "—"
    scaled = value / divisor
    return f"{MINUS if scaled < 0 else ''}{abs(scaled):,.{places}f}"


def _pct(value, places: int = 1, signed: bool = False) -> str:
    if value is None:
        return "—"
    sign = MINUS if value < 0 else ("+" if signed else "")
    return f"{sign}{abs(value) * 100:,.{places}f}%"


def _text(x, y, s, size=10, fill=TK.MUTED, anchor="start", family=UI, weight="", extra=""):
    w = f' font-weight="{weight}"' if weight else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"'
            f' text-anchor="{anchor}" font-family="{family}"{w}{extra}>{_esc(s)}</text>')


def _seg(x1, y1, x2, y2, stroke, width=1.5) -> str:
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"'
            f' stroke="{stroke}" stroke-width="{width}" stroke-linecap="round"/>')


_ACROSS = re.compile(r' (x|x1|x2|cx|width)="(-?[0-9.]+)"')
_DOWN = re.compile(r' (y|y1|y2|cy|height)="(-?[0-9.]+)"')


def _fluid(body: str, width: float, height: float, label: str) -> str:
    """The drawing, placed in percentages of its own box, as a whole SVG.

    Every mark is laid out on a sheet ``width`` by ``height`` and then written as a
    share of it, with no viewBox. The page sizes the box (the row's width, and the
    height the screen has left), and the marks follow: columns widen, bands deepen.
    Type and strokes are in pixels and do not scale, so a label is eleven pixels on a
    laptop and on a wide monitor alike. A viewBox scaled the whole sheet as a picture,
    type included, and held its shape: on a wide screen it was either fifteen pixel
    labels or a blank strip beside the figure.

    A mark that has to keep its size (the readout under the pointer) is written with
    capital attribute names, which the conversion passes over and then lowers.
    """
    body = _ACROSS.sub(lambda m: f' {m[1]}="{float(m[2]) / width * 100:.3f}%"', body)
    body = _DOWN.sub(lambda m: f' {m[1]}="{float(m[2]) / height * 100:.3f}%"', body)
    for fixed in ("X", "Y", "WIDTH", "HEIGHT"):
        body = body.replace(f' {fixed}="', f' {fixed.lower()}="')
    return (f'<svg width="100%" height="{height}" role="img" overflow="visible"'
            f' style="font-family:{UI}" aria-label="{_esc(label)}">{body}</svg>')


def _step(top: float) -> float:
    """A round gridline step that puts about three lines under ``top``."""
    if top <= 0:
        return 1.0
    rough = top / 3
    power = 10 ** math.floor(math.log10(rough))
    for multiple in (1, 2, 2.5, 5, 10):
        if rough <= multiple * power:
            return multiple * power
    return 10 * power


def _dodge(items: list, low: float, high: float, gap: float = 12.5) -> list:
    """Label positions kept ``gap`` apart inside a band, each as near its mark as fits."""
    placed = sorted(items, key=lambda item: item[0])
    ys = [item[0] for item in placed]
    for i in range(1, len(ys)):
        ys[i] = max(ys[i], ys[i - 1] + gap)
    if ys and ys[-1] > high:
        ys[-1] = high
        for i in range(len(ys) - 2, -1, -1):
            ys[i] = min(ys[i], ys[i + 1] - gap)
    if ys and ys[0] < low:
        ys[0] = low
        for i in range(1, len(ys)):
            ys[i] = max(ys[i], ys[i - 1] + gap)
    return [(y, *item[1:]) for y, item in zip(ys, placed)]


def _band(rows, came_in: str, stack, kept_of, unit: float, base: float, x_at,
          bar_w: float, kept_fill: str, loss_fill: str) -> list:
    """One band of the grammar: the stack, what was kept on top of it, and the line.

    What was kept is drawn at its own size from the top of the stack. It meets the line
    where the stack and it account for everything that came in, which is the usual case;
    a company with other income larger than its tax keeps more than revenue left it, and
    its green then stands above the line by that much rather than being cut to fit.
    """
    out, path = [], []
    for i, row in enumerate(rows):
        line = row.get(came_in)
        cx = x_at(i)
        run = 0.0
        for key, _name, fill, opacity in stack:
            value = row.get(key)
            if value is None or value <= 0:
                continue
            y1, y0 = base - (run + value) * unit, base - run * unit
            # A hairline of the page's ground between segments, so two neutrals that
            # meet read as two blocks.
            out.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{y1:.1f}" width="{bar_w:.1f}"'
                       f' height="{max(y0 - y1, 0.6):.1f}" fill="{fill}"'
                       f' fill-opacity="{opacity}" stroke="{TK.GROUND}" stroke-width="0.8"/>')
            run += value
        if line is None:
            path.append(None)
            continue
        y_line = base - max(line, 0.0) * unit
        kept = kept_of(row)
        if kept is not None and kept > 0:
            out.append(f'<rect x="{cx - bar_w / 2:.1f}" y="{base - (run + kept) * unit:.1f}"'
                       f' width="{bar_w:.1f}" height="{max(kept * unit, 0.6):.1f}"'
                       f' fill="{kept_fill}"/>')
        elif run > line:
            # The stack ran past the line. A rail down the overrun, so it is seen as
            # more spent than came in and not as a taller column of the same kind.
            out.append(f'<rect x="{cx + bar_w / 2 + 1.5:.1f}" y="{base - run * unit:.1f}"'
                       f' width="2.5" height="{max((run - max(line, 0)) * unit, 1):.1f}"'
                       f' fill="{loss_fill}"/>')
        path.append((cx, y_line))
    # The line, stepped: flat across each period and joined to the next, broken where a
    # period has no figure.
    #
    # Segments and not a path. A path's points are numbers in the drawing's own units
    # and cannot be percentages, and the figure is placed in percentages so that it
    # fills whatever box the page gives it (``_fluid``).
    half = bar_w / 2 + 5
    for run_points in _runs([p[1] if p else None for p in path]):
        before = None
        for index, y in run_points:
            cx = path[index][0]
            if before is not None:
                out.append(_seg(before[0], before[1], cx - half, y, TK.TEXT, 1.6))
            out.append(_seg(cx - half, y, cx + half, y, TK.TEXT, 1.6))
            before = (cx + half, y)
    return out


def render(data: dict, currency: str = "", view: str = "income") -> str:
    """One view of the figure as SVG, or "" where there is too little to draw it.

    ``view`` is one of VIEWS. The three were first drawn stacked in one figure, and
    read together they are the whole chain from revenue to cash; on a page they were
    three charts' worth of marks at once, and the reader asked for one at a time.
    """
    rows = data.get("periods") or []
    if len([r for r in rows if r.get("revenue") is not None]) < 2:
        return ""
    div, unit_name, n = data["divisor"], data["unit"], len(rows)
    show_income, show_rates, show_cash = (view == key for key, _label in VIEWS)

    def stack_top(row, stack):
        return sum(v for v in (row.get(k) for k, *_ in stack) if v is not None and v > 0)

    income_top = max(max(r.get("revenue") or 0.0,
                         stack_top(r, COSTS) + max(r.get("net") or 0.0, 0.0)) for r in rows)
    cash_top = max(max(r.get("cfo") or 0.0, stack_top(r, USES)) for r in rows)
    has_cash = show_cash and cash_top > 0
    rate_points = [(r.get("growth"), r.get("margin")) for r in rows]
    rate_reals = [v for pair in rate_points for v in pair if v is not None]
    has_rates = show_rates and len(rate_reals) >= 2
    if (show_cash and not has_cash) or (show_rates and not has_rates) or (
            show_income and not income_top):
        return ""
    unit = BAND_MAX / (income_top if show_income else cash_top if has_cash else 1.0)
    income_h = income_top * unit if show_income else 0.0
    cash_h = cash_top * unit if has_cash else 0.0

    top = CAPTION + 6
    income_base = rate_base = cash_base = top
    level_y = None
    if show_income:
        income_base = top + income_h
        height = round(income_base + LABELS + 6)
    elif has_rates:
        rate_top = top + 6
        rate_base = rate_top + RATE_H
        height = round(rate_base + LABELS + 10)
    else:
        cash_base = top + cash_h
        level_y = cash_base + LABELS + 18
        height = round(level_y + 8)

    slot = (W - PAD_L - PAD_R) / n
    bar_w = min(slot * 0.6, 58.0)

    def x_at(index):
        return PAD_L + slot * (index + 0.5)

    last = rows[-1]
    label_x = x_at(n - 1) + bar_w / 2 + 18
    money = f'{(currency + " ") if currency else ""}{unit_name}'
    out = ["<style>.hoverband .tip{display:none}.hoverband:hover .tip{display:block}"
           ".hoverband:hover .hit{fill-opacity:0.045}</style>"]

    def caption(y_at, text):
        out.append(_text(0, y_at, text, 9.5, TK.MUTED, weight="600",
                         extra=' letter-spacing="0.07em"'))

    def scale(base, band_h, step):
        """The band's baseline and its round gridlines, the same step in both bands."""
        out.append(f'<line x1="{PAD_L - 6}" y1="{base:.1f}" x2="{W - PAD_R + 6}"'
                   f' y2="{base:.1f}" stroke="{TK.RULE_STRONG}"/>')
        value = step
        while value * unit <= band_h + 0.5:
            gy = base - value * unit
            out.append(f'<line x1="{PAD_L - 6}" y1="{gy:.1f}" x2="{W - PAD_R + 6}"'
                       f' y2="{gy:.1f}" stroke="{TK.RULE_FAINT}"/>')
            whole = abs(step / div - round(step / div)) < 1e-9
            out.append(_text(PAD_L - 10, gy + 3.5, _num(value, div, 0 if whole else 1),
                             10, TK.MUTED, "end", MONO))
            value += step

    step = _step((income_top if show_income else cash_top) / div) * div

    def periods_row(y_at):
        every = max(1, -(-n // 16))
        for i, row in enumerate(rows):
            if i % every and i != n - 1:
                continue
            newest = i == n - 1
            out.append(_text(x_at(i), y_at, row["label"], 10,
                             TK.TEXT if newest else TK.MUTED, "middle", MONO,
                             "600" if newest else ""))

    def named(items, low, high):
        """The latest period's lines, named and valued beside it."""
        for y_at, name, value, fill, opacity, bold in _dodge(items, low, high):
            if fill:
                out.append(f'<rect x="{label_x:.1f}" y="{y_at - 7.5:.1f}" width="8" height="8"'
                           f' fill="{fill}" fill-opacity="{opacity}"/>')
            else:
                out.append(f'<line x1="{label_x:.1f}" y1="{y_at - 3.5:.1f}"'
                           f' x2="{label_x + 8:.1f}" y2="{y_at - 3.5:.1f}"'
                           f' stroke="{TK.TEXT}" stroke-width="1.6"/>')
            out.append(_text(label_x + 13, y_at, name, 11, TK.TEXT,
                             weight="600" if bold else ""))
            out.append(_text(W - 2, y_at, value, 11, TK.TEXT, "end", MONO,
                             "600" if bold else ""))

    # --- income -------------------------------------------------------------------
    if show_income:
        caption(CAPTION - 4, f"INCOME · {money.upper()}")
        scale(income_base, income_h, step)
        out += _band(rows, "revenue", COSTS, lambda r: r.get("net"), unit, income_base, x_at,
                     bar_w, TK.UP, TK.DOWN)
        periods_row(income_base + 14)
        items, run = [], 0.0
        for key, name, fill, opacity in COSTS:
            value = last.get(key)
            if value is None or value <= 0:
                continue
            items.append((income_base - (run + value / 2) * unit + 4, name, _num(value, div),
                          fill, opacity, False))
            run += value
        if last.get("net") is not None and last.get("revenue") is not None:
            kept = last["net"]
            mid = (income_base - (run + max(kept, 0) / 2) * unit + 4 if kept >= 0
                   else income_base - run * unit + 4)
            items.append((mid, "Net income" if kept >= 0 else "Net loss", _num(kept, div),
                          TK.UP if kept >= 0 else TK.DOWN, 1.0, True))
        if last.get("revenue") is not None:
            items.append((income_base - last["revenue"] * unit - 5, "Revenue",
                          _num(last["revenue"], div), None, 1.0, True))
        named(items, CAPTION + 4, income_base + 2)

    # --- growth and margin ---------------------------------------------------------
    if has_rates:
        caption(CAPTION - 4, "GROWTH ON A YEAR AND NET MARGIN")
        lo, hi = _domain(rate_reals, include_zero=min(rate_reals) < 0)

        def ry(value):
            clamped = min(max(value, lo), hi)
            return rate_top + (hi - clamped) / (hi - lo) * RATE_H

        for value in (hi, (hi + lo) / 2, lo):
            out.append(f'<line x1="{PAD_L - 6}" y1="{ry(value):.1f}" x2="{W - PAD_R + 6}"'
                       f' y2="{ry(value):.1f}" stroke="{TK.RULE_FAINT}"/>')
            out.append(_text(PAD_L - 10, ry(value) + 3.5, _pct(value, 0), 10, TK.MUTED,
                             "end", MONO))
        if lo < 0 < hi:
            out.append(f'<line x1="{PAD_L - 6}" y1="{ry(0):.1f}" x2="{W - PAD_R + 6}"'
                       f' y2="{ry(0):.1f}" stroke="{TK.RULE_STRONG}" stroke-dasharray="3,3"/>')
        ends = []
        for index, (name, colour) in enumerate((("Revenue growth", TK.TEXT),
                                                ("Net margin", TK.UP))):
            values = [pair[index] for pair in rate_points]
            for run_points in _runs(values):
                for (i0, v0), (i1, v1) in zip(run_points, run_points[1:]):
                    out.append(_seg(x_at(i0), ry(v0), x_at(i1), ry(v1), colour))
                for i, v in run_points:
                    off = not (lo <= v <= hi)
                    out.append(f'<circle cx="{x_at(i):.1f}" cy="{ry(v):.1f}" r="2.1"'
                               f' fill="{TK.GROUND if off else colour}" stroke="{colour}"/>')
            newest = values[-1]
            if newest is not None:
                ends.append((ry(newest) + 4, name, _pct(newest, 1, signed=index == 0),
                             colour, 1.0, False))
        named(ends, rate_top + 6, rate_base + 4)
        periods_row(rate_base + 16)

    # --- cash ---------------------------------------------------------------------
    if has_cash:
        caption(CAPTION - 4, f"CASH · {money.upper()}")
        scale(cash_base, cash_h, step)
        def cash_kept(row):
            return (row["cfo"] - stack_top(row, USES)) if row.get("cfo") is not None else None

        out += _band(rows, "cfo", USES, cash_kept, unit, cash_base, x_at, bar_w,
                     TK.UP, TK.DOWN)
        periods_row(cash_base + 14)
        items, run = [], 0.0
        for key, name, fill, opacity in USES:
            value = last.get(key)
            if value is None or value <= 0:
                continue
            items.append((cash_base - (run + value / 2) * unit + 4, name, _num(value, div),
                          fill, opacity, False))
            run += value
        if last.get("cfo") is not None:
            items.append((cash_base - max(last["cfo"], 0) * unit - 5, "Cash from operations",
                          _num(last["cfo"], div), None, 1.0, True))
            kept = last["cfo"] - run
            items.append((cash_base - (run + max(kept, 0) / 2) * unit + 4 if kept >= 0
                          else cash_base - run * unit + 4,
                          "Cash kept" if kept >= 0 else "From the balance sheet",
                          _num(abs(kept), div), TK.UP if kept >= 0 else TK.DOWN, 1.0, False))
        named(items, cash_base - cash_h - 2, cash_base + 2)

    # --- the level, printed -------------------------------------------------------
    if level_y is not None and any(r.get("net_debt") is not None for r in rows):
        caption(level_y, "NET DEBT")
        for i, row in enumerate(rows):
            if row.get("net_debt") is None:
                continue
            newest = i == n - 1
            out.append(_text(x_at(i), level_y, _num(row["net_debt"], div, 1), 10.5,
                             TK.TEXT if newest else TK.MUTED, "middle", MONO,
                             "600" if newest else ""))

    # --- a period under the pointer: every line of it ------------------------------
    for i, row in enumerate(rows):
        facts = [(row["label"], "", True)]
        if show_income:
            # The upper remainder and the line it stops at, whichever this period has.
            split = ((("Other operating", _num(row["opex_other"], div)),
                      ("Operating income", _num(row.get("operating"), div)))
                     if row.get("opex_other") is not None else
                     (("Other costs", _num(row["pretax_other"], div)),
                      ("Income before tax", _num(row.get("pretax"), div)))
                     if row.get("pretax_other") is not None else ())
            shown = (("Revenue", _num(row.get("revenue"), div)),
                     ("Cost of sales", _num(row.get("cogs"), div)),
                     ("Gross profit", _num(row.get("gross"), div)),
                     ("R&D", _num(row.get("rd"), div)),
                     ("SG&A", _num(row.get("sga"), div)),
                     *split,
                     ("Tax and other", _num(row.get("other"), div)),
                     ("Net income", _num(row.get("net"), div)),
                     ("Net margin", _pct(row.get("margin"))))
        elif has_rates:
            shown = (("Growth on a year", _pct(row.get("growth"), 1, signed=True)),
                     ("Net margin", _pct(row.get("margin"))),
                     ("Revenue", _num(row.get("revenue"), div)),
                     ("Net income", _num(row.get("net"), div)))
        else:
            shown = (("Cash from operations", _num(row.get("cfo"), div)),
                     ("Capital expenditure", _num(row.get("capex"), div)),
                     ("Acquisitions", _num(row.get("acquisitions"), div)),
                     ("Buybacks", _num(row.get("buybacks"), div)),
                     ("Dividends", _num(row.get("dividends"), div)),
                     ("Net debt", _num(row.get("net_debt"), div)))
        facts += [(name, value, False) for name, value in shown]
        tip_w, line_h = 198, 14.5
        tip_h = line_h * len(facts) + 12
        # Hung from the period's own edge: to its right in the left half of the figure,
        # to its left in the right half, so it never runs off the sheet whatever width
        # the page gives it. Its own marks are in pixels from that edge.
        right_side = i < n / 2
        edge = x_at(i) + slot / 2 + 4 if right_side else x_at(i) - slot / 2 - 4
        shift = 0 if right_side else -tip_w
        tip = [f'<rect X="{shift}" Y="0" WIDTH="{tip_w}" HEIGHT="{tip_h:.1f}"'
               f' fill="{TK.PANEL}" stroke="{TK.RULE_STRONG}"/>']
        for k, (name, value, head) in enumerate(facts):
            ty = 15 + line_h * k
            bold = ' font-weight="600"' if head else ""
            tip.append(f'<text X="{shift + 9}" Y="{ty:.1f}" font-size="10.5"'
                       f' fill="{TK.TEXT if head else TK.MUTED}"'
                       f' font-family="{MONO if head else UI}"{bold}>{_esc(name)}</text>')
            if value:
                tip.append(f'<text X="{shift + tip_w - 9}" Y="{ty:.1f}" font-size="10.5"'
                           f' fill="{TK.TEXT}" text-anchor="end" font-family="{MONO}">'
                           f'{_esc(value)}</text>')
        out.append(f'<g class="hoverband"><rect class="hit" x="{x_at(i) - slot / 2:.1f}" y="0"'
                   f' width="{slot:.1f}" height="{height}" fill="{TK.TEXT}" fill-opacity="0"/>'
                   f'<svg class="tip" x="{edge:.1f}" Y="4" overflow="visible"'
                   f' pointer-events="none">{"".join(tip)}</svg></g>')

    return _fluid("".join(out), W, height,
                  f'{dict(VIEWS)[view]}, over the last {n} periods to {last["label"]}')


# --- one line of a statement, on its own --------------------------------------------

STATEMENTS = (("income", "Income statement"), ("balance", "Balance sheet"),
              ("cashflow", "Cash flow"))


def line_options(statements: dict) -> list:
    """(id, label) for every statement line with enough on file to draw: two figures.

    The id is ``statement:key`` and the label names the statement first, so the three
    lists read as three groups in a selector that has no groups of its own.
    """
    out = []
    for key, title in STATEMENTS:
        for line in (statements.get(key) or {}).get("lines") or []:
            figures = [cell.get("value") for cell in line.get("cells") or []]
            if sum(value is not None for value in figures) >= 2:
                out.append((f"{key}:{line.get('key')}", f"{title}: {line.get('label')}"))
    return out


def _line_scale(unit: str, top: float, currency: str):
    """(divisor, places, the unit as words) for a line's own unit."""
    if unit and unit.endswith("/shares"):
        return 1.0, 2, f"{unit.split('/')[0]} per share"
    if unit == "shares":
        return 1e6, 0, "shares, m"
    code = unit or currency
    if top >= 1e9:
        return 1e9, 2, f"{code} bn".strip()
    if top >= 1e6:
        return 1e6, 1, f"{code} m".strip()
    return 1.0, 2, code


def render_line(statements: dict, choice: str, currency: str = "") -> str:
    """One line of one statement as columns, each with its figure printed on it.

    A level (a balance sheet line) and a flow are both drawn as columns from nought,
    since each is read against its own past. A negative stands below the line. A cash
    flow line on a quarterly basis is year-to-date as filed, so each quarter is worked
    out of the chain (``discrete``) and the caption says so. A missing figure is no
    column.
    """
    key, _, name = (choice or "").partition(":")
    statement = statements.get(key) or {}
    line = next((row for row in statement.get("lines") or [] if row.get("key") == name), None)
    periods = statement.get("periods") or []
    if line is None or not periods:
        return ""
    figures = [cell.get("value") for cell in line.get("cells") or []]
    worked = key == "cashflow" and _is_cumulative(periods)
    if worked:
        figures = discrete(figures, periods)
    # A quarter's cash is named by its quarter, which is the income statement's label
    # for the same period end, not by the year-to-date span it was filed under.
    named_by = {p.get("period_end"): p.get("label") for p in
                (statements.get("income") or {}).get("periods") or []}
    labels = [(named_by.get(p.get("period_end")) if worked else None) or p.get("label") or ""
              for p in periods]
    rows = list(zip(labels, figures, [p.get("period_end") for p in periods]))[::-1]
    real = [value for _label, value, _end in rows if value is not None]
    if len(real) < 2:
        return ""
    div, places, unit_words = _line_scale(line.get("unit") or "", max(abs(v) for v in real),
                                          currency)
    hi, lo = max(0.0, max(real)), min(0.0, min(real))
    unit = BAND_MAX / ((hi - lo) or 1.0)
    top = CAPTION + 16
    base = top + hi * unit
    height = round(top + (hi - lo) * unit + LABELS + 20)
    n = len(rows)
    slot = (W - PAD_L - PAD_R) / n
    bar_w = min(slot * 0.6, 58.0)

    def x_at(index):
        return PAD_L + slot * (index + 0.5)

    title = dict(STATEMENTS).get(key, key)
    out = []
    out.append(_text(0, CAPTION - 4,
                     f'{title} · {line.get("label")} · {unit_words}'.upper(), 9.5, TK.MUTED,
                     weight="600", extra=' letter-spacing="0.07em"'))
    step = _step(max(hi, -lo) / div) * div
    whole = abs(step / div - round(step / div)) < 1e-9
    mark = step * math.ceil(lo / step) if lo < 0 else 0.0
    while mark <= hi + 1e-9:
        gy = base - mark * unit
        out.append(f'<line x1="{PAD_L - 6}" y1="{gy:.1f}" x2="{W - PAD_R + 6}" y2="{gy:.1f}"'
                   f' stroke="{TK.RULE_STRONG if abs(mark) < 1e-9 else TK.RULE_FAINT}"/>')
        out.append(_text(PAD_L - 10, gy + 3.5, _num(mark, div, 0 if whole else 1), 10,
                         TK.MUTED, "end", MONO))
        mark += step
    for i, (label, value, _end) in enumerate(rows):
        newest = i == n - 1
        out.append(_text(x_at(i), top + (hi - lo) * unit + 16, label, 10,
                         TK.TEXT if newest else TK.MUTED, "middle", MONO,
                         "600" if newest else ""))
        if value is None:
            continue
        y_value = base - value * unit
        out.append(f'<rect x="{x_at(i) - bar_w / 2:.1f}" y="{min(y_value, base):.1f}"'
                   f' width="{bar_w:.1f}" height="{max(abs(y_value - base), 0.8):.1f}"'
                   f' fill="{TK.TEXT if newest else TK.MUTED}"'
                   f' fill-opacity="{1.0 if newest else 0.7}"/>')
        out.append(_text(x_at(i), y_value - 5 if value >= 0 else y_value + 13,
                         _num(value, div, places), 10.5, TK.TEXT if newest else TK.MUTED,
                         "middle", MONO, "600" if newest else ""))
    # The latest figure, named, and against the same period a year before.
    label_x = x_at(n - 1) + bar_w / 2 + 18
    latest_label, latest, latest_end = rows[-1]
    out.append(_text(label_x, top + 12, line.get("label") or "", 11, TK.TEXT, weight="600"))
    if latest is not None:
        out.append(_text(label_x, top + 34, _num(latest, div, places), 17.5, TK.TEXT,
                         family=MONO, weight="600"))
        out.append(_text(label_x, top + 50, f"{latest_label} · {unit_words}", 10.5, TK.MUTED))
    year_ago = None
    if latest_end:
        want = f"{int(latest_end[:4]) - 1}{latest_end[4:7]}"
        year_ago = next((value for _label, value, end in rows
                         if end and end[:7] == want), None)
    if latest is not None and year_ago:
        change = latest / year_ago - 1
        out.append(_text(label_x, top + 70, _pct(change, 1, signed=True), 11,
                         TK.UP if change > 0 else TK.DOWN if change < 0 else TK.MUTED,
                         family=MONO, weight="600"))
        out.append(_text(label_x + 52, top + 70, "on a year before", 10.5, TK.MUTED))
    if worked:
        out.append(_text(label_x, top + 90, "each quarter from year-to-date", 10, TK.MUTED))
    return _fluid("".join(out), W, height,
                  f'{title}: {line.get("label")}, over the last {n} periods to {rows[-1][0]}')
