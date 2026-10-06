"""The redesigned Universe tab: one company in focus against its cohort (AstraZeneca first).

Pure builders over the payload of ``GET /universe/command`` (backend/universe_command.py).
Every function takes the payload, or a slice of it, and returns a markup string: HTML for
``st.markdown`` and complete ``<svg>`` elements for the chart mounts and the ``uvboard``
component. None of them touches Streamlit, the network or a clock, so the tests run them
on a saved payload.

Ported from the approved mockups (design_ui/universe_a/gen.py, the base, and
design_ui/universe_b/build.py, the grafts) with the hand-placed parts replaced by rules:
label placement is a greedy collision search, short names come from the payload, and
every figure is computed from the payload here. Colour in the SVGs comes from
components/tokens.py, as in charts.py; the HTML reads the CSS tokens. A null is never
drawn as a zero: it is left off the chart and named, or printed as "no free data".
"""

from __future__ import annotations

import datetime as dt
import html
import math
import re
import statistics

from components import tokens as TK

MINUS = "−"
NO_DATA = "no free data"
WINDOWS = (("1m", "1 month"), ("3m", "3 months"), ("1y", "1 year"))
WIN_LABEL = dict(WINDOWS)
WIN_WORDS = {"1m": "in a month", "3m": "in three months", "1y": "in a year"}
LEAD_OVER = {"1m": "over a month", "3m": "over three months", "1y": "over a year"}

T = dict(ground=TK.GROUND, panel=TK.PANEL, rule=TK.RULE, rule_strong=TK.RULE_STRONG,
         rule_faint=TK.RULE_FAINT, text=TK.TEXT, muted=TK.MUTED, up=TK.UP, down=TK.DOWN,
         flag=TK.FLAG, pre=TK.PHASE_RAMP["preclinical"], p1=TK.PHASE_RAMP["Phase 1"],
         p2=TK.PHASE_RAMP["Phase 2"], p3=TK.PHASE_RAMP["Phase 3"],
         filed=TK.PHASE_RAMP["filed"], approved=TK.PHASE_RAMP["approved"],
         orange=TK.ORANGE_BOOK, purple=TK.PURPLE_BOOK)


# ------------------------------------------------------------------------------ helpers
def hx(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def blend(a, b, t):
    """t of colour a over colour b, the way theme._blend mixes a token into the ground."""
    A, B = hx(a), hx(b)
    return "#%02X%02X%02X" % tuple(round(A[i] * t + B[i] * (1 - t)) for i in range(3))


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def sgn(x, dp=1, unit="%"):
    """A signed figure with a true minus. x is already in display units."""
    if x is None:
        return NO_DATA
    s = f"{abs(x):,.{dp}f}"
    if float(s.replace(",", "")) == 0:
        return s + unit
    return ("+" if x > 0 else MINUS) + s + unit


def pc(v, dp=1):
    return NO_DATA if v is None else sgn(v * 100, dp)


def num(v, dp=2):
    if v is None:
        return NO_DATA
    s = f"{abs(v):,.{dp}f}"
    return (MINUS + s) if v < 0 else s


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }".replace(" ", "")


def _d(iso):
    try:
        return dt.date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return None


def dday(iso):
    d = _d(iso)
    if d is None:
        s = str(iso or "")
        if len(s) == 7:          # a month only
            m = _d(s + "-01")
            return f"{m:%b} {m.year}" if m else s
        return s or NO_DATA
    return f"{d.day} {d:%b}"


def dlong(iso):
    d = _d(iso)
    return f"{d.day} {d:%b} {d.year}" if d else (str(iso) if iso else NO_DATA)


def place(vals, focal, better="higher"):
    """1-based place of focal among vals, ties sharing a place; and the count."""
    v = vals[focal]
    if better == "higher":
        return 1 + sum(1 for x in vals.values() if x > v), len(vals)
    return 1 + sum(1 for x in vals.values() if x < v), len(vals)


def text(x, y, s, size=10, fill=None, anchor="start", weight=None, mono=False,
         cls=None, opacity=None, extra=""):
    a = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{size}"',
         f'fill="{fill or T["text"]}"']
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if weight:
        a.append(f'font-weight="{weight}"')
    c = " ".join(k for k in (("m" if mono else ""), cls or "") if k)
    if c:
        a.append(f'class="{c}"')
    if opacity is not None:
        a.append(f'opacity="{opacity}"')
    return f"<text {' '.join(a)}{extra}>{esc(s)}</text>"


def lab_w(s, size=9.5, mono=False):
    """A rough width for a label, for the collision checks."""
    return len(s) * size * (0.6 if mono else 0.56)


def rect_hits_circle(rx0, ry0, rx1, ry1, cx, cy, r, pad=2):
    nx, ny = min(max(cx, rx0), rx1), min(max(cy, ry0), ry1)
    return (nx - cx) ** 2 + (ny - cy) ** 2 < (r + pad) ** 2


def rects_hit(a, b, pad=2):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def labels_hit(a, b, pad=3):
    """Two label boxes collide: a gap of ``pad`` side to side, none needed between two
    tiers stacked above one another."""
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] <= b[1] or b[3] <= a[1])


def _join_and(items):
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def _this_year(p):
    """The payload's own year, read off its date; never the clock."""
    d = _d(p.get("today")) or _d(p.get("price_date"))
    return d.year if d else None


def _loe_year(p):
    """The last year of the five the exclusivity share counts, this one included."""
    y = _this_year(p)
    return y + 4 if y else None


def _cos(p):
    return p.get("companies") or {}


def _focal(p):
    return (p.get("focal") or {}).get("ticker") or p.get("ticker")


def _name(p, t):
    return (_cos(p).get(t) or {}).get("short") or t


def _cohort_noun(p):
    return (p.get("cohort") or {}).get("noun") or "companies"


def _tickers(p):
    """The cohort by market cap, largest first, companies with no cap last."""
    return list(p.get("tickers") or sorted(_cos(p)))


def _window(p, w=None):
    w = w or p.get("window") or "1y"
    return w if w in WIN_LABEL else "1y"


def _rel(p, w):
    return {t: c["rel"][w]["rel"] * 100 for t, c in _cos(p).items()
            if ((c.get("rel") or {}).get(w) or {}).get("rel") is not None}


def _own(p, w):
    return {t: c["rel"][w]["own"] for t, c in _cos(p).items()
            if ((c.get("rel") or {}).get(w) or {}).get("own") is not None}


# ------------------------------------------------------------- control row and lead
def status_line(p):
    """The right end of the control row: the close the page reads to, and the page's notes
    behind a hover. The cohort and the company in focus are in the close's hover. A read
    taken while the API was still valuing the group leads with how many are valued, in the
    flag colour, and says the rest on hover, so the partial state costs the page no line."""
    n = (p.get("cohort") or {}).get("n") or len(_cos(p))
    f = _focal(p)
    who = (_cos(p).get(f) or {}).get("short") or f
    tip = (f"{n} {_cohort_noun(p)}, prices to the {dlong(p.get('price_date'))} close; "
           f"{who} in focus, set by the company picker")
    part = ""
    if not p.get("complete", True):
        valued, of = _valued(p)
        part = (f'<span class="uv-nt uv-pt" tabindex="0">{valued} of {of} valued ▾'
                f'<span class="uv-nt-c">{esc(incomplete_text(p))}</span></span>')
    return (f'<div class="uv-status">{part}<span title="{esc(tip)}">closes to '
            f'{esc(dday(p.get("price_date")))}</span>'
            f'<span class="uv-nt" tabindex="0">notes ▾'
            f'<span class="uv-nt-c">{esc(notes_text(p))}</span></span></div>')


def lead_line(p, w=None):
    """The window in one line: the two regions' median moves and the focal company's move
    and place. Empty when any figure it needs is missing."""
    w = _window(p, w)
    lead = (p.get("lead") or {}).get(w) or {}
    us, eu = lead.get("us_median"), lead.get("eu_median")
    own = lead.get("own") or {}
    f = _focal(p)
    if us is None or eu is None or f not in own or not lead.get("us_n") or not lead.get("eu_n"):
        return ""

    def fig(v):
        tone = "up" if v > 0 else ("down" if v < 0 else "")
        return f'<b class="{tone}">{esc(pc(v))}</b>'
    rank = 1 + sum(1 for v in own.values() if v > own[f])
    med = statistics.median(own.values())
    tone = "up" if own[f] > med else ("even" if own[f] == med else "down")
    noun = _cohort_noun(p)
    tip = (f"Median share price move of the US and the European {noun}, and "
           f"{(_cos(p).get(f) or {}).get('short') or f}'s own move and place among the "
           f"{len(own)}, {WIN_WORDS[w]} to the {dlong(p.get('price_date'))} close")
    return (f'<div class="uv-lead" title="{esc(tip)}">US median {fig(us)}, Europe {fig(eu)}, '
            f'{esc(f)} {fig(own[f])} <span class="rk {tone}">{ordinal(rank)} of {len(own)}</span> '
            f'{LEAD_OVER[w]}</div>')


def _valued(p):
    """How many of the cohort carry a model value on this read, and of how many."""
    cos = _cos(p)
    return (sum(1 for c in cos.values() if (c.get("model") or {}).get("upside") is not None),
            len(cos))


def incomplete_text(p):
    """What a read taken while the API was still valuing the group (``complete`` false)
    says: how many of the cohort have a model value so far, and that the page reads again
    rather than holding the gap. Empty on a complete read."""
    if p.get("complete", True):
        return ""
    n, of = _valued(p)
    return (f"The API was still valuing the group when this page read it: {n} of {of} "
            f"{_cohort_noun(p)} have a model value so far. It is not held: reload in a "
            f"minute for the full read.")


def incomplete_note(p):
    """The incomplete read as a line of its own, for the company dialog. The tab says it
    in the control row (``status_line``)."""
    note = incomplete_text(p)
    return f'<div class="uv-partial">{esc(note)}</div>' if note else ""


# ------------------------------------------------- the company against the group (row 2)
def ranked_card(title, vals, fmt, focal, better="higher", note=None, med=None):
    """The hover card on a spotlight cell: all of the cohort, best first, the median
    drawn where it falls and the focal company washed."""
    rows = sorted(vals.items(), key=lambda kv: -kv[1] if better == "higher" else kv[1])
    med = statistics.median(vals.values()) if med is None else med
    out = [f'<div class="uv-hc"><div class="hc-t">{esc(title)}</div>']
    drew_med = False
    for i, (t, v) in enumerate(rows, 1):
        past = (v < med) if better == "higher" else (v > med)
        if past and not drew_med:
            out.append(f'<div class="hc-med">median {esc(fmt(med))}</div>')
            drew_med = True
        me = " me" if t == focal else ""
        out.append(f'<div class="hc-r{me}"><span>{i}</span><span>{esc(t)}</span>'
                   f'<span>{esc(fmt(v))}</span></div>')
    if note:
        out.append(f'<div class="hc-n">{esc(note)}</div>')
    out.append("</div>")
    return "".join(out)


def _missing(p, vals):
    gone = [t for t in _tickers(p) if t not in vals]
    if not gone:
        return ""
    return f'{", ".join(gone)} {"has" if len(gone) == 1 else "have"} none.'


def _cell(key, label, vals, focal, value_html, sub, better="higher", fmt=None, note=None,
          med=None):
    """One ranking cell on three lines: the label with a marker saying a hover lists the
    cohort, the value in its tone with the place beside it, and one sub-line. The hover
    card ranks every company. A focal company with no figure prints "no free data" and no
    place."""
    fmt = fmt or (lambda v: f"{v:.0f}")
    if not vals:
        return (f'<div class="c-{key}"><div class="k"><span>{esc(label)}</span></div>'
                f'<div class="vr"><div class="v none">{NO_DATA}</div></div>'
                f'<div class="s">{esc(note or "")}</div></div>')
    card = ranked_card(label, vals, fmt, focal, better, note, med)
    m = statistics.median(vals.values()) if med is None else med
    head = (f'<div class="k"><span>{esc(label)}</span>'
            f'<span class="all" title="Hover for all {len(vals)}, ranked">▾</span></div>')
    if focal not in vals:
        return (f'<div class="c-{key}">{head}<div class="vr"><div class="v none">{NO_DATA}</div>'
                f'<span class="r">not placed</span></div>'
                f'<div class="s">median {esc(fmt(m))}</div>{card}</div>')
    fv = vals[focal]
    good = (fv > m) if better == "higher" else (fv < m)
    tone = "" if fv == m else ("up" if good else "down")
    p_, n = place(vals, focal, better)
    return (f'<div class="c-{key}">{head}<div class="vr"><div class="v {tone}">{value_html}</div>'
            f'<span class="r"><b>{ordinal(p_)}</b> of {n}</span></div>'
            f'<div class="s">{sub}</div>{card}</div>')


def range_bar(price, lo, hi, w=196):
    """The share price on its own 52-week range: the low and the high either side of a
    bar filled to the price. One text line tall."""
    fr = min(max((price - lo) / (hi - lo), 0.0), 1.0)
    x0, x1 = 64, w - 40
    tip = (f"{pc(price / lo - 1)} above the 52-week low; 52-week range {lo:.2f} to {hi:.2f}")
    return (f'<svg class="uv-rng" width="{w}" height="13" viewBox="0 0 {w} 13" role="img" '
            f'aria-label="52-week range"><title>{esc(tip)}</title>'
            + text(0, 10, "52 wk", 9, T["muted"])
            + text(x0 - 4, 10, f"{lo:.2f}", 9.5, T["muted"], "end", mono=True)
            + f'<rect x="{x0}" y="5" width="{x1 - x0}" height="3" fill="{T["rule"]}"/>'
            f'<rect x="{x0}" y="5" width="{(x1 - x0) * fr:.1f}" height="3" fill="{T["down"]}"/>'
            f'<line x1="{x0 + (x1 - x0) * fr:.1f}" y1="1" x2="{x0 + (x1 - x0) * fr:.1f}" y2="12" '
            f'stroke="{T["flag"]}" stroke-width="2"/>'
            + text(x1 + 4, 10, f"{hi:.2f}", 9.5, T["muted"], mono=True) + "</svg>")


def spotlight_html(p, w=None):
    """"<Company> against the group": the share price and seven rankings, each with its
    place and a hover card ranking every company."""
    w = _window(p, w)
    cos = _cos(p)
    f = _focal(p)
    me = cos.get(f) or {}
    date = p.get("price_date")
    cells = []

    # 1. The price, against its own 52-week range.
    price = me.get("price")
    rng = me.get("range_52w") or {}
    lo, hi = rng.get("low"), rng.get("high")
    head = (f'<div class="k"><span>Share price, '
            f'{esc(dday(me.get("price_as_of") or date))} close</span></div>')
    if price is None:
        cells.append(f'<div class="c0">{head}<div class="vr"><div class="v none">{NO_DATA}</div>'
                     f'</div></div>')
    else:
        d1 = me.get("change_1d")
        day = (f'<span class="r {"down" if d1 < 0 else "up"}">{esc(pc(d1))} on the day</span>'
               if d1 is not None else "")
        bar = (range_bar(price, lo, hi) if lo is not None and hi is not None and hi > lo
               else f'<span>52-week range: {NO_DATA}</span>')
        cells.append(
            f'<div class="c0">{head}<div class="vr"><div class="v">{price:.2f}'
            f'<span class="u">USD</span></div>{day}</div><div class="s">{bar}</div></div>')

    # 2. The window move against XLV.
    vals = _rel(p, w)
    last = min(vals, key=vals.get) if vals else None
    med = statistics.median(vals.values()) if vals else None
    xv = f"{sgn(vals[f], 1, '')}<span class=\"u\">pts</span>" if f in vals else NO_DATA
    cells.append(_cell(
        "rel", f"Against XLV, {WIN_LABEL[w]}", vals, f, xv,
        f'{esc(last)} last, median {esc(sgn(med, 1, " pts"))}' if last else "",
        fmt=lambda v: sgn(v, 1, " pts"),
        note=f"Price move less XLV's total return, to the {dday(date)} close."))

    # 3. The model's 12-month upside.
    up = {t: c["model"]["upside"] * 100 for t, c in cos.items()
          if (c.get("model") or {}).get("upside") is not None}
    mm = me.get("model") or {}
    upm = statistics.median(up.values()) if up else None
    to = f'to {mm["forward_12m"]:.2f}, ' if mm.get("forward_12m") is not None else ""
    cells.append(_cell(
        "up", "Model, 12 months", up, f, sgn(up[f]) if f in up else NO_DATA,
        f'{to}{esc(mm.get("rating") or "no rating")}, median {esc(sgn(upm))}',
        fmt=lambda v: sgn(v),
        note=("Upside to the model's 12-month value. " + _missing(p, up)).strip()))

    # 4. The street target.
    st_ = {t: c["street"]["upside"] * 100 for t, c in cos.items()
           if (c.get("street") or {}).get("upside") is not None}
    sm = me.get("street") or {}
    rated = ", ".join(f'{sm.get(k)} {k}' for k in ("buy", "hold", "sell") if sm.get(k) is not None)
    sto = f'to {sm["value"]:.2f}, ' if f in st_ and sm.get("value") is not None else ""
    cells.append(_cell(
        "st", "Street target", st_, f, sgn(st_[f]) if f in st_ else NO_DATA,
        sto + esc(rated or "no ratings on file"), fmt=lambda v: sgn(v),
        note=(f"Nasdaq consensus target over the {dday(date)} close. " + _missing(p, st_)).strip()))

    # 5. The scorecard.
    score = {t: c["score"]["score"] for t, c in cos.items()
             if (c.get("score") or {}).get("score") is not None}
    rr = (me.get("score") or {}).get("rank_range")
    smed = ((p.get("cohort") or {}).get("medians") or {}).get("score")
    cells.append(_cell(
        "sc", "Scorecard", score, f,
        f'{score[f]}<span class="u">of 100</span>' if f in score else NO_DATA, "",
        fmt=lambda v: f"{v:.0f}", med=smed,
        note="Five business pillars; value and momentum are kept out."
             + (f" {f} ranks {rr[0]} to {rr[1]} under random weightings of the pillars." if rr else "")))

    # 6. Dated catalysts in 12 months.
    cat = {t: c["catalysts_12m"] for t, c in cos.items() if c.get("catalysts_12m") is not None}
    cells.append(_cell(
        "ca", "Catalysts, 12 months", cat, f,
        f'{cat[f]}<span class="u">dated</span>' if f in cat else NO_DATA, "",
        fmt=lambda v: f"{v:.0f}", note="Dated readouts and decisions in the next 12 months."))

    # 7. Trial dates slipped (fewer is better).
    slipped = {t: (c.get("slip") or {}).get("slipped") for t, c in cos.items()
               if (c.get("slip") or {}).get("slipped") is not None}
    absent = [t for t in _tickers(p) if not ((cos.get(t) or {}).get("slip") or {}).get("on_file")]
    sl = me.get("slip") or {}
    cells.append(_cell(
        "sl", "Trial dates slipped", slipped, f,
        str(slipped[f]) if f in slipped else NO_DATA, "",
        better="lower", fmt=lambda v: f"{v:.0f}",
        note=("Primary completion dates moved later in snapshot history."
              + (f' {slipped[f]} of {f}\'s {sl["moved"]} moved dates slipped.'
                 if f in slipped and sl.get("moved") is not None else "")
              + (f' {", ".join(absent)} {"has" if len(absent) == 1 else "have"} no moved trial on file.'
                 if absent else ""))))

    # 8. Exclusivity lost within five years (less is better).
    loe = {t: c["loe"]["share_5y"] * 100 for t, c in cos.items()
           if (c.get("loe") or {}).get("share_5y") is not None}
    year = _loe_year(p)
    lm = me.get("loe") or {}
    lmed = statistics.median(loe.values()) if loe else None
    risk = lm.get("at_risk_5y_usd")
    cells.append(_cell(
        "lo", f"Revenue LOE by {year}" if year else "Revenue LOE in five years", loe, f,
        f'{loe[f]:.0f}%' if f in loe else NO_DATA,
        (f'${risk / 1e9:.1f}bn; ' if f in loe and risk is not None else "")
        + (f"median {lmed:.0f}%" if lmed is not None else ""),
        better="lower", fmt=lambda v: f"{v:.0f}%",
        note=f"Share of tagged product revenue whose exclusivity ends by {year or 'the fifth year'}."))
    return f'<div class="uv-sp">{"".join(cells)}</div>'


# -------------------------------------------------------------- hero: price against value
# Drawn 1:1 in the hero's 7fr column at 1440: the hero, with the board beside it, has to fit
# one screen with the rankings above and the tabbed panel below.
MAP_W, MAP_H = 803, 312
ML, MR, MT, MB = 50, 14, 12, 32
R_MAX = 30.0
TINT = {"Strong buy": ("up", 0.42), "Buy": ("up", 0.26), "Hold": ("muted", 0.22),
        "Sell": ("down", 0.30), "Strong sell": ("down", 0.42)}


def _plotted(p, w):
    rel = _rel(p, w)
    return [t for t in _tickers(p) if t in rel
            and ((_cos(p)[t].get("model") or {}).get("upside") is not None)]


def map_counts(p, w=None):
    """'17 plotted, BAYN has no model value' for the section count."""
    w = _window(p, w)
    plotted = _plotted(p, w)
    gone = [t for t in _tickers(p) if t not in plotted]
    if not gone:
        return f"{len(plotted)} plotted"
    if not plotted:
        return "none plotted, no model value on file"
    # Named while they fit the section rule; counted past that.
    who = ", ".join(gone) if len(gone) <= 3 else str(len(gone))
    return f'{len(plotted)} plotted, {who} {"has" if len(gone) == 1 else "have"} no model value'



def hero_map(p, w=None):
    """x is the price move against XLV over the window, y the model's 12-month upside,
    area the market cap, tint the model's rating. The focal company is ringed with its
    12-month range and its street target. Labels are placed by collision checks."""
    w = _window(p, w)
    cos = _cos(p)
    f = _focal(p)
    plotted = _plotted(p, w)
    if not plotted:
        return ""
    rel = _rel(p, w)
    up = {t: cos[t]["model"]["upside"] * 100 for t in plotted}
    caps = {t: cos[t].get("cap_usd_bn") for t in plotted if cos[t].get("cap_usd_bn")}
    cmax = max(caps.values()) if caps else 1.0

    def bub_r(t):
        c = caps.get(t)
        return max(4.0, R_MAX * math.sqrt(c / cmax)) if c else 4.0

    pw, ph = MAP_W - ML - MR, MAP_H - MT - MB
    xs = [rel[t] for t in plotted]
    step = 10 if (max(xs) - min(xs)) > 40 else 5
    x0 = math.floor((min(xs) - 4) / step) * step
    x1 = math.ceil((max(xs) + 4) / step) * step
    if x0 >= 0:
        x0 = -step
    if x1 <= 0:
        x1 = step
    rating = ((p.get("focal") or {}).get("fair_value") or {}).get("rating") or {}
    price = (cos.get(f) or {}).get("price")
    ys = list(up.values())
    extra = []
    if price and rating.get("forward_low") is not None and rating.get("forward_high") is not None:
        extra += [(rating["forward_low"] / price - 1) * 100, (rating["forward_high"] / price - 1) * 100]
    sv = (cos.get(f) or {}).get("street") or {}
    if f in plotted and sv.get("upside") is not None:
        extra.append(sv["upside"] * 100)
    y0 = min(-75.0, math.floor((min(ys + extra) - 10) / 20) * 20)
    y1 = max(85.0, math.ceil((max(ys + extra) + 10) / 20) * 20)

    def X(v):
        return ML + (v - x0) / (x1 - x0) * pw

    def Y(v):
        return MT + (y1 - v) / (y1 - y0) * ph

    circ = {t: (X(rel[t]), Y(up[t]), bub_r(t)) for t in plotted}
    placed = []

    def clear(rect, own=None, pad=2):
        if any(rects_hit(rect, r_, pad) for r_ in placed):
            return False
        return not any(rect_hits_circle(*rect, cx, cy, r, pad) for t, (cx, cy, r) in circ.items()
                       if t != own)

    def inside(rect):
        return rect[0] >= ML and rect[2] <= ML + pw and rect[1] >= MT and rect[3] <= MT + ph

    o = [f'<svg class="uv-map" width="{MAP_W}" height="{MAP_H}" viewBox="0 0 {MAP_W} {MAP_H}" '
         f'role="img" aria-label="Price against value, {WIN_LABEL[w]}">']
    o.append(f'<rect x="{ML}" y="{MT}" width="{X(0)-ML:.1f}" height="{Y(0)-MT:.1f}" '
             f'fill="{blend(T["up"], T["ground"], 0.05)}"/>')
    o.append(f'<rect x="{X(0):.1f}" y="{Y(0):.1f}" width="{ML+pw-X(0):.1f}" '
             f'height="{MT+ph-Y(0):.1f}" fill="{blend(T["down"], T["ground"], 0.05)}"/>')
    v = x0
    while v <= x1 + 1e-9:
        o.append(f'<line x1="{X(v):.1f}" y1="{MT}" x2="{X(v):.1f}" y2="{MT+ph}" '
                 f'stroke="{T["rule_faint"]}"/>')
        o.append(text(X(v), MT + ph + 14, sgn(v, 0, ""), 9.5, T["muted"], "middle", mono=True))
        v += step
    yv = math.ceil(y0 / 20) * 20
    while yv <= y1 - 5:
        o.append(f'<line x1="{ML}" y1="{Y(yv):.1f}" x2="{ML+pw}" y2="{Y(yv):.1f}" '
                 f'stroke="{T["rule_faint"]}"/>')
        # A tick on the plot's foot would print into the corner the x axis's first label
        # holds; its gridline stays and the label goes.
        if MT + ph - Y(yv) >= 8:
            o.append(text(ML - 6, Y(yv) + 3.5, sgn(yv, 0), 9.5, T["muted"], "end", mono=True))
        yv += 20
    o.append(f'<line x1="{X(0):.1f}" y1="{MT}" x2="{X(0):.1f}" y2="{MT+ph}" '
             f'stroke="{T["rule_strong"]}" stroke-width="1.2"/>')
    o.append(f'<line x1="{ML}" y1="{Y(0):.1f}" x2="{ML+pw}" y2="{Y(0):.1f}" '
             f'stroke="{T["rule_strong"]}" stroke-width="1.2"/>')
    med = statistics.median(up.values())
    o.append(f'<line x1="{ML}" y1="{Y(med):.1f}" x2="{ML+pw}" y2="{Y(med):.1f}" '
             f'stroke="{T["muted"]}" stroke-dasharray="2 4" opacity="0.7"/>')
    for xm, anc in ((ML + 8, "start"), (ML + pw - 8, "end")):
        lab = f"group median {sgn(med)}"
        wd = len(lab) * 5.0
        rect = (xm if anc == "start" else xm - wd, Y(med) - 12,
                (xm + wd) if anc == "start" else xm, Y(med) - 2)
        if clear(rect):
            o.append(text(xm, Y(med) - 4, lab, 9, T["muted"], anc, cls="halo"))
            placed.append(rect)
            break

    med_band = (ML, Y(med) - 0.5, ML + pw, Y(med) + 0.5)
    # Quadrant names: the first clear corner of each quadrant.
    quads = (("LAGGED XLV, MODEL UPSIDE", (ML, X(0)), (MT, Y(0))),
             ("BEAT XLV, MODEL UPSIDE", (X(0), ML + pw), (MT, Y(0))),
             ("LAGGED XLV, ABOVE MODEL", (ML, X(0)), (Y(0), MT + ph)),
             ("BEAT XLV, ABOVE MODEL", (X(0), ML + pw), (Y(0), MT + ph)))
    on_top = []
    for lab, (qx0, qx1), (qy0, qy1) in quads:
        wd = len(lab) * 6.3
        if qx1 - qx0 < wd + 16 or qy1 - qy0 < 24:
            continue
        best = None
        for yy in (qy0 + 14, qy1 - 6):
            for anc in ("start", "end"):
                xx = qx0 + 8 if anc == "start" else qx1 - 8
                rect = (xx if anc == "start" else xx - wd, yy - 9,
                        (xx + wd) if anc == "start" else xx, yy + 2)
                if rect[0] < qx0 or rect[2] > qx1:
                    continue
                # The dashed group median runs the plot's width; a name is not set on it.
                if clear(rect) and not rects_hit(rect, med_band, 1):
                    best = (xx, yy, anc, rect)
                    break
            if best:
                break
        if not best:
            xx = qx1 - 8 if qx0 > ML + 1 else qx0 + 8
            anc = "end" if qx0 > ML + 1 else "start"
            yy = qy1 - 6 if qy0 > MT + 1 else qy0 + 14
            best = (xx, yy, anc, (xx - wd if anc == "end" else xx, yy - 9,
                                  xx if anc == "end" else xx + wd, yy + 2))
        xx, yy, anc, rect = best
        on_top.append(text(xx, yy, lab, 9, T["muted"], anc, cls="cap halo"))
        placed.append(rect)

    o.append(text(ML + pw / 2, MAP_H - 6,
                  f"Share price move against XLV, {WIN_LABEL[w]} to {dlong(p.get('price_date'))}, points",
                  10, T["muted"], "middle"))
    o.append(f'<text transform="translate(12 {MT+ph/2:.1f}) rotate(-90)" font-size="10" '
             f'fill="{T["muted"]}" text-anchor="middle">Model upside to its 12-month value</text>')

    # The focal company: its 12-month range whisker and its street ring, under the bubbles.
    if f in circ:
        ax, ay, ar = circ[f]
        if price and rating.get("forward_low") is not None and rating.get("forward_high") is not None:
            flo = (rating["forward_low"] / price - 1) * 100
            fhi = (rating["forward_high"] / price - 1) * 100
            o.append(f'<line x1="{ax:.1f}" y1="{Y(flo):.1f}" x2="{ax:.1f}" y2="{Y(fhi):.1f}" '
                     f'stroke="{T["up"]}" stroke-width="2" opacity="0.8"><title>Model 12-month range '
                     f'{rating["forward_low"]:.2f} to {rating["forward_high"]:.2f}</title></line>')
            for yy in (flo, fhi):
                o.append(f'<line x1="{ax-5:.1f}" y1="{Y(yy):.1f}" x2="{ax+5:.1f}" y2="{Y(yy):.1f}" '
                         f'stroke="{T["up"]}" stroke-width="2" opacity="0.8"/>')
            top = min(Y(flo), Y(fhi))
        else:
            top = ay - ar - 5
        if sv.get("upside") is not None and sv.get("value") is not None:
            sy = Y(sv["upside"] * 100)
            o.append(f'<line x1="{ax:.1f}" y1="{top-2:.1f}" x2="{ax:.1f}" y2="{sy+6:.1f}" '
                     f'stroke="{T["text"]}" stroke-dasharray="2 3" opacity="0.7"/>')
            o.append(f'<circle cx="{ax:.1f}" cy="{sy:.1f}" r="5.5" fill="none" stroke="{T["text"]}" '
                     f'stroke-width="1.5"><title>Street target {sv["value"]:.2f}, '
                     f'{pc(sv["upside"])}</title></circle>')
            lab = f"street {sv['value']:.2f}"
            wd = len(lab) * 5.8
            for anc in ("end", "start"):
                xx = ax - 10 if anc == "end" else ax + 10
                rect = (xx - wd if anc == "end" else xx, sy - 8, xx if anc == "end" else xx + wd, sy + 4)
                if clear(rect):
                    break
            o.append(text(xx, sy + 3.5, lab, 9.5, T["text"], anc, mono=True, cls="halo"))
            placed.append(rect)

    # The size key: the first clear corner of the plot.
    rs = [(v_, lab_, R_MAX * math.sqrt(v_ / cmax)) for v_, lab_ in
          ((1000, "$1tn"), (500, "$500bn"), (100, "$100bn")) if v_ <= cmax * 1.6]
    if rs:
        kw, kh = 2 * rs[0][2] + 50, 2 * rs[0][2] + 4
        spots = ((ML + pw - 8 - rs[0][2], MT + 30 + kh), (ML + pw - 8 - rs[0][2], MT + ph - 10),
                 (ML + 60 + rs[0][2], MT + 30 + kh), (ML + 60 + rs[0][2], MT + ph - 10))
        kx, ky = spots[0]
        for kx_, ky_ in spots:
            rect = (kx_ - rs[0][2] - 50, ky_ - kh, kx_ + rs[0][2], ky_)
            if clear(rect, pad=4):
                kx, ky = kx_, ky_
                break
        for v_, lab_, rr_ in rs:
            o.append(f'<circle cx="{kx:.1f}" cy="{ky-rr_:.1f}" r="{rr_:.1f}" fill="none" '
                     f'stroke="{T["muted"]}" stroke-width="0.9" opacity="0.8"/>')
            o.append(f'<line x1="{kx:.1f}" y1="{ky-2*rr_:.1f}" x2="{kx-rs[0][2]-4:.1f}" '
                     f'y2="{ky-2*rr_:.1f}" stroke="{T["rule_strong"]}"/>')
            o.append(text(kx - rs[0][2] - 6, ky - 2 * rr_ + 3, lab_, 9, T["muted"], "end", mono=True))
        placed.append((kx - rs[0][2] - 50, ky - kh, kx + rs[0][2], ky))

    # Bubbles, largest first, each a click target for the company dialog.
    labels = []
    for t in sorted(plotted, key=lambda t: -(caps.get(t) or 0)):
        x, y, r = circ[t]
        c = cos[t]
        cap = c.get("cap_usd_bn")
        tip = (f"{c.get('name') or t} ({t}): {sgn(rel[t], 1, ' pts')} against XLV over "
               f"{WIN_LABEL[w]}; model {pc(c['model']['upside'])} to its 12-month value, rated "
               f"{c['model'].get('rating') or 'no rating'}; market cap "
               + (f"${cap:,.0f}bn" if cap is not None else NO_DATA) + ". Click for the detail.")
        if t == f:
            o.append(f'<g class="b azn" data-ticker="{esc(t)}"><circle cx="{x:.1f}" '
                     f'cy="{y:.1f}" r="{r+5:.1f}" fill="none" stroke="{T["up"]}" '
                     f'stroke-width="1.2"/><circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                     f'fill="{blend(T["up"], T["ground"], 0.62)}" stroke="{T["text"]}" '
                     f'stroke-width="1.8"><title>{esc(tip)}</title></circle></g>')
            labels.append(text(x, y + 4, t, 11, T["text"], "middle", 700, mono=True,
                               extra=' pointer-events="none"'))
            continue
        tone, a_ = TINT.get(c["model"].get("rating"), ("muted", 0.22))
        col = T[tone]
        o.append(f'<g class="b" data-ticker="{esc(t)}"><circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" '
                 f'fill="{blend(col, T["ground"], a_)}" stroke="{blend(col, T["ground"], 0.85)}" '
                 f'stroke-width="1"><title>{esc(tip)}</title></circle></g>')
    for t in sorted(plotted, key=lambda t: -(caps.get(t) or 0)):
        if t == f:
            continue
        x, y, r = circ[t]
        wd = len(t) * 6.2
        cands = []
        if r >= 13:
            cands.append(("in", x, y + 3.5, "middle", (x - wd / 2, y - 5, x + wd / 2, y + 5)))
        cands += [("r", x + r + 4, y + 3.5, "start", (x + r + 3, y - 5, x + r + 4 + wd, y + 5)),
                  ("l", x - r - 4, y + 3.5, "end", (x - r - 4 - wd, y - 5, x - r - 3, y + 5)),
                  ("t", x, y - r - 4, "middle", (x - wd / 2, y - r - 13, x + wd / 2, y - r - 3)),
                  ("b", x, y + r + 12, "middle", (x - wd / 2, y + r + 3, x + wd / 2, y + r + 13))]
        pick = None
        for kind, lx, ly, anc, rect in cands:
            ok = not any(rects_hit(rect, r_, 1) for r_ in placed)
            if kind != "in":
                ok = ok and clear(rect, own=t, pad=1) and inside(rect)
            if ok:
                pick = (kind, lx, ly, anc, rect)
                break
        if pick is None:
            pick = cands[0]
        kind, lx, ly, anc, rect = pick
        placed.append(rect)
        labels.append(text(lx, ly, t, 10, T["text"], anc, 600, mono=True, opacity=0.92,
                           cls=None if kind == "in" else "halo", extra=' pointer-events="none"'))
    o.extend(labels)
    o.extend(on_top)

    # The focal callout in the clearest lower corner, with a leader.
    if f in circ:
        ax, ay, ar = circ[f]
        p_rel, n_rel = place(rel, f)
        p_up, n_up = place(up, f)
        mm = cos[f]["model"]
        lines = [f"{sgn(rel[f], 1, ' pts')} against XLV, {ordinal(p_rel)} of {n_rel}",
                 f"Model {pc(mm['upside'])}"
                 + (f" to {mm['forward_12m']:.2f}" if mm.get("forward_12m") is not None else "")
                 + f", {ordinal(p_up)} of {n_up}"]
        if sv.get("upside") is not None:
            lines.append(f"Street {pc(sv['upside'])} to {sv['value']:.2f}")
        cw = 200
        best = None
        for cx, cy in ((ML + 14, MT + ph - 70), (ML + pw - 14 - cw, MT + ph - 70),
                       (ML + 14, MT + 40), (ML + pw - 14 - cw, MT + 40)):
            rect = (cx - 4, cy - 16, cx + cw, cy + 46)
            hits = sum(1 for t, (bx, by, br) in circ.items() if rect_hits_circle(*rect, bx, by, br))
            hits += sum(1 for r_ in placed if rects_hit(rect, r_))
            if best is None or hits < best[0]:
                best = (hits, cx, cy)
        _, cx, cy = best
        ex = cx + 150 if cx < ax else cx + 40
        o.append(f'<path d="M{ax:.1f} {ay+(ar+5 if cy > ay else -ar-5):.1f} L{ex:.1f} {cy-14:.1f} '
                 f'L{cx:.1f} {cy-14:.1f}" fill="none" stroke="{T["up"]}" stroke-width="1" '
                 f'opacity="0.8" pointer-events="none"/>')
        o.append(text(cx, cy, f, 12, T["up"], weight=700, mono=True))
        if price is not None:
            o.append(text(cx + 10 + len(f) * 7.5, cy, f"{price:.2f}", 12, T["text"], weight=600,
                          mono=True))
        for i, ln in enumerate(lines):
            o.append(text(cx, cy + 15 + 14 * i, ln, 10, T["text"], cls="halo"))
    o.append("</svg>")
    return "".join(o)


def map_legend(p):
    """One line: the rating tints, the focal company's marks, the size key and the click."""
    f = _focal(p)

    def sw(var, a, border):
        return (f'<i style="background:color-mix(in oklab, var(--{var}) {a}%, var(--ground));'
                f'border:1px solid {border}"></i>')
    return (f'<div class="uv-leg" title="Above model: the price is over its 12-month value. '
            f'Below the dashed line: less upside than the group median.">'
            f'<span>{sw("up", 42, "var(--up)")}Strong buy</span>'
            f'<span>{sw("up", 26, "color-mix(in oklab, var(--up) 85%, var(--ground))")}Buy</span>'
            f'<span>{sw("muted", 22, "var(--muted)")}Hold</span>'
            f'<span>{sw("down", 30, "var(--down)")}Sell</span>'
            f"<span>the model's rating</span>"
            f'<span><i class="ring"></i>street target</span>'
            f'<span><i class="wh"></i>{esc(f)} 12-month range</span>'
            f'<span>area: market cap</span>'
            f'<span class="sp">click a bubble for its detail</span></div>')


# ------------------------------------------------------------- the company board (right)
# Drawn 1:1 in the hero's 5fr column at 1440. The week's news is no longer a column of
# chips: its count and its lines are in the row's hover, which leaves the radar the width.
BW, ROW_H, FOC_H, HEAD_H, FOOT_H = 573, 14.5, 40, 20, 4
CX = dict(tk=6, wk=42, wk_w=52, rel=98, rel_w=52, rd0=162, rd1=544, n=571)
NEWS_ORDER = ("deal", "readout", "approval", "regulatory", "filing", "slip")
# The focal row's asset labels: one tier over the dots and one under them.
BOARD_TIERS = {-1: -8, 1: 15}


def heat(v, clip, w, x, y, h, label):
    if v is None:
        return (f'<rect x="{x}" y="{y+1.5:.1f}" width="{w}" height="{h-3:.1f}" fill="{T["panel"]}"/>'
                + text(x + w / 2, y + h / 2 + 3.5, "n/a", 9, T["muted"], "middle", mono=True))
    t = min(abs(v) / clip, 1.0)
    col = T["up"] if v > 0 else T["down"]
    fill = blend(col, T["panel"], 0.14 + 0.62 * t) if abs(v) > 1e-9 else T["panel"]
    return (f'<rect x="{x}" y="{y+1.5:.1f}" width="{w}" height="{h-3:.1f}" fill="{fill}"/>'
            + text(x + w / 2, y + h / 2 + 3.5, label, 10, T["text"], "middle", 500, mono=True))


def place_labels(marks, mid, x_min, x_max, size=9, tiers=None):
    """Labels for the focal row's events, placed greedily: on the tiers given (offsets
    from the row's middle; above the dots on two tiers and below on one by default),
    centred, then leaning right or left, so no two overlap and none leaves the radar. A
    mark that finds no clear spot keeps its hover only. Returns
    [(x, y, anchor, label, tier, mark_x)]."""
    offs = tiers or {-1: -9, 1: 16, -2: -19}
    ys = {k: mid + v for k, v in offs.items()}
    order = [(t, a) for a in ("middle", "start", "end") for t in (-1, 1, -2) if t in ys]
    taken, out = [], []
    for xx, label in sorted(marks, key=lambda m: m[0]):
        wd = lab_w(label, size)
        for tier, anc in order:
            y = ys[tier]
            x0 = {"middle": xx - wd / 2, "start": xx - 3, "end": xx - wd + 3}[anc]
            # Cap height to descender: a 9px label inks about 7px above its baseline.
            rect = (x0, y - size * 0.8, x0 + wd, y + 2)
            if rect[0] < x_min or rect[2] > x_max:
                continue
            if any(labels_hit(rect, r) for r in taken):
                continue
            taken.append(rect)
            lx = {"middle": xx, "start": xx - 3, "end": xx + 3}[anc]
            out.append((lx, y, anc, label, tier, xx))
            break
    return out


def _news_tip(items):
    """The row hover's news: how many items in seven days and each one's line."""
    if not items:
        return "no news in seven days"
    lines = "; ".join(f'{dday(n_["date"])} {n_["kind"]}: {(n_.get("text") or "").strip()}'
                      for n_ in items)
    return f'{len(items)} news {"item" if len(items) == 1 else "items"} in seven days: {lines}'


def board_svg(p, w=None):
    """One row per company, the focal company pinned first and taller: the week's move
    and the window's move against XLV as heat cells, and the next 90 days as a radar of
    dated events. The week's news is in each row's hover. Asset labels are drawn on the
    focal row only; another row's only label is a firm FDA date. The radar's only rules
    are today and the month starts, each named in the header."""
    w = _window(p, w)
    cos = _cos(p)
    f = _focal(p)
    rows = [f] + [t for t in _tickers(p) if t != f] if f in cos else _tickers(p)
    win = p.get("events_window") or {}
    r0, r1 = _d(win.get("start")), _d(win.get("end"))
    if not rows or r0 is None or r1 is None:
        return ""
    span = max((r1 - r0).days, 1)

    def rx(day):
        return CX["rd0"] + (day / span) * (CX["rd1"] - CX["rd0"])

    H = HEAD_H + (FOC_H if f in cos else ROW_H) + ROW_H * (len(rows) - 1) + FOOT_H
    clip = {"1m": 10, "3m": 25, "1y": 40}[w]
    rel = _rel(p, w)
    o = [f'<svg class="uv-board" width="{BW}" height="{H:.0f}" viewBox="0 0 {BW} {H:.0f}" '
         f'role="img" aria-label="Company board">']
    hy = 13
    o.append(text(CX["wk"] + CX["wk_w"] / 2, hy, "WEEK", 9, T["muted"], "middle", cls="cap"))
    o.append(text(CX["rel"] + CX["rel_w"] / 2, hy, f"VS XLV {w.upper()}", 9, T["muted"],
                  "middle", cls="cap"))
    o.append(text(CX["n"], hy, "N", 9, T["muted"], "end", cls="cap"))
    o.append(text(rx(0) + 3, hy, dday(r0.isoformat()).upper(), 9, T["text"], cls="cap"))
    month = (r0.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    rules = []
    while month <= r1:
        rules.append(month)
        if rx((month - r0).days) < CX["rd1"] - 20:
            o.append(text(rx((month - r0).days) + 3, hy, f"{month:%b}".upper(), 9, T["muted"],
                          cls="cap"))
        month = (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    top, bottom = HEAD_H, H - FOOT_H
    for m in rules:
        xx = rx((m - r0).days)
        o.append(f'<line x1="{xx:.1f}" y1="{top-4}" x2="{xx:.1f}" y2="{bottom:.1f}" '
                 f'stroke="{T["rule_faint"]}"/>')
    o.append(f'<line x1="{rx(0):.1f}" y1="{top-4}" x2="{rx(0):.1f}" y2="{bottom:.1f}" '
             f'stroke="{T["rule_strong"]}" stroke-width="1.2"/>')

    events = p.get("events") or []
    y = top
    for t in rows:
        c = cos.get(t) or {}
        me = t == f
        h = FOC_H if me else ROW_H
        mid = y + h / 2
        mine = [e for e in events if e["ticker"] == t]
        wk = c.get("change_5d")
        news = sorted(c.get("news") or [], key=lambda n_: NEWS_ORDER.index(n_["kind"])
                      if n_["kind"] in NEWS_ORDER else 9)
        tip = (f"{c.get('name') or t}: week {pc(wk)}; "
               f"{sgn(rel.get(t), 1, ' pts') if t in rel else NO_DATA} against XLV over "
               f"{WIN_LABEL[w]}; {len(mine)} dated in the next 90 days; {_news_tip(news)}. "
               f"Click for the detail.")
        o.append(f'<g class="row{" me" if me else ""}" data-ticker="{esc(t)}"><title>{esc(tip)}</title>')
        if me:
            o.append(f'<rect class="bg" x="0" y="{y:.1f}" width="{BW}" height="{h}" '
                     f'fill="{blend(T["up"], T["panel"], 0.14)}"/>'
                     f'<rect x="0" y="{y:.1f}" width="2" height="{h}" fill="{T["up"]}"/>')
        else:
            o.append(f'<rect class="bg" x="0" y="{y:.1f}" width="{BW}" height="{h}" '
                     f'fill="{T["ground"]}" fill-opacity="0"/>')
        o.append(f'<line x1="0" y1="{y+h:.1f}" x2="{BW}" y2="{y+h:.1f}" '
                 f'stroke="{T["rule"] if me else T["rule_faint"]}"/>')
        o.append(text(CX["tk"], mid + 3.5, t, 11 if me else 10,
                      T["up"] if me else T["text"], weight=700 if me else 600, mono=True))
        hh = ROW_H
        o.append(heat(wk * 100 if wk is not None else None, 8, CX["wk_w"], CX["wk"],
                      mid - hh / 2, hh, pc(wk)))
        o.append(heat(rel.get(t), clip, CX["rel_w"], CX["rel"], mid - hh / 2, hh,
                      sgn(rel.get(t), 1, "")))
        bars = [e for e in mine if e["month"]]
        for i, e in enumerate(bars):
            m0 = _d(e["date"] + "-01")
            m1 = (m0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
            xa, xb = rx(max((m0 - r0).days, 0)), rx(min((m1 - r0).days, span))
            col = T.get(e.get("phase") or "", T["flag"])
            yy = mid - 4 + (i % 3) * 3
            o.append(f'<rect x="{xa+1:.1f}" y="{yy:.1f}" width="{max(xb-xa-2, 1):.1f}" height="2" '
                     f'fill="{col}" opacity="0.55"><title>{esc(e["date"] + " (month only): " + (e.get("title") or ""))}'
                     f'</title></rect>')
        dots = sorted([e for e in mine if not e["month"] and _d(e["date"])],
                      key=lambda e: e["date"])
        late, lastx, k, placed_dots = [], -99.0, 0, []
        for e in dots:
            xx = rx((_d(e["date"]) - r0).days)
            k = k + 1 if xx - lastx < 4 else 0
            lastx = xx
            yy = mid + ((-1) ** k) * (k and 2.5 + (k // 2) * 1.5)
            r = 3.8 if me else 2.6
            tip = (f'{dlong(e["date"])} ({e.get("confidence")}): {e.get("title") or ""}'
                   + (f' · {e["nct"]}' if e.get("nct") else ""))
            if e.get("regulatory"):
                s = r + 1.6
                o.append(f'<path d="M{xx:.1f} {yy-s:.1f} L{xx+s:.1f} {yy:.1f} L{xx:.1f} {yy+s:.1f} '
                         f'L{xx-s:.1f} {yy:.1f}Z" fill="{T["flag"]}" stroke="{T["text"]}" '
                         f'stroke-width="1.1"><title>{esc(tip)}</title></path>')
                if me or e.get("firm"):
                    kind = "PDUFA" if (e.get("type") or "").upper() == "PDUFA" else "FDA"
                    late.append(text(xx + s + 3, yy + 3.2, f"{kind} {dday(e['date'])}", 9,
                                     T["flag"], weight=600, cls="halo"))
            else:
                col = T.get(e.get("phase") or "", T["flag"])
                ring = (f' stroke="{T["text"]}" stroke-width="1.2"' if e.get("firm") else
                        f' stroke="{T["ground"]}" stroke-width="0.8"')
                o.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="{r}" fill="{col}"{ring}>'
                         f'<title>{esc(tip)}</title></circle>')
            placed_dots.append((xx, e))
        o.extend(late)
        if me:
            # A study whose registry title names no drug has a condition or the title's
            # first words for a short name: it keeps its hover rather than reading as an
            # asset on the row.
            marks = [(xx, f'{e["short"]} Ph {e["phase"][1]}' if e.get("phase") else e["short"])
                     for xx, e in placed_dots
                     if e.get("short") and e.get("short_basis") not in ("condition", "title")]
            # Leaders first, then the labels, so a label's halo covers any leader that
            # runs behind it.
            placed_labels = place_labels(marks, mid, CX["rd0"] - 2, BW - 30, tiers=BOARD_TIERS)
            for lx, ly, anc, label, tier, mx in placed_labels:
                y_end = ly + 2 if tier < 0 else ly - 9
                o.append(f'<line x1="{mx:.1f}" y1="{mid + (-5 if tier < 0 else 5):.1f}" '
                         f'x2="{mx:.1f}" y2="{y_end:.1f}" stroke="{T["muted"]}" '
                         f'stroke-width="0.8" opacity="0.7"/>')
            for lx, ly, anc, label, tier, mx in placed_labels:
                o.append(text(lx, ly, label, 9, T["text"], anc, 500, cls="halo"))
        o.append(text(CX["n"], mid + 3.5, str(len(mine)), 10, T["text"] if me else T["muted"],
                      "end", 600 if me else 400, mono=True))
        o.append("</g>")
        y += h
    o.append("</svg>")
    return "".join(o)


def board_counts(p):
    ev = p.get("events") or []
    firm = sum(1 for e in ev if e.get("firm"))
    xw = (p.get("xlv_week") or {}).get("change")
    return f"{len(ev)} dated, {firm} firm · XLV week {pc(xw)}"


def board_legend():
    return ('<div class="uv-leg">'
            '<span><i style="background:var(--phase-3)"></i>Phase 3</span>'
            '<span><i style="background:var(--phase-2)"></i>Phase 2</span>'
            '<span><i style="background:var(--text);box-shadow:0 0 0 1.5px var(--text)"></i>firm date</span>'
            '<span><i class="dia" style="background:var(--flag)"></i>regulatory</span>'
            '<span><i class="bar" style="background:var(--phase-3);opacity:.6"></i>month only</span>'
            '<span class="sp">hover a row for its news, click for the detail</span></div>')


def section_html(label, basis="", count=""):
    """The house section rule as one string, for blocks built in one markdown call."""
    chip = f'<span class="sec-basis">{esc(basis)}</span>' if basis else ""
    tail = f'<span class="sec-count">{esc(count)}</span>' if count else ""
    return f'<div class="sec"><span class="sec-label">{esc(label)}</span>{chip}{tail}</div>'


def hero_html(p, w=None):
    """The hero band as one block: the map with its legend beside the board with its
    legend, at the Key insights 7fr/5fr seam. This is what the uvboard frame renders."""
    w = _window(p, w)
    svg = hero_map(p, w)
    body = (f'<div class="chart-mount stretch">{svg}</div>{map_legend(p)}' if svg else
            f'<div class="uv-empty">{NO_DATA}: no company in the group has a model value '
            f'and a move against XLV on this read, so the map has nothing to place.</div>')
    return (f'<div class="uv uv-frame"><div class="uv-hero">'
            f'<div>{section_html("Price against value", f"{WIN_LABEL[w]} · model upside · market cap", map_counts(p, w))}'
            f'{body}</div>'
            f'<div>{section_html("Company board", "week · window · next 90 days", board_counts(p))}'
            f'<div class="chart-mount stretch">{board_svg(p, w)}</div>{board_legend()}</div>'
            f'</div></div>')


# ---------------------------------------------------------- "This week, ranked" (graft)
# Drawn at the width its grid column gives it (universe.css, .uv-wm > summary), so the
# axis words print at 9px rather than being scaled under it.
IW, IH = 100, 28
ACCENT = {"deal": "var(--up)", "market": "var(--muted)", "readout": "var(--phase-3)",
          "readout2": "var(--phase-2)", "approval": "var(--phase-approved)",
          "slip": "var(--down)", "regulatory": "var(--phase-filed)"}


def _mini_open():
    return (f'<svg class="uv-mini" viewBox="0 0 {IW} {IH}" width="{IW}" height="{IH}" '
            f'aria-hidden="true">')


def mini_spark(vals, marks=(), stroke=None, mark_col=None, end_dot=True):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return ""
    stroke, mark_col = stroke or T["muted"], mark_col or T["text"]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1

    def sx(i):
        return 2 + i / (len(vals) - 1) * (IW - 6)

    def sy(v):
        return IH - 4 - (v - lo) / span * (IH - 8)
    pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(vals))
    o = [_mini_open(), f'<polyline points="{pts}" fill="none" stroke="{stroke}" stroke-width="1.25"/>']
    for i in marks:
        o.append(f'<line x1="{sx(i):.1f}" x2="{sx(i):.1f}" y1="2" y2="{IH-2}" stroke="{mark_col}" '
                 f'stroke-width="1" stroke-opacity="0.6"/>')
        o.append(f'<circle cx="{sx(i):.1f}" cy="{sy(vals[i]):.1f}" r="2.5" fill="{mark_col}"/>')
    if end_dot:
        o.append(f'<circle cx="{sx(len(vals)-1):.1f}" cy="{sy(vals[-1]):.1f}" r="2" fill="{stroke}"/>')
    o.append("</svg>")
    return "".join(o)


def stock_mini(closes, dates, n=24):
    rows = (closes or [])[-n:]
    idx = [i for i, (d, _c) in enumerate(rows) if d in set(dates)]
    return mini_spark([c for _d, c in rows], idx)


def deal_mini(upfront, milestones):
    if not upfront or not milestones:
        return ""
    total = upfront + milestones
    w1 = (IW - 4) * upfront / total
    return (_mini_open() + f'<rect x="2" y="9" width="{w1:.1f}" height="10" fill="{T["up"]}"/>'
            f'<rect x="{2 + w1 + 2:.1f}" y="9" width="{IW - 6 - w1:.1f}" height="10" '
            f'fill="{T["up"]}" fill-opacity="0.3"/>'
            + text(2, 27, "upfront", 9, T["muted"], mono=True)
            + text(IW - 2, 27, "milestones", 9, T["muted"], "end", mono=True) + "</svg>")


def slip_mini(old, new):
    a, b = _d(old), _d(new)
    if not a or not b:
        return ""
    y0, y1 = dt.date(a.year, 1, 1), dt.date(b.year + 1, 1, 1)
    span = (y1 - y0).days

    def sx(d):
        return 4 + (d - y0).days / span * (IW - 8)
    o = [_mini_open(), f'<line x1="4" x2="{IW-4}" y1="14" y2="14" stroke="{T["rule_strong"]}"/>',
         f'<line x1="{sx(a):.1f}" x2="{sx(b)-4:.1f}" y1="14" y2="14" stroke="{T["down"]}" stroke-width="2"/>',
         f'<circle cx="{sx(a):.1f}" cy="14" r="3.5" fill="{T["ground"]}" stroke="{T["muted"]}" stroke-width="1.25"/>',
         f'<circle cx="{sx(b):.1f}" cy="14" r="3.5" fill="{T["down"]}"/>']
    for yr in range(a.year, b.year + 1):
        o.append(text(sx(dt.date(yr, 1, 1)) + 1, 26, str(yr), 9, T["muted"], mono=True))
    o.append("</svg>")
    return "".join(o)


def countdown_mini(days, of=30):
    if days is None:
        return ""
    x = 4 + min(max(days, 0), of) / of * (IW - 8)
    return (_mini_open() + f'<line x1="4" x2="{IW-4}" y1="13" y2="13" stroke="{T["rule_strong"]}"/>'
            f'<line x1="4" x2="{x:.1f}" y1="13" y2="13" stroke="{T["flag"]}" stroke-width="2"/>'
            f'<circle cx="4" cy="13" r="2.5" fill="{T["text"]}"/>'
            f'<path d="M{x:.1f},8 L{x+5:.1f},13 L{x:.1f},18 L{x-5:.1f},13 Z" fill="{T["flag"]}"/>'
            + text(4, 26, "today", 9, T["muted"], mono=True)
            + text(IW - 4, 26, f"+{of}d", 9, T["muted"], "end", mono=True) + "</svg>")


def dates_mini(dates, a, b):
    da, db = _d(a), _d(b)
    if not dates or not da or not db or db <= da:
        return ""
    span = (db - da).days

    def sx(d):
        return 6 + (_d(d) - da).days / span * (IW - 12)
    o = [_mini_open(), f'<line x1="4" x2="{IW-4}" y1="16" y2="16" stroke="{T["rule_strong"]}"/>']
    seen = {}
    for d in dates:
        k = seen.get(d, 0)
        seen[d] = k + 1
        o.append(f'<circle cx="{sx(d):.1f}" cy="{16 - k * 7:.1f}" r="3" fill="{T["approved"]}"/>')
    o.append(text(4, 27, dday(a), 9, T["muted"], mono=True)
             + text(IW - 4, 27, dday(b), 9, T["muted"], "end", mono=True) + "</svg>")
    return "".join(o)


def _moves(pairs):
    return " · ".join(f"{t} {pc(m)}" if m is not None else f"{t} no close yet"
                      for t, m in pairs or [])


def week_item(p, it):
    """One ranked item as its parts: (tag, tickers, head, mini, figure, sub, figure class,
    detail rows, title). Pure."""
    cos = _cos(p)
    kind = it.get("kind")
    tickers = it.get("tickers") or []
    tk = " · ".join(tickers) if tickers != ["ALL"] else f"ALL {len(cos)}"
    mini, fig, sub, fcls, title = "", NO_DATA, "", "", ""
    rows = []
    head = it.get("head") or ""
    m = it.get("mini") or {}
    if m.get("type") == "deal":
        mini = deal_mini(m.get("upfront"), m.get("milestones"))
    elif m.get("type") == "spark":
        mini = mini_spark(m.get("values") or [], stroke=T["text"])
    elif m.get("type") == "stock":
        mini = stock_mini((p.get("closes") or {}).get(m.get("ticker")) or [], m.get("marks") or [])
    elif m.get("type") == "slip":
        mini = slip_mini(m.get("was"), m.get("now"))
    elif m.get("type") == "countdown":
        mini = countdown_mini(m.get("days"), m.get("of") or 30)
    elif m.get("type") == "dates":
        ds = m.get("dates") or []
        if ds:
            a = (_d(ds[0]) - dt.timedelta(days=3)).isoformat()
            b = (_d(ds[-1]) + dt.timedelta(days=3)).isoformat()
            mini = dates_mini(ds, a, b)
    if kind == "deal":
        if it.get("value_usd"):
            fig, sub = it.get("fig") or NO_DATA, dday(it.get("date"))
        else:
            fig, sub, fcls = "no value", dday(it.get("date")), "none"
        for k, v in it.get("rows") or []:
            if isinstance(v, list):
                rows.append((k if not str(k).startswith("Day move,") else f"Day move, {dday(str(k)[10:])}",
                             _moves(v)))
            elif v is None:
                rows.append((k, "none stated in the announcement or the filing"))
            else:
                rows.append((k, dlong(v) if _d(v) and len(str(v)) == 10 else v))
    elif kind == "market":
        head = head.split(" (")[0]
        fig, sub = sgn(it.get("fig_bp"), 0, "bp"), it.get("fig_sub") or ""
        for k, v in it.get("rows") or []:
            if k == "Level" and isinstance(v, dict):
                rows.append(("Level", f'{v["value"]*100:.2f}% on {dday(v.get("as_of"))}, '
                                      f'{sgn(v.get("change_bp"), 0, "bp")} since {dday(v.get("from"))}'
                             if v.get("value") is not None else NO_DATA))
            elif k == "Flags this week":
                rows.append((k, " · ".join(f'{dday(d)}' for d, _h in v)))
            elif isinstance(v, dict):
                rows.append((k, f'{sgn(v.get("change_bp"), 0, "bp")} since {dday(v.get("from"))}'))
        rate = ((p.get("focal") or {}).get("fair_value") or {}).get("rating") or {}
        if rate.get("cost_of_equity") is not None:
            rows.append((f"For {_focal(p)}", f'cost of equity {rate["cost_of_equity"]*100:.2f}%'))
    elif kind in ("readout", "readout2"):
        mv = it.get("fig_move")
        fig, sub = (pc(mv), dday(it.get("date"))) if mv is not None else ("no close yet", dday(it.get("date")))
        fcls = "" if mv is not None else "none"
        for k, v in it.get("rows") or []:
            rows.append((k, _moves(v) if isinstance(v, list) else v))
    elif kind == "approval":
        head = "Label expansions for " + _join_and(it.get("brands") or []) \
            if len(it.get("brands") or []) > 1 else f'Label expansion for {(it.get("brands") or [""])[0]}'
        fig, sub = str(it.get("fig_n")), "approved"
        for k, v in it.get("rows") or []:
            rows.append((k, dlong(v) if _d(v) and len(str(v)) == 10 else v))
    elif kind == "slip":
        s = it.get("slip") or {}
        head = f'{s.get("nct")} primary completion moves {s.get("days")} days to {dlong(s.get("now"))}'
        fig, sub = f'{s.get("days")}d', f'seen {dday(s.get("seen"))}'
        title = it.get("head_title") or ""
        rows = [("Study", f'{s.get("nct")}' + (f', {it["phase"]}' if it.get("phase") else "")),
                ("Was", dlong(s.get("was"))), ("Now", dlong(s.get("now")))]
        if title:
            rows.append(("Title", title))
    elif kind == "regulatory":
        e = it.get("event") or {}
        n = it.get("n_firm") or 1
        what = (e.get("title") or "").split(", ")
        name = e.get("short") or what[0]
        cond = what[1] if len(what) > 1 else ""
        cond = re.sub(r"^(?:the\s+)?(?:treatment|prevention)\s+of\s+(?:adult\s+|paediatric\s+|"
                      r"pediatric\s+)?(?:adults|patients|children|people)?\s*(?:with\s+)?",
                      "", cond, flags=re.I) or cond
        kindw = "PDUFA" if (e.get("type") or "").upper() == "PDUFA" else "FDA date"
        head = (f"{name} {kindw}" + (f" in {cond}" if cond else "")
                + (": the only firm FDA date in the next 30 days" if n == 1
                   else f": the first of {n} firm FDA dates in the next 30 days"))
        fig, sub = f'{it.get("days")}d', dday(e.get("date"))
        rows = [("Date", f'{dlong(e.get("date"))}, {e.get("confidence")}')]
    return {"tag": it.get("tag") or kind, "tk": tk, "head": head, "mini": mini, "fig": fig,
            "sub": sub, "fcls": fcls, "rows": rows, "title": title,
            "accent": ACCENT.get(kind, "var(--rule-strong)"),
            "focus": _focal(p) in tickers, "url": it.get("url"), "src": it.get("src") or ""}


def week_rows(p):
    """The week's material items as rows, ranked by kind and then size, each with a small
    chart and its lead figure. Every row opens in place (a native <details>)."""
    rows = []
    for i, it in enumerate(p.get("week_items") or [], 1):
        x = week_item(p, it)
        body = "".join(f'<div class="uv-kv"><span>{esc(k)}</span><span>{esc(v)}</span></div>'
                       for k, v in x["rows"])
        link = (f'<a class="uv-src-link" href="{esc(x["url"])}" target="_blank">source</a>'
                if x["url"] else "")
        cls = "uv-wm" + (" me" if x["focus"] else "")
        tip = f' title="{esc(x["title"])}"' if x["title"] else ""
        rows.append(
            f'<details class="{cls}" style="--accent:{x["accent"]}"><summary{tip}>'
            f'<span class="n">{i}</span><span class="tag">{esc(x["tag"])}</span>'
            f'<span class="h"><span class="tk">{esc(x["tk"])}</span> {esc(x["head"])}</span>'
            f'<span class="ch">{x["mini"]}</span>'
            f'<span class="f {x["fcls"]}">{esc(x["fig"])}<small>{esc(x["sub"])}</small></span>'
            f'</summary><div class="uv-wm-body">{body}<div class="uv-wm-src">{esc(x["src"])}{link}</div>'
            f'</div></details>')
    return rows


def week_html(p):
    """The ranked rows in two columns, read down the first and then the second, so eight
    items sit in four rows. An opened row pushes only its own column."""
    rows = week_rows(p)
    if not rows:
        return '<div class="uv-empty">Nothing material across the group in the last seven days.</div>'
    half = (len(rows) + 1) // 2
    return (f'<div class="uv-wk2"><div>{"".join(rows[:half])}</div>'
            f'<div>{"".join(rows[half:])}</div></div>')


def week_count(p):
    since = p.get("week_since")
    n = len(p.get("week_items") or [])
    return f'{dday(since)} to {dday(p.get("today"))} · {n} items' if since else f"{n} items"


# ---------------------------------------------------------- panel tab: rates and value
def spark(series, w=132, h=24, col=None, dot=True):
    vals = [v for _d, v in series or [] if v is not None]
    if len(vals) < 2:
        return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true"></svg>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = [(2 + i / (len(vals) - 1) * (w - 6), 2 + (hi - v) / span * (h - 4))
           for i, v in enumerate(vals)]
    d = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    out = [f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">',
           f'<path d="{d}" fill="none" stroke="{col or T["muted"]}" stroke-width="1.4"/>']
    if dot:
        out.append(f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.4" fill="{T["text"]}"/>')
    out.append("</svg>")
    return "".join(out)


def rates_html(p, focal=True):
    """Four rates with their quarter's path and 30-day change (uncoloured: a rising rate is
    value-negative, so direction colour would mislead), the reporting currencies with who
    reports in each, and what the discount rate means for the focal company's value.
    ``focal=False`` is the group's view: the rates and the currencies alone, the same
    whichever company is picked."""
    mk = p.get("markets") or {}
    f = _focal(p)
    rows = []
    for r in mk.get("rates") or []:
        own = " (ICE, shown not exported)" if r.get("restricted_to") else ""
        val = f'{r["value"]*100:.2f}%' if r.get("value") is not None else NO_DATA
        rows.append(f'<div class="uv-rt" title="{esc((r.get("description") or "") + own)}">'
                    f'<span class="n">{esc(r.get("label"))}</span>{spark(r.get("path"))}'
                    f'<span class="v">{val}</span>'
                    f'<span class="c">{esc(sgn(r.get("change_bp"), 0, "bp"))}</span>'
                    f'<span class="a">{esc(dday(r.get("as_of")))}</span></div>')
    fx = []
    for x in mk.get("fx") or []:
        who = ", ".join(x.get("reporters") or []) or "none of the group"
        ch = x.get("change_pct")
        cls = "" if ch is None else ("down" if ch < 0 else "up")
        rate = f'{x["rate"]:.4f}' if x.get("rate") is not None else NO_DATA
        fx.append(f'<div class="uv-fx" title="{esc(x.get("base"))}/USD, ECB reference rate '
                  f'{esc(dlong(x.get("as_of")))}"><span class="n">{esc(x.get("base"))}</span>'
                  f'<span class="v">{rate}</span><span class="c {cls}">{esc(pc(ch))}</span>'
                  f'<span class="w">{esc(who)}</span></div>')
    bm = []
    last = None
    for b in mk.get("benchmarks") or []:
        name = "XLV" if b.get("symbol") == "XLV" else "S&P 500"
        ch = b.get("change_pct")
        cls = "" if ch is None else ("down" if ch < 0 else "up")
        close = f'{b["close"]:,.2f}' if b.get("close") is not None else NO_DATA
        bm.append(f'<span><b>{esc(name)}</b> {close} <i class="{cls}">{esc(pc(ch))}</i></span>')
        last = b.get("as_of") or last
    days = mk.get("days") or 30
    left = ('<div><div class="uv-sub">Rates <span>line: the quarter; change: 30 days</span></div>'
            + ("".join(rows) or f'<div class="uv-empty">{NO_DATA}</div>')
            + f'<div class="uv-bm">{"".join(bm)} <em>{days} days to {esc(dday(last))}</em></div>'
            '</div>')
    mid_col = ('<div><div class="uv-sub">Currencies, 30 days <span>who reports in each</span></div>'
               + f'<div class="uv-fxg">{"".join(fx) or NO_DATA}</div></div>')

    def out_(box):
        return f'<div class="uv-rates">{left}{mid_col}<div>{box}</div></div>'

    if not focal:
        return f'<div class="uv-rates uv-rates2">{left}{mid_col}</div>'

    fv = (p.get("focal") or {}).get("fair_value") or {}
    rt = fv.get("rating") or {}
    c = _cos(p).get(f) or {}
    lo, mid, hi = rt.get("low_today"), rt.get("value_today"), rt.get("high_today")
    price = c.get("price")
    coe = rt.get("cost_of_equity")
    if None in (lo, mid, hi, coe):
        return out_(f'<div class="uv-azn"><div class="hd"><b>{esc(f)}</b>: the model\'s value '
                    f'at the discount rate a point either way has no free data on this read.'
                    f'</div></div>')
    pts = [lo, mid, hi] + ([price] if price is not None else [])
    a0 = math.floor(min(pts) * 0.95 / 10) * 10
    a1 = math.ceil(max(pts) * 1.05 / 10) * 10
    W = 400

    def X(v):
        return 10 + (v - a0) / (a1 - a0) * (W - 20)
    sv = [f'<svg width="{W}" height="46" viewBox="0 0 {W} 46" role="img" '
          f'aria-label="{esc(f)} value at the discount rate a point either way">',
          f'<rect x="{X(lo):.1f}" y="14" width="{X(hi)-X(lo):.1f}" height="8" '
          f'fill="{blend(T["up"], T["panel"], 0.45)}"/>',
          f'<line x1="{X(mid):.1f}" y1="10" x2="{X(mid):.1f}" y2="26" stroke="{T["text"]}" stroke-width="2"/>',
          text(X(lo), 40, f"{lo:.2f}", 10, T["text"], "middle", mono=True),
          text(X(hi), 40, f"{hi:.2f}", 10, T["text"], "middle", mono=True),
          text(X(mid) + 4, 8, f"{mid:.2f} model", 9.5, T["text"], mono=True),
          text(X(lo) - 4, 21.5, "+1 pt", 9, T["muted"], "end"),
          text(X(hi) + 4, 21.5, MINUS + "1 pt", 9, T["muted"])]
    if price is not None:
        sv.insert(3, f'<line x1="{X(price):.1f}" y1="6" x2="{X(price):.1f}" y2="30" '
                     f'stroke="{T["flag"]}" stroke-width="2"/>')
        # The price label takes the first spot that clears the three fixed labels: under
        # the bar either side of its tick, then over it.
        lab = f"price {price:.2f}"
        wd = lab_w(lab, 9.5, mono=True)
        fixed = [(X(lo) - lab_w(f"{lo:.2f}", 10, True) / 2, 31, X(lo) + lab_w(f"{lo:.2f}", 10, True) / 2, 42),
                 (X(hi) - lab_w(f"{hi:.2f}", 10, True) / 2, 31, X(hi) + lab_w(f"{hi:.2f}", 10, True) / 2, 42),
                 (X(mid) + 4, 0, X(mid) + 4 + lab_w(f"{mid:.2f} model", 9.5, True), 10)]
        spot = None
        for x_, y_, anc in ((X(price) - 4, 40, "end"), (X(price) + 4, 40, "start"),
                            (X(price) - 4, 8, "end"), (X(price) + 4, 8, "start")):
            rect = (x_ - wd if anc == "end" else x_, y_ - 9, x_ if anc == "end" else x_ + wd, y_ + 2)
            if rect[0] >= 0 and rect[2] <= W and not any(rects_hit(rect, r_, 3) for r_ in fixed):
                spot = (x_, y_, anc)
                break
        if spot:
            sv.append(text(spot[0], spot[1], lab, 9.5, T["flag"], spot[2], mono=True))
    sv.append("</svg>")
    beta = c.get("beta")
    nr = (p.get("focal") or {}).get("note_rate")
    nt = ""
    if nr:
        verb = "lower" if nr["change_pct"] < 0 else "higher"
        nt = (f'The stored note of {dday(nr.get("generated_at"))} measured the 10-year '
              f'{abs(nr["move_bp"]):.0f}bp {"above" if nr["move_bp"] > 0 else "below"} the '
              f'{nr["anchor"]*100:.2f}% last priced: {esc(f)} equity per share '
              f'{abs(nr["change_pct"])*100:.1f}% {verb}, {nr["before"]:.2f} to {nr["now"]:.2f}, '
              f'on {dday(nr["from"])} and {dday(nr["to"])} levels. Both predate today\'s {mid:.2f}. ')
    cur = c.get("currency")
    nt += (f'{esc(f)} reports in USD, so no currency row moves it directly.' if cur == "USD"
           else f'{esc(f)} reports in {esc(cur or NO_DATA)}, the currency row above moves its dollar value.')
    return out_(
        '<div class="uv-azn">'
        f'<div class="hd"><b>{esc(f)}</b> discounts at <b>{coe*100:.2f}%</b>'
        + (f' (beta {beta:.2f})' if beta is not None else "")
        + f'. A point on the discount rate either way moves today\'s value from '
          f'<b>{mid:.2f}</b> to <b>{lo:.2f}</b> or <b>{hi:.2f}</b>.</div>'
        f'{"".join(sv)}<div class="nt">{nt}</div></div>')


# --------------------------------------------- panel tab: Medicare and exclusivity
def col_chart(title, rows, focal, fmt, colour, tip, empty, W=680, H=152):
    """One measure across the cohort as columns, largest first: the value over each
    column, the ticker under it, the focal company washed. ``rows`` is
    [(ticker, value or None, why-empty)]; a company with no value prints ``empty`` (or its
    own why-empty word) where its column would stand and is never drawn as a zero."""
    rows = sorted(rows, key=lambda r: (r[1] is None, -(r[1] or 0), r[0]))
    n = max(len(rows), 1)
    x0, top, base = 4, 30, 136
    pitch = (W - 2 * x0) / n
    bw = min(pitch * 0.56, 22)
    vmax = max([r[1] for r in rows if r[1] is not None] or [1.0]) or 1.0
    o = [f'<svg class="uv-col" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="{esc(title)}">', text(x0, 10, title.upper(), 9, T["muted"], cls="cap")]
    o.append(f'<line x1="{x0}" y1="{base}" x2="{W - x0}" y2="{base}" stroke="{T["rule_strong"]}"/>')
    for i, (t, v, why) in enumerate(rows):
        cx = x0 + pitch * (i + 0.5)
        me = t == focal
        if me:
            o.append(f'<rect x="{cx - pitch / 2:.1f}" y="{top - 14}" width="{pitch:.1f}" '
                     f'height="{H - top + 14}" fill="{blend(T["up"], T["panel"], 0.14)}"/>'
                     f'<rect x="{cx - pitch / 2:.1f}" y="{top - 14}" width="{pitch:.1f}" height="2" '
                     f'fill="{T["up"]}"/>')
        if v is None:
            word = why or empty
            say = ("no drug selected for Medicare negotiation" if word == "none"
                   else NO_DATA)
            o.append(f'<g><title>{esc(t)}: {esc(say)}</title>'
                     + text(cx, base - 4, word, 9, T["muted"], "middle") + "</g>")
        else:
            h = max(v / vmax * (base - top), 0.5)
            o.append(f'<rect x="{cx - bw / 2:.1f}" y="{base - h:.1f}" width="{bw:.1f}" '
                     f'height="{h:.1f}" fill="{colour}" opacity="{1 if me else 0.55}">'
                     f'<title>{esc(tip(t, v))}</title></rect>')
            o.append(text(cx, base - h - 4, fmt(v), 9, T["text"], "middle",
                          600 if me else None, mono=True))
        o.append(text(cx, base + 12, t, 9.5 if me else 9, T["up"] if me else T["text"], "middle",
                      700 if me else 500, mono=True))
    o.append("</svg>")
    return "".join(o)


def exposure_html(p, focal_caption=True):
    """Every company's Medicare Part D gross spend on negotiated drugs as a share of
    revenue, and its share of product revenue losing exclusivity in five years: two column
    charts side by side, each ranked on its own measure, the focal company washed in
    both. ``focal_caption=False`` leaves the focal company's sentence off the caption, so
    the tab reads the same whichever company is picked."""
    cos = _cos(p)
    f = _focal(p)
    year = _loe_year(p)
    med, loe = [], []
    for t in _tickers(p):
        c = cos[t]
        ira = c.get("ira") or {}
        sel = bool(ira.get("selected"))
        med.append((t, ira.get("share"), None if sel else "none"))
        loe.append((t, (c.get("loe") or {}).get("share_5y"), "n/a"))
    left = col_chart(
        "Medicare Part D spend on negotiated drugs, share of revenue", med, f,
        lambda v: f"{v * 100:.1f}%", T["flag"],
        lambda t, v: f"{t} Part D gross spend {v * 100:.1f}% of revenue", "n/a")
    right = col_chart(
        (f"Exclusivity lost by {year}" if year else "Exclusivity lost in five years")
        + ", share of product revenue", loe, f, lambda v: f"{v * 100:.0f}%", T["orange"],
        lambda t, v: f"{t} {v * 100:.0f}% of tagged product revenue loses exclusivity by {year}",
        "n/a")
    ira = (cos.get(f) or {}).get("ira") or {}
    if not focal_caption:
        cap = ""
    elif ira.get("selected"):
        drugs = ", ".join(f'{s["brand"].title()} (price year {s["ipay"]}'
                          + (f', ceiling cut {s["ceiling_cut"]*100:.0f}%' if s.get("ceiling_cut") is not None else "")
                          + ")" for s in ira["selected"])
        shares = {t: ((cos[t].get("ira") or {}).get("share") or 0.0) for t in cos}
        most = 1 + sum(1 for t in cos if shares[t] > shares.get(f, 0.0))
        yrs = ira.get("spending_years") or []
        spend = ira.get("part_d_spending")
        cap = (f'<b>{esc(f)}:</b> {esc(drugs)}. '
               + (f'${spend/1e9:.2f}bn of {yrs[-1] if yrs else ""} Part D gross spend, '
                  if spend is not None else "")
               + (f'{ira["share"]*100:.1f}% of revenue, {ordinal(most)} most exposed of {len(cos)}. '
                  if ira.get("share") is not None else ""))
    else:
        cap = f'<b>{esc(f)}:</b> no drug CMS has selected belongs to this company. '
    none = [t for t, v, why in med if v is None and why == "none"]
    cap += ((f'None selected: {esc(", ".join(none))}. ' if none else "")
            + "Medicare Part D only, gross of rebates: spend sizes the franchise, it is not "
              "revenue at risk.")
    return (f'<div class="uv-exp"><div class="chart-mount">{left}</div>'
            f'<div class="chart-mount">{right}</div></div><div class="uv-cap">{cap}</div>')


# ------------------------------------------ panel tab: approvals and readouts (graft)
def lanes_svg(p, width=1408, focal_h=20, row_h=9.5, pin=True):
    """FDA approvals since 1 January by application type and dated catalysts ahead, one
    lane per company with the focal company first and taller. The focal company's signed
    results of the year are drawn on its lane. Lanes are a text line tall, so the whole
    cohort fits the tabbed panel: the captions and today's date run along the top, the
    months along the foot. ``pin=False`` is the group's view: every lane one height in
    the order of its count, the focal company washed where it falls and nothing drawn on
    its lane that another lane does not carry."""
    lanes = p.get("lanes") or {}
    a, b = _d(lanes.get("start")), _d(lanes.get("end"))
    today = _d(p.get("today"))
    cos = _cos(p)
    f = _focal(p)
    if not a or not b or not today or not cos:
        return ""
    L, R = 76, 104

    def sx(d):
        dd = _d(d) if not isinstance(d, dt.date) else d
        return L + (dd - a).days / (b - a).days * (width - L - R)
    events = [e for e in lanes.get("events") or []]
    count = {t: sum(1 for e in events if e["ticker"] == t) for t in cos}
    if pin:
        order = ([f] if f in cos else []) + sorted([t for t in cos if t != f],
                                                   key=lambda t: (-count[t], t))
    else:
        order = sorted(cos, key=lambda t: (-count[t], t))
        focal_h = row_h
    top = 14
    rh = {t: (focal_h if t == f else row_h) for t in order}
    ys, y = {}, top
    for t in order:
        ys[t] = y
        y += rh[t]
    height = y + 12
    o = [f'<svg class="uv-svg uv-lanes" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
         f'role="img" aria-label="FDA approvals since 1 January and dated catalysts ahead, one row per company">']
    xt = sx(today)
    o.append(f'<rect x="{xt:.1f}" y="{top-2}" width="{width-R-xt:.1f}" height="{y-top+2}" '
             f'fill="{T["panel"]}" fill-opacity="0.7"/>')
    x30 = sx(today + dt.timedelta(days=30))
    o.append(f'<rect x="{xt:.1f}" y="{top-2}" width="{x30-xt:.1f}" height="{y-top+2}" '
             f'fill="{T["flag"]}" fill-opacity="0.05"/>')
    m = dt.date(a.year, a.month, 1)
    while m < b:
        x = sx(m)
        o.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top-2}" y2="{y+2}" '
                 f'stroke="{T["rule_faint"]}"/>')
        lab = f"{m:%b}" + (f" {m:%y}" if m.month == 1 else "")
        o.append(text(x + 3, y + 10, lab, 9, T["muted"], mono=True))
        m = dt.date(m.year + (m.month // 12), m.month % 12 + 1, 1)
    o.append(text(L, 9, "FDA APPROVALS SINCE 1 JAN, BY APPLICATION TYPE", 9, T["muted"], cls="cap"))
    o.append(text(xt + 6, 9, f"DATED AHEAD, TO {b:%b %Y}".upper(), 9, T["muted"], cls="cap"))
    o.append(text(xt + 6 + lab_w(f"DATED AHEAD, TO {b:%b %Y}", 9) * 1.18 + 10, 9,
                  "next 30 days tinted", 9, T["flag"], mono=True))
    o.append(f'<line x1="{xt:.1f}" x2="{xt:.1f}" y1="{top-4}" y2="{y+3}" stroke="{T["text"]}" '
             f'stroke-width="1.25"/>')
    o.append(text(xt - 6, 9, f"today {dday(today.isoformat())}", 9.5, T["text"], "end", 600,
                  mono=True))
    appr = lanes.get("approvals") or []
    readouts = ((p.get("focal") or {}).get("readouts") or []) if pin else []
    maxc = max(count.values()) if count and max(count.values()) else 1
    for t in order:
        y0 = ys[t]
        h = rh[t]
        cy = y0 + h / 2
        o.append(f'<g data-ticker="{esc(t)}">')
        if t == f:
            o.append(f'<rect x="0" y="{y0}" width="{width}" height="{h}" fill="{T["up"]}" '
                     f'fill-opacity="0.10"/><rect x="0" y="{y0}" width="2" height="{h}" fill="{T["up"]}"/>')
        o.append(f'<line x1="{L}" x2="{width-R}" y1="{y0+h:.1f}" y2="{y0+h:.1f}" stroke="{T["rule_faint"]}"/>')
        o.append(text(8, cy + 3.5, t, 10.5 if t == f and pin else 9,
                      T["up"] if t == f else T["text"], weight=700 if t == f else 600, mono=True))
        n = count.get(t, 0)
        bw = 46 * n / maxc
        o.append(f'<rect x="{width-R+18}" y="{cy-2.5:.1f}" width="{bw:.1f}" height="5" '
                 f'fill="{T["p3"]}" fill-opacity="0.55"/>')
        o.append(text(width - R + 22 + bw, cy + 3.2, str(n), 9, T["text"], mono=True))
        lab_boxes = []
        ya = cy + (5 if t == f and pin else 0)
        mine = [x for x in appr if x["ticker"] == t and _d(x.get("date"))]
        row_marks = [sx(x["date"]) for x in mine]
        for ap in mine:
            x = sx(ap["date"])
            kind = ap.get("application_type")
            tip = (f"{t} {ap.get('label')}, {kind or 'application'} {ap.get('application_number') or ''}, "
                   f"approved {dlong(ap['date'])}")
            o.append(f"<g><title>{esc(tip)}</title>")
            if kind == "ANDA":
                o.append(f'<circle cx="{x:.1f}" cy="{ya:.1f}" r="2.6" fill="none" stroke="{T["muted"]}" '
                         f'stroke-width="1.2"/>')
            elif kind == "BLA":
                o.append(f'<rect x="{x-3.6:.1f}" y="{ya-3.6:.1f}" width="7.2" height="7.2" '
                         f'fill="{T["purple"]}"/>')
            else:
                o.append(f'<circle cx="{x:.1f}" cy="{ya:.1f}" r="3.8" fill="{T["orange"]}"/>')
            o.append("</g>")
            if kind != "ANDA" and ap.get("label"):
                lab = ap["label"].split(" (")[0]
                w_ = lab_w(lab, 9)
                bx = (x + 6, x + 6 + w_)
                ok = all(not (x < mx < bx[1] + 6) for mx in row_marks if abs(mx - x) > 0.5)
                if ok and all(bx[0] > q[1] + 4 or bx[1] < q[0] - 4 for q in lab_boxes) \
                        and bx[1] < xt - 2:
                    lab_boxes.append(bx)
                    o.append(text(x + 6, ya + 3, lab, 9, T["text"] if t == f else T["muted"]))
        if t == f and pin:
            yr = cy - 5
            rb = []
            rmarks = [sx(r["date"]) for r in readouts if _d(r.get("date"))]
            for rd in sorted([r for r in readouts if _d(r.get("date"))], key=lambda r: r["date"]):
                x = sx(rd["date"])
                pos = rd.get("outcome") == "positive"
                q = (rd.get("quote") or "")[:160]
                tip = (f"{rd.get('drug')}, Phase {rd.get('phase')}, {rd.get('outcome')}, "
                       f"{dlong(rd['date'])}: {q}")
                path = (f"M{x-4:.1f},{yr+3:.1f} L{x+4:.1f},{yr+3:.1f} L{x:.1f},{yr-4:.1f} Z" if pos
                        else f"M{x-4:.1f},{yr-3:.1f} L{x+4:.1f},{yr-3:.1f} L{x:.1f},{yr+4:.1f} Z")
                o.append(f'<g><title>{esc(tip)}</title><path d="{path}" '
                         f'fill="{T["up"] if pos else T["down"]}"/></g>')
                drug = rd.get("drug") or ""
                lab = drug.split("(")[1].rstrip(")") if "(" in drug else drug
                w_ = lab_w(lab, 9)
                ok = all(not (x + 4 < mx < x + 8 + w_) for mx in rmarks if abs(mx - x) > 0.5)
                if ok and all(x + 6 > q_[1] + 4 or x + 6 + w_ < q_[0] - 4 for q_ in rb) \
                        and x + 6 + w_ < xt - 2:
                    rb.append((x + 6, x + 6 + w_))
                    o.append(text(x + 6, yr + 3, lab, 9, T["text"]))
        for e in [e for e in events if e["ticker"] == t]:
            tip = f"{t} {(e.get('title') or '')[:120]} · {e['date']} · {e.get('confidence')}"
            yy = cy + (4 if t == f and pin else 0)
            big = e.get("phase") == "p3"
            if e.get("regulatory") and not e.get("month"):
                x = sx(e["date"])
                o.append(f'<g><title>{esc(tip)}</title><path d="M{x:.1f},{yy-5:.1f} L{x+5:.1f},{yy:.1f} '
                         f'L{x:.1f},{yy+5:.1f} L{x-5:.1f},{yy:.1f} Z" fill="{T["filed"]}"/></g>')
            elif e.get("month"):
                m0 = _d(e["date"] + "-01")
                m1 = dt.date(m0.year + (m0.month // 12), m0.month % 12 + 1, 1)
                xa_, xb_ = sx(max(m0, today)), sx(min(m1, b))
                o.append(f'<g><title>{esc(tip)}</title><rect x="{xa_:.1f}" y="{yy-1.5:.1f}" '
                         f'width="{max(xb_-xa_-4, 2):.1f}" height="3" '
                         f'fill="{T["p3"] if big else T["p2"]}" fill-opacity="0.6"/></g>')
            else:
                x = sx(e["date"])
                o.append(f'<g><title>{esc(tip)}</title><circle cx="{x:.1f}" cy="{yy:.1f}" '
                         f'r="{3.4 if big else 2.4}" fill="none" stroke="{T["p3"] if big else T["p2"]}" '
                         f'stroke-width="{1.4 if big else 1.1}"/></g>')
        o.append("</g>")
    o.append(text(width - R + 18, 9, f"{(b.year - today.year) * 12 + b.month - today.month} months",
                  9, T["muted"], mono=True))
    o.append("</svg>")
    return "".join(o)


def lanes_legend(p, pin=True):
    f = _focal(p)
    mine = (f'<span><i class="tri" style="background:var(--up)"></i>{esc(f)} Phase 3 positive</span>'
            '<span><i class="tri dn" style="background:var(--down)"></i>negative</span>'
            if pin else "")
    return ('<div class="uv-leg uv-leg-lanes">'
            '<span><i style="background:var(--orange-book)"></i>NDA, small molecule</span>'
            '<span><i class="sq" style="background:var(--purple-book)"></i>BLA, biologic</span>'
            '<span><i class="ring" style="border-color:var(--muted)"></i>ANDA, generic</span>'
            + mine +
            '<span><i class="ring" style="border-color:var(--phase-3)"></i>readout, Phase 3 (smaller: Phase 2)</span>'
            '<span><i class="bar" style="background:var(--phase-3)"></i>month only</span>'
            '<span><i class="dia" style="background:var(--phase-filed)"></i>firm FDA date</span></div>')


def lanes_counts(p):
    lanes = p.get("lanes") or {}
    return (f'{len(lanes.get("approvals") or [])} approvals · {len(lanes.get("events") or [])} '
            f'dated to {dday(lanes.get("end"))}')


# ------------------------------------------- panel tab: prices, 12 months (graft)
def prices_html(p, cols=9):
    """A year of closes per company, indexed to 100 on one scale with XLV's total return
    dashed, sorted by the move against XLV. The focal panel is washed."""
    cos = _cos(p)
    f = _focal(p)
    end = p.get("price_date")
    endd = _d(end)
    if not endd:
        return ""
    start = (endd - dt.timedelta(days=365)).isoformat()
    bench = [(d, v) for d, v in p.get("benchmark") or [] if start <= d <= end]
    series = {}
    for t in cos:
        rows = [(d, c) for d, c in (p.get("closes") or {}).get(t) or [] if start <= d <= end]
        if len(rows) >= 2 and rows[0][1]:
            series[t] = [(d, c / rows[0][1] * 100) for d, c in rows]
    xs = [(d, v / bench[0][1] * 100) for d, v in bench] if bench and bench[0][1] else []
    allv = [v for s in series.values() for _d_, v in s] + [v for _d_, v in xs]
    if not allv:
        return ""
    lo, hi = math.floor(min(allv) / 10) * 10, math.ceil(max(allv) / 10) * 10
    rel = _rel(p, "1y")
    order = sorted([t for t in series if t in rel], key=lambda t: -rel[t]) + \
        [t for t in series if t not in rel]
    W, Hh = 140, 52

    def path(pts):
        n = len(pts)
        keep = [pts[i] for i in range(0, n, 3)]
        if keep[-1] != pts[-1]:
            keep.append(pts[-1])

        def sx_(i):
            return 2 + i / max(len(keep) - 1, 1) * (W - 6)

        def sy_(v):
            return Hh - 3 - (v - lo) / (hi - lo or 1) * (Hh - 6)
        return " ".join(f"{sx_(i):.1f},{sy_(v):.1f}" for i, (_d_, v) in enumerate(keep)), \
            sx_(len(keep) - 1), sy_(keep[-1][1]), sy_
    xp = path(xs)[0] if len(xs) >= 2 else ""
    cells = []
    for i, t in enumerate(order, 1):
        pts, ex, ey, sy = path(series[t])
        own = ((cos[t].get("rel") or {}).get("1y") or {}).get("own")
        chg = own if own is not None else series[t][-1][1] / 100 - 1
        col = T["up"] if chg > 0 else T["down"]
        r = rel.get(t)
        tip = (f"{t} {cos[t].get('name') or ''}: {pc(chg)} over the year to {dlong(end)}, "
               + (f"{sgn(r, 1, ' points')} against XLV, {ordinal(i)} of {len(rel)} against XLV"
                  if r is not None else "no XLV comparison on file"))
        svg = (f'<svg viewBox="0 0 {W} {Hh}" width="{W}" height="{Hh}" aria-hidden="true">'
               f'<line x1="2" x2="{W-2}" y1="{sy(100):.1f}" y2="{sy(100):.1f}" stroke="{T["rule_strong"]}"/>'
               + (f'<polyline points="{xp}" fill="none" stroke="{T["muted"]}" stroke-width="1" '
                  f'stroke-dasharray="2 2"/>' if xp else "")
               + f'<polyline points="{pts}" fill="none" stroke="{T["text"] if t == f else col}" '
               f'stroke-width="{1.6 if t == f else 1.25}"/>'
               f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="2.2" fill="{col}"/></svg>')
        cls = "uv-sm" + (" me" if t == f else "")
        tone = "up" if chg > 0 else "down"
        foot = (f'<span>{ordinal(i)}</span><span>{esc(sgn(r, 1, " pts"))} vs XLV</span>'
                if r is not None else f'<span>{NO_DATA}</span>')
        cells.append(f'<div class="{cls}" title="{esc(tip)}"><div class="uv-sm-h">'
                     f'<span class="tk">{esc(t)}</span><span class="v {tone}">{esc(pc(chg))}</span></div>'
                     f'{svg}<div class="uv-sm-f">{foot}</div></div>')
    return f'<div class="uv-sms" style="--sm-cols:{cols}">{"".join(cells)}</div>'


def prices_basis(p):
    """The date the panels are indexed on: the first close inside the year, which is the
    first session on or after the day a year back (5 Oct 2025 was a Sunday; the panels
    start on the 6th)."""
    end = p.get("price_date")
    endd = _d(end)
    if not endd:
        return "indexed to 100"
    start = (endd - dt.timedelta(days=365)).isoformat()
    first = next((d for d, v in p.get("benchmark") or [] if start <= d <= end and v), None)
    return f"indexed to 100 on {dlong(first or start)}"


def prices_count(p):
    bench = p.get("benchmark") or []
    end = p.get("price_date")
    endd = _d(end)
    if not endd or not bench:
        return "sorted by move against XLV"
    start = (endd - dt.timedelta(days=365)).isoformat()
    b = [v for d, v in bench if start <= d <= end]
    if len(b) < 2 or not b[0]:
        return "sorted by move against XLV"
    return f"sorted by move against XLV ({pc(b[-1] / b[0] - 1)}, dashed)"


# ------------------------------------------------------ panel tab: policy calendar
LANE_TIERS = (-1, -2, 1)
LANE_TIER_COST = {-1: 0.0, -2: 1.0, 1: 1.5}


def place_lane_labels(marks, y, reserved=(), x_min=0.0, x_max=1e9, size=9, budget=40000):
    """Labels for the marks on one policy lane: each on a tier above the lane (-1, then
    -2) or below it (1), starting at its mark or ending at it.

    A label is drawn with a leader from its mark, so two rules hold beside "no two labels
    overlap": a label never sits over another mark whose leader runs up (or down) through
    its tier, and a leader never runs through a nearer label. A greedy pass broke the
    second and paired the June proposed rule's square with the July draft guidance's
    label. The marks are few, so the placement is searched: the lowest total cost (near
    tier, then far, then below; a label after its mark before one ending at it), a mark
    left unlabelled only when nothing fits. ``marks`` is [(x, label)]; returns
    [(x, label, anchor, tier, baseline y)] for the marks placed. Pure."""
    tiers = {-1: y - 13, -2: y - 26, 1: y + 24}
    marks = sorted(marks, key=lambda m: m[0])
    opts = []
    for xx, lab in marks:
        wd = lab_w(lab, size)
        mine = []
        for tier in LANE_TIERS:
            yy = tiers[tier]
            for anc in ("start", "end"):
                x0 = xx + 2 if anc == "start" else xx + 3 - wd
                rect = (x0, yy - size, x0 + wd, yy + 2)
                if rect[0] < x_min or rect[2] > x_max:
                    continue
                if any(labels_hit(rect, r) for r in reserved):
                    continue
                mine.append((LANE_TIER_COST[tier] + (0.2 if anc == "end" else 0.0),
                             tier, anc, yy, rect))
        mine.sort(key=lambda o_: o_[0])
        opts.append(mine)
    unplaced = 100.0

    def clash(i, a, j, b):
        if labels_hit(a[4], b[4]):
            return True
        for (k, ka), (m, mb) in (((i, a), (j, b)), ((j, b), (i, a))):
            # m's leader runs through k's tier when m is on the same side and further out.
            if ka[1] * mb[1] > 0 and abs(mb[1]) > abs(ka[1]):
                if ka[4][0] - 4 <= marks[m][0] <= ka[4][2] + 4:
                    return True
        return False

    best = {"cost": float("inf"), "pick": [None] * len(marks)}
    floor = [min([o_[0] for o_ in mine] + [unplaced]) for mine in opts]
    rest = [sum(floor[i:]) for i in range(len(marks) + 1)]
    nodes = [0]

    def search(i, pick, cost):
        nodes[0] += 1
        if cost + rest[i] >= best["cost"] or nodes[0] > budget:
            return
        if i == len(marks):
            best["cost"], best["pick"] = cost, list(pick)
            return
        for o_ in opts[i]:
            if all(pick[j] is None or not clash(i, o_, j, pick[j]) for j in range(i)):
                pick.append(o_)
                search(i + 1, pick, cost + o_[0])
                pick.pop()
        pick.append(None)
        search(i + 1, pick, cost + unplaced)
        pick.pop()

    search(0, [], 0.0)
    return [(marks[i][0], marks[i][1], o_[2], o_[1], o_[3])
            for i, o_ in enumerate(best["pick"]) if o_ is not None]


def policy_svg(p, W=573):
    """Both policy lanes on this year's axis: a rule filled, a proposed rule open, a
    notice a dot, comment windows as bars with the open one bright and counted down."""
    pol = p.get("policy") or {}
    items = pol.get("items") or []
    today = _d(p.get("today"))
    if not today:
        return ""
    L, Rr = 112, 14
    d0, d1 = dt.date(today.year, 1, 1), dt.date(today.year, 12, 31)
    span = (d1 - d0).days

    def X(iso):
        d = _d(iso)
        return L + max(min((d - d0).days, span), 0) / span * (W - L - Rr)
    lanes = {"cms_ira": 64, "bis_pharma": 134}
    H = 186
    o = [f'<svg class="uv-pol" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="Policy documents by date">']
    for m in range(1, 13):
        iso = f"{today.year}-{m:02d}-01"
        o.append(f'<line x1="{X(iso):.1f}" y1="14" x2="{X(iso):.1f}" y2="{H-18}" '
                 f'stroke="{T["rule_faint"]}"/>')
        o.append(text(X(iso) + 2, H - 6, f"{dt.date(today.year, m, 1):%b}", 9, T["muted"], mono=True))
    tx = X(today.isoformat())
    o.append(f'<line x1="{tx:.1f}" y1="10" x2="{tx:.1f}" y2="{H-18}" stroke="{T["rule_strong"]}" '
             f'stroke-width="1.2"/>')
    o.append(text(tx, 8, "today", 9, T["muted"], "middle"))
    for lane, (a_, b_) in {"cms_ira": ("Medicare", "negotiation"),
                           "bis_pharma": ("Section 232", "tariffs")}.items():
        y = lanes[lane]
        o.append(f'<line x1="{L}" y1="{y}" x2="{W-Rr}" y2="{y}" stroke="{T["rule"]}"/>')
        o.append(text(0, y - 2, a_, 10.5, T["text"], weight=600))
        o.append(text(0, y + 11, b_, 10.5, T["text"], weight=600))
        early = [i for i in items if i.get("lane") == lane and (i.get("published_on") or "") < d0.isoformat()]
        if early:
            # The read spans two years back, so the earlier documents are counted by
            # the years they carry, not assumed to fall in last year.
            years = sorted({i["published_on"][:4] for i in early})
            when = years[0] if len(years) == 1 else f"{years[0]} to {years[-1]}"
            o.append(text(0, y + 24, f"{len(early)} in {when}", 9, T["muted"], mono=True))
    labels = {"cms_ira": [], "bis_pharma": []}
    reserved = {"cms_ira": [], "bis_pharma": []}
    for it in sorted(items, key=lambda i: i.get("published_on") or ""):
        if it.get("lane") not in lanes or not _d(it.get("published_on")):
            continue
        y = lanes[it["lane"]]
        close = it.get("comments_close_on")
        open_now = bool(close and close >= today.isoformat())
        if close and close >= d0.isoformat():
            xa, xc = X(max(it["published_on"], d0.isoformat())), X(close)
            o.append(f'<rect x="{xa:.1f}" y="{y+6}" width="{max(xc-xa, 1):.1f}" height="3" '
                     f'fill="{T["flag"]}" opacity="{1 if open_now else 0.35}"/>')
            if open_now:
                days = (_d(close) - today).days
                lab = f"comments close {dday(close)}, {days} days"
                o.append(text(xc + 3, y + 22, lab, 9, T["flag"], "end", 600))
                reserved[it["lane"]].append((xc + 3 - lab_w(lab, 9) - 4, y + 12, xc + 3, y + 24))
                o.append(f'<line x1="{xc:.1f}" y1="{y+9}" x2="{xc:.1f}" y2="{y+13}" stroke="{T["flag"]}"/>')
        if it["published_on"] < d0.isoformat():
            continue
        x = X(it["published_on"])
        tip = (f'{dlong(it["published_on"])}, {it.get("doc_type")} {it.get("docket_id") or ""}: '
               f'{it.get("title")}' + (f'; comments close {dlong(close)}' if close else ""))
        dtp = it.get("doc_type")
        if dtp == "Rule":
            o.append(f'<rect x="{x-4:.1f}" y="{y-4}" width="8" height="8" fill="{T["text"]}">'
                     f'<title>{esc(tip)}</title></rect>')
        elif dtp == "Proposed Rule":
            o.append(f'<rect x="{x-3.5:.1f}" y="{y-3.5}" width="7" height="7" fill="{T["ground"]}" '
                     f'stroke="{T["text"]}" stroke-width="1.4"><title>{esc(tip)}</title></rect>')
        else:
            o.append(f'<circle cx="{x:.1f}" cy="{y}" r="4" fill="{T["muted"]}" stroke="{T["ground"]}" '
                     f'stroke-width="1"><title>{esc(tip)}</title></circle>')
        if it.get("short"):
            labels[it["lane"]].append((x, it["short"]))
    # Labels: tiers above and below each lane, placed so that no leader runs through
    # another document's label. Leaders first, then the labels with a halo.
    for lane, marks in labels.items():
        y = lanes[lane]
        placed = place_lane_labels(marks, y, reserved[lane], L - 4, W - 2)
        for xx, lab, anc, tier, yy in placed:
            y_end = yy + 3 if tier < 0 else yy - 9
            o.append(f'<line x1="{xx:.1f}" y1="{y + (-5 if tier < 0 else 10)}" x2="{xx:.1f}" '
                     f'y2="{y_end}" stroke="{T["rule_strong"]}"/>')
        for xx, lab, anc, tier, yy in placed:
            o.append(text(xx + 2 if anc == "start" else xx + 3, yy, lab, 9, T["text"], anc,
                          opacity=0.88, cls="halo"))
    o.append("</svg>")
    return "".join(o)


def policy_html(p, W=840):
    pol = p.get("policy") or {}
    today = p.get("today") or ""
    rows = []
    for e in sorted(pol.get("events") or [], key=lambda e: e.get("date") or "", reverse=True):
        drug = (e.get("drug") or "").title() or "a drug"
        if e.get("kind") == "selected":
            txt = f"CMS selects {drug} for Medicare negotiation" + (
                f", price year {e['year']}" if e.get("year") else "")
        else:
            txt = f"CMS deselects {drug} from Medicare negotiation, for review"
        rows.append(f'<div class="uv-am k-policy"><span class="d">{esc(dday(e.get("date")))}</span>'
                    f'<span class="h"><b class="tk">{esc(e.get("ticker"))}</b> {esc(txt)}</span></div>')
    events = ('<div class="uv-sub">Company events <span>from the policy feed, 30 days</span></div>'
              + ("".join(rows) or '<div class="uv-am"><span class="d">·</span>'
                                  '<span class="h">No company selected or dropped in 30 days</span></div>'))
    opened = [i for i in pol.get("items") or [] if (i.get("comments_close_on") or "") >= today]
    foot = "".join(
        f'<b>Open for comment:</b> {esc(i.get("docket_id") or i.get("document_number"))}, '
        f'{esc(i.get("title"))}, closes {esc(dlong(i.get("comments_close_on")))}. ' for i in opened)
    foot += ("Section 232: which company imports what has no free data, so no company is "
             "ranked on tariff exposure.")
    return (f'<div class="uv-polg"><div class="chart-mount">{policy_svg(p, W)}</div>'
            f'<div>{events}<div class="uv-pol-foot">{foot}</div></div></div>')


def policy_count(p):
    items = (p.get("policy") or {}).get("items") or []
    return f"{len(items)} documents in 24 months"


# --------------------------------------------------------------------- the notes byline
def notes_text(p):
    ev = p.get("events") or []
    firm = [e for e in ev if e.get("firm")]
    firm_txt = ("; ".join(f"{e['ticker']} {e.get('short') or ''}, {dlong(e['date'])}" for e in firm)
                if firm else "none")
    left = p.get("events_left_off") or 0
    return (f"Prices to the {dlong(p.get('price_date'))} close. The week is ranked by kind, "
            "then size, and never by the company picked: deals with a stated value, the rate "
            "move, Phase 3 results, other deals, Phase 2 results, approvals, slips, then what "
            "is due. Words in quotes, and the headlines marked as the source's, are the "
            "source's own. Cheap to expensive is the model's 12-month upside to the close. "
            "Moves against XLV use XLV's total "
            "return and each company's price, so they understate a company by its own dividend. "
            f"Firm dates on the board: {firm_txt}; every other date is a registry estimate. "
            + (f"{left} items dated only to a month that runs past the 90 days are left off. " if left else "")
            + "Medians are true medians of the companies that have the figure.")


# --------------------------------------------------------------------- the company dialog
LENS_NAMES = {"sotp_wacc": "Sum of the parts, rate ±1 pt",
              "sotp_fade": "Sum of the parts, growth fade",
              "sotp_guidance": "Sum of the parts, guidance",
              "pe_ntm": "P/E, next 12 months", "ev_sales": "EV / revenue",
              "precedents": "Takeover precedents", "targets": "Analyst targets",
              "range": "52-week closes"}
PILLARS = (("growth", "Growth"), ("profitability", "Profitability"),
           ("balance_sheet", "Balance sheet"), ("pipeline", "Pipeline"),
           ("durability", "Durability"), ("value", "Value"), ("momentum", "Momentum"))


def nice_step(span, max_ticks=7):
    """The smallest round tick step that puts no more than ``max_ticks`` on ``span``."""
    steps = sorted(b * m for b in (1, 2, 2.5, 5) for m in (0.1, 1, 10, 100, 1000, 10000))
    return next((s for s in steps if span / s <= max_ticks), steps[-1])


def lens_name(lens):
    """A lens's row label: the house name where the key has one, else the lens's own
    words, capitalised and cut to fit the label column."""
    name = LENS_NAMES.get(lens.get("key"))
    if name:
        return name
    words = (lens.get("lens") or "").strip()
    if words.lower().startswith("the "):
        words = words[4:]
    words = words[:1].upper() + words[1:]
    return words if len(words) <= 30 else words[:29].rstrip(" ,") + "…"


def football_svg(p):
    f = _focal(p)
    lenses = [l for l in ((p.get("focal") or {}).get("fair_value") or {}).get("lenses") or []
              if l.get("low") is not None and l.get("high") is not None]
    price = (_cos(p).get(f) or {}).get("price")
    if not lenses:
        return ""
    W, L, RH, top = 516, 176, 22, 8
    H = top + RH * len(lenses) + 22
    vals = [v for l in lenses for v in (l["low"], l["high"])] + ([price] if price else [])
    lo_v, hi_v = min(vals), max(vals)
    step = nice_step((hi_v - lo_v) or abs(hi_v) or 1.0)
    # Room left of the lowest bar for its own label.
    a0 = math.floor((lo_v - 0.03 * ((hi_v - lo_v) or step)) / step) * step
    a1 = math.ceil(hi_v / step) * step
    a1 = a1 if a1 > a0 else a0 + step

    def X(v):
        return L + (v - a0) / (a1 - a0) * (W - L - 28)
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Value lenses">']
    v = a0
    while v <= a1 + 1e-9:
        o.append(f'<line x1="{X(v):.1f}" y1="{top}" x2="{X(v):.1f}" y2="{H-18}" stroke="{T["rule_faint"]}"/>')
        o.append(text(X(v), H - 5, f"{v:,.0f}" if step >= 1 else f"{v:,.1f}", 9, T["muted"],
                      "middle", mono=True))
        v += step
    for i, l in enumerate(lenses):
        y = top + i * RH
        mid = y + RH / 2
        model = (l.get("key") or "").startswith("sotp")
        col = T["up"] if model else (T["muted"] if l.get("key") == "range" else T["rule_strong"])
        o.append(text(0, mid + 3.5, lens_name(l), 10.5, T["text"] if model else T["muted"]))
        o.append(f'<rect x="{X(l["low"]):.1f}" y="{mid-5}" width="{max(X(l["high"])-X(l["low"]), 1):.1f}" '
                 f'height="10" fill="{blend(col, T["ground"], 0.7 if model else 0.9)}">'
                 f'<title>{esc(l.get("lens"))}: {l["low"]:.2f} to {l["high"]:.2f}'
                 + (f', mid {l["mid"]:.2f}' if l.get("mid") is not None else "")
                 + f'. {esc(l.get("basis"))}</title></rect>')
        if l.get("mid") is not None:
            o.append(f'<line x1="{X(l["mid"]):.1f}" y1="{mid-7}" x2="{X(l["mid"]):.1f}" y2="{mid+7}" '
                     f'stroke="{T["text"]}" stroke-width="1.6"/>')
        o.append(text(X(l["low"]) - 4, mid + 3.5, f'{l["low"]:.0f}', 9, T["muted"], "end", mono=True))
        o.append(text(X(l["high"]) + 4, mid + 3.5, f'{l["high"]:.0f}', 9, T["muted"], mono=True))
    if price:
        o.append(f'<line x1="{X(price):.1f}" y1="{top-4}" x2="{X(price):.1f}" y2="{H-18}" '
                 f'stroke="{T["flag"]}" stroke-width="1.5" stroke-dasharray="3 3"/>')
    o.append("</svg>")
    return "".join(o)


def vs_xlv_svg(p):
    """The focal company against XLV over the year, both indexed to 100 on their first
    shared close."""
    f = _focal(p)
    win = (p.get("windows") or {}).get("1y") or {}
    first, last = win.get("first"), win.get("last")
    closes = (p.get("closes") or {}).get(f) or []
    xl = dict((d, v) for d, v in p.get("benchmark") or [])
    if not first or not last:
        return ""
    pts = [(d, v) for d, v in closes if first <= d <= last and d in xl and xl[d]]
    if len(pts) < 2:
        return ""
    a0, x0 = pts[0][1], xl[pts[0][0]]
    sa = [v / a0 * 100 for _d_, v in pts]
    sx_ = [xl[d] / x0 * 100 for d, _v in pts]
    W, H, L, Rr, top, bot = 516, 136, 34, 72, 8, 20
    lo = math.floor(min(sa + sx_) / 10) * 10
    hi = math.ceil(max(sa + sx_) / 10) * 10

    def X(i):
        return L + i / (len(pts) - 1) * (W - L - Rr)

    def Y(v):
        return top + (hi - v) / (hi - lo or 1) * (H - top - bot)
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="{esc(f)} against XLV, indexed">']
    v = lo
    while v <= hi:
        o.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{W-Rr}" y2="{Y(v):.1f}" '
                 f'stroke="{T["rule_strong"] if v == 100 else T["rule_faint"]}"/>')
        o.append(text(L - 5, Y(v) + 3.5, str(v), 9, T["muted"], "end", mono=True))
        v += 10
    me = ((_cos(p).get(f) or {}).get("rel") or {}).get("1y") or {}
    ends = []
    for s, col, lab, val in ((sx_, T["muted"], "XLV", win.get("xlv")),
                             (sa, T["up"], f, me.get("own"))):
        d = "M" + " L".join(f"{X(i):.1f} {Y(v_):.1f}" for i, v_ in enumerate(s))
        o.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{2 if lab == f else 1.5}"/>')
        ends.append([Y(s[-1]) + 3.5, lab, val])
    if abs(ends[0][0] - ends[1][0]) < 12:
        ends[0][0] -= 6
        ends[1][0] += 6
    for yy, lab, val in ends:
        o.append(text(W - Rr + 6, yy, f"{lab} {pc(val)}", 10, T["text"], mono=True,
                      weight=600 if lab == f else 400))
    o.append(text(L, H - 4, dlong(first), 9, T["muted"], mono=True))
    o.append(text(W - Rr, H - 4, dlong(last), 9, T["muted"], "end", mono=True))
    o.append("</svg>")
    return "".join(o)


def pillars_svg(p):
    f = _focal(p)
    pil = (p.get("focal") or {}).get("pillars") or {}
    meds = (p.get("cohort") or {}).get("medians") or {}
    score = ((_cos(p).get(f) or {}).get("score") or {}).get("score")
    rows = [(k, lab) for k, lab in PILLARS if k in pil]
    if not rows:
        return ""
    W, L, RH = 516, 104, 20
    split = sum(1 for k, _l in rows if k not in ("value", "momentum"))
    H = RH * len(rows) + 22 + (10 if split < len(rows) else 0)
    bx1 = 360

    def X(v):
        return L + v / 100 * (bx1 - L)
    o = [f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Pillar scores">']
    for i, (k, lab) in enumerate(rows):
        kept = k in ("value", "momentum")
        y = i * RH + (10 if kept else 0)
        mid = y + RH / 2
        s, med = (pil.get(k) or {}).get("score"), meds.get(k)
        o.append(text(0, mid + 3.5, lab, 10.5, T["muted"] if kept else T["text"]))
        o.append(f'<rect x="{L}" y="{mid-4}" width="{bx1-L}" height="8" fill="{T["rule_faint"]}"/>')
        if s is None:
            o.append(text(bx1 + 8, mid + 3.5, NO_DATA, 9.5, T["muted"]))
            continue
        col = T["up"] if med is not None and s > med else (
            T["down"] if med is not None and s < med else T["text"])
        o.append(f'<rect x="{L}" y="{mid-4}" width="{X(s)-L:.1f}" height="8" fill="{col}" '
                 f'opacity="{0.6 if kept else 1}"/>')
        if med is not None:
            o.append(f'<line x1="{X(med):.1f}" y1="{mid-7}" x2="{X(med):.1f}" y2="{mid+7}" '
                     f'stroke="{T["text"]}" stroke-width="1.4"/>')
        o.append(text(bx1 + 8, mid + 3.5, f"{s}", 10.5, T["text"], weight=600, mono=True))
        if med is not None:
            o.append(text(bx1 + 30, mid + 3.5, f"median {med}", 9.5, T["muted"], mono=True))
    if split < len(rows):
        o.append(f'<line x1="0" y1="{split*RH+5}" x2="{W}" y2="{split*RH+5}" stroke="{T["rule"]}"/>')
        o.append(text(0, H - 2, "Value and momentum are kept out of the score"
                      + (f" of {score}." if score is not None else "."), 9.5, T["muted"]))
    o.append("</svg>")
    return "".join(o)


def next90_html(p):
    rows = sorted((p.get("focal") or {}).get("events") or [],
                  key=lambda e: e["date"] if not e.get("month") else e["date"] + "-99")
    out = []
    for e in rows:
        ph = e.get("phase")
        stage = {"p3": "Phase 3", "p2": "Phase 2", "p1": "Phase 1"}.get(ph, e.get("type") or "")
        cond = ", ".join(e.get("conditions") or []) or NO_DATA
        enr = e.get("enrollment")
        glyph = "◆" if e.get("firm") else ("◌" if e.get("month") else "○")
        out.append(
            f'<div class="uv-ev" title="{esc(e.get("trial_title") or e.get("title"))}">'
            f'<span class="d"><i>{glyph}</i>{esc(dday(e["date"]))}</span>'
            f'{asset_cell(e)}'
            f'<span class="uv-ph {ph or "filed"}">{esc(stage)}</span>'
            f'<span class="w">{esc(cond)}</span>'
            f'<span class="e">{enr if enr else "·"}</span>'
            f'{stake_cell(e.get("stake"))}</div>')
    return "".join(out), len(rows)


def asset_cell(e):
    """The dialog's asset column: the drug the event names, or, where its registry title
    names none and the short name is a condition or the title's first words, "no drug
    named" (the condition has its own column; repeating it here read as an asset)."""
    if e.get("short_basis") in ("condition", "title"):
        return ('<span class="n none" title="The registry title names no drug">'
                'no drug named</span>')
    return f'<span class="n">{esc(e.get("short"))}</span>'


def stake_cell(stake):
    """What a dated event puts on the share: the swing a share between success and failure
    where the model prices it, else "no free data" with what would price it."""
    stake = stake or {}
    if stake.get("priced") and stake.get("per_share") is not None:
        return (f'<span class="s priced" title="Value a share on success less value a share '
                f'on failure, at the company\'s share of the economics">'
                f'${stake["per_share"]:.2f}</span>')
    missing = ", ".join(stake.get("missing") or [])
    tip = f' title="Needs {esc(missing)} on file"' if missing else ""
    return f'<span class="s"{tip}>{NO_DATA}</span>'


def next90_foot(p):
    """The line under the dialog's 90 days: how many of them the model prices, then the
    date glyphs."""
    rows = (p.get("focal") or {}).get("events") or []
    priced = sum(1 for e in rows if (e.get("stake") or {}).get("priced"))
    if not rows or not any(isinstance(e.get("stake"), dict) for e in rows):
        head = ""
    elif not priced:
        head = ("None of these carries a probability of success on file, so none is "
                "priced. ")
    else:
        head = (f"{priced} of {len(rows)} carry a probability of success on file; at stake "
                "is the swing in value a share between success and failure. ")
    return (head + "○ marks a date read off the registry's estimated primary completion, "
            "◌ a month only, ◆ a firm date.")


def dialog_figs(p):
    f = _focal(p)
    c = _cos(p).get(f) or {}
    rt = ((p.get("focal") or {}).get("fair_value") or {}).get("rating") or {}
    sv = c.get("street") or {}
    sc = c.get("score") or {}
    caps = {t: x.get("cap_usd_bn") for t, x in _cos(p).items() if x.get("cap_usd_bn")}
    figs = [
        (num(c.get("price")), f"close, {dday(c.get('price_as_of'))}", ""),
        (num(rt.get("value_today")),
         "model today" + (f", {rt['low_today']:.2f} to {rt['high_today']:.2f}"
                          if rt.get("low_today") is not None and rt.get("high_today") is not None else ""), ""),
        (num(rt.get("forward_12m")),
         "12 months" + (f", {pc(rt.get('upside_12m'))}" if rt.get("upside_12m") is not None else "")
         + (f", {rt['rating']}" if rt.get("rating") else ""),
         "up" if (rt.get("upside_12m") or 0) > 0 else ("down" if (rt.get("upside_12m") or 0) < 0 else "")),
        (num(sv.get("value")),
         "street target" + (f", {pc(sv.get('upside'))}" if sv.get("upside") is not None else "")
         + (f", {sv.get('buy')} buy {sv.get('hold')} hold" if sv.get("buy") is not None else ""), ""),
        (str(sc.get("score")) if sc.get("score") is not None else NO_DATA,
         "scorecard" + (f", {ordinal(sc['rank'])} of {sc.get('ranked_of') or len(_cos(p))}"
                        if sc.get("rank") else ""), ""),
        (f"${c['cap_usd_bn']:,.0f}bn" if c.get("cap_usd_bn") else NO_DATA,
         "market cap" + (f", {ordinal(1 + sum(1 for v in caps.values() if v > c['cap_usd_bn']))} of {len(_cos(p))}"
                         if c.get("cap_usd_bn") else ""), ""),
    ]
    return "".join(f'<div class="ki-f"><span class="v {cls} {"none" if v == NO_DATA else ""}">{esc(v)}</span>'
                   f'<span class="k">{esc(k)}</span></div>' for v, k, cls in figs)


def exposure_kv(p):
    f = _focal(p)
    c = _cos(p).get(f) or {}
    fo = p.get("focal") or {}
    loe = c.get("loe") or {}
    year = _loe_year(p)
    kv = []
    if loe.get("share_5y") is not None:
        kv.append((f"Exclusivity by {year}", f'{loe["share_5y"]*100:.0f}% of tagged revenue'
                   + (f', ${loe["at_risk_5y_usd"]/1e9:.1f}bn of ${loe["priced_total_usd"]/1e9:.1f}bn'
                      if loe.get("at_risk_5y_usd") is not None and loe.get("priced_total_usd") else "")))
    else:
        kv.append((f"Exclusivity by {year}", NO_DATA))
    first = fo.get("loe_first") or []
    if first:
        kv.append(("First to go", "; ".join(
            f'{b.get("brand")}, {b.get("basis") or "exclusivity"} {dlong(b.get("loe"))}'
            + (f', ${b["revenue"]/1e9:.2f}bn' if b.get("revenue") else "") for b in first[:2])))
    ira = c.get("ira") or {}
    if ira.get("selected"):
        kv.append(("Medicare", "; ".join(
            f'{s["brand"].title()} price year {s["ipay"]}'
            + (f', ceiling cut {s["ceiling_cut"]*100:.0f}%' if s.get("ceiling_cut") is not None else "")
            for s in ira["selected"])
            + (f'; ${ira["part_d_spending"]/1e9:.2f}bn Part D gross spend'
               if ira.get("part_d_spending") is not None else "")))
    elif "ira" in c:
        kv.append(("Medicare", "no drug selected for negotiation"))
    sl = c.get("slip") or {}
    if sl.get("on_file"):
        cos = _cos(p)
        most = sl.get("slipped") == max((x.get("slip") or {}).get("slipped") or 0 for x in cos.values())
        kv.append(("Trial dates", f'{sl.get("moved")} moved, {sl.get("slipped")} slipped'
                   + (f" (most of {len(cos)})" if most else "")
                   + f', {sl.get("pulled_in")} pulled in'
                   + (f', median {sgn(sl.get("median_days"), 0, " days")}'
                      if sl.get("median_days") is not None else "")))
    ro = fo.get("readouts") or []
    p3 = [r for r in ro if str(r.get("phase")) == "3"]
    if p3:
        neg = [r for r in p3 if r.get("outcome") == "negative"]
        npos = sum(1 for r in p3 if r.get("outcome") == "positive")
        named = ", ".join(f"{r.get('drug')}, {dday(r.get('date'))}" for r in neg)
        yr = _this_year(p)
        kv.append((f"{yr} Phase 3", f"{npos} positive, {len(neg)} negative"
                   + (f" ({named})" if neg else "")))
    aps = fo.get("approvals") or []
    if aps:
        yr = _this_year(p)
        kv.append((f"FDA approvals {yr}", ", ".join(
            f'{a.get("label")} {dday(a.get("date"))}'
            + (" (generic)" if a.get("application_type") == "ANDA" else "") for a in aps)))
    deals = fo.get("deals") or {}
    if deals.get("count_text"):
        kv.append(("Deals on file", f'{deals["count_text"]}'
                   + (f'; {deals["chip"].lower()}' if deals.get("chip") else "")))
    return "".join(f'<div class="uv-kv"><span>{esc(k)}</span><span>{esc(v)}</span></div>' for k, v in kv)


def dialog_html(p, opened_from="the map"):
    """The company dialog's body: six figures, then value against the price and the year
    against XLV, the scorecard against the median, the next 90 days and exposure."""
    f = _focal(p)
    c = _cos(p).get(f) or {}
    sc = c.get("score") or {}
    fo = p.get("focal") or {}
    pos = "".join(f'<div class="uv-pn up"><span>▲</span>{esc(x.get("text"))}<em>{esc(x.get("source"))}</em></div>'
                  for x in fo.get("positives") or [])
    neg = "".join(f'<div class="uv-pn down"><span>▼</span>{esc(x.get("text"))}<em>{esc(x.get("source"))}</em></div>'
                  for x in fo.get("negatives") or [])
    ev, nev = next90_html(p)
    n_peers = max(len(_cos(p)) - 1, 0)
    fb = football_svg(p)
    vx = vs_xlv_svg(p)
    pl = pillars_svg(p)
    rr = sc.get("rank_range")
    price_count = f"price {num(c.get('price'))}, dashed"
    count = (f'{sc.get("score")}, {ordinal(sc["rank"])} of {sc.get("ranked_of") or len(_cos(p))}'
             + (f', range {rr[0]} to {rr[1]}' if rr else "")) if sc.get("rank") else NO_DATA
    return (
        f'<div class="uv uv-dg">'
        f'<div class="uv-dg-sub">{esc(f)} against {n_peers} {esc(_cohort_noun(p))} peers · prices to the '
        f'{esc(dlong(p.get("price_date")))} close · opened from {esc(opened_from)}</div>'
        f'{incomplete_note(p)}'
        f'<div class="ki-figs uv-dg-figs">{dialog_figs(p)}</div>'
        f'<div class="uv-dg-grid">'
        f'<div>{section_html("Value against the price", "USD a share", price_count)}'
        + (f'<div class="chart-mount">{fb}</div>' if fb else f'<div class="uv-empty">{NO_DATA}: the model has not valued this company on this read.</div>')
        + f'<div class="uv-s2">{section_html("Against XLV, 1 year", "indexed to 100", "XLV on total return")}</div>'
        + (f'<div class="chart-mount">{vx}</div>' if vx else f'<div class="uv-empty">{NO_DATA}</div>')
        + '</div>'
        f'<div>{section_html("Scorecard against the median", "0 to 100", count)}'
        + (f'<div class="chart-mount">{pl}</div>' if pl else f'<div class="uv-empty">{NO_DATA}</div>')
        + f'<div class="uv-pns">{pos}{neg}</div></div>'
        f'<div>{section_html("Next 90 days", "registry estimates", f"{nev} dated")}'
        + ('<div class="uv-evh"><span>date</span><span>asset</span><span>stage</span><span>condition</span>'
           '<span>enrolled</span><span>at stake</span></div>' + ev if nev else
           '<div class="uv-empty">Nothing dated in the next 90 days.</div>')
        + f'<div class="uv-dg-foot">{esc(next90_foot(p))}</div></div>'
        f'<div>{section_html("Exposure and delivery", "on file")}{exposure_kv(p)}</div>'
        '</div></div>')


# ------------------------------------------------------------------ the page's sections
def spotlight_section(p, w=None):
    """The section rule over the rankings."""
    n = len(_cos(p))
    return section_html(f"{_name(p, _focal(p))} against the group",
                        f"place of {n}, 1st is best", f"hover a cell for all {n}")


def tab_head(left, right=""):
    """A panel tab's first line: what the tab is measured on, and its counts."""
    return (f'<div class="uv-th"><div class="b">{left}</div>'
            f'<div class="c">{esc(right)}</div></div>')


def _tab(head, body):
    return f'<div class="uv uv-tab">{head}{body}</div>'


def panel_tabs(p):
    """The tabbed panel under the hero, as [(tab label, body markup)]: the week ranked
    first, then the year's approvals and readouts, the prices, rates against the focal
    company's value, Medicare and exclusivity, and the policy calendar. None of it moves
    with the window."""
    f = _focal(p)
    lanes = p.get("lanes") or {}
    svg = lanes_svg(p)
    week = _tab(tab_head(f"Ranked by kind, then size. Rows carrying {esc(f)} are washed; "
                         "click a row to open it", week_count(p)), week_html(p))
    lane = _tab(tab_head(lanes_legend(p), lanes_counts(p)),
                f'<div class="chart-mount wide">{svg}</div>' if svg else
                f'<div class="uv-empty">{NO_DATA}: no approval or dated catalyst on file.</div>')
    sms = prices_html(p)
    prices = _tab(tab_head(esc(prices_basis(p)) + ", one scale; XLV on total return, dashed",
                           prices_count(p)),
                  sms or f'<div class="uv-empty">{NO_DATA}: no closes on file.</div>')
    rates = _tab(tab_head("30-day change", "FRED, ECB, Yahoo"), rates_html(p))
    exposure = _tab(tab_head("Share of revenue, each chart ranked on its own measure",
                             "CMS, FDA books"), exposure_html(p))
    policy = _tab(tab_head("Federal Register documents this year, by lane",
                           policy_count(p)), policy_html(p))
    return [("This week, ranked", week), ("Approvals and readouts", lane),
            ("Prices, 12 months", prices), (f"Rates and the {f} value", rates),
            ("Medicare and exclusivity", exposure), ("Policy calendar", policy)]


# =========================================================================================
# The week across the group: the news-first page. The control row's kicker, the lead story,
# the ranked feed, the company board, the cheap to expensive ribbon and the grid of every
# change. Every rule reads the group; the company in focus is washed where it falls and
# nowhere else, so the page reads the same whichever company is picked.
# =========================================================================================
# The colour of each kind of news. Green and red mean up and down, and cheap and expensive,
# and nothing else on the page, so the kinds take the other colours: deals purple, results
# the phase ramp, anything at the FDA amber, a date running against a company orange
# (a slip, an exclusivity ending), and the rest of the record grey.
KIND_COLOUR = {
    "deal": "var(--purple-book)", "readout": "var(--phase-3)", "readout2": "var(--phase-2)",
    "notice": "var(--phase-1)", "due": "var(--phase-3)", "approval": "var(--flag)",
    "regulatory": "var(--flag)", "slips": "var(--orange-book)", "loe": "var(--orange-book)",
    "market": "var(--muted)", "earnings": "var(--muted)", "filing": "var(--muted)",
    "labels": "var(--muted)",
}
# The grid's rows (backend GRID_KINDS) in the same colours.
GRID_COLOUR = {"deal": "var(--purple-book)", "result": "var(--phase-3)", "fda": "var(--flag)",
               "slip": "var(--orange-book)", "company": "var(--muted)",
               "routine": "var(--muted)"}
# The kinds the live week_item draws; the rest are drawn by feed_item.
_LIVE_KINDS = ("deal", "market", "readout", "readout2", "approval", "regulatory")
# The ranked feed under the lead story: two columns of this many rows at 1440, ranks 2 on.
RANK_ROWS = 4
STAGE = {"p3": "Ph 3", "p2": "Ph 2", "p1": "Ph 1"}
# What a lead story built from a verbatim headline says it is.
LEAD_WORDS = {"deal": "deal announced, no value stated", "notice": "data to be presented",
              "earnings": "results date set"}


def week_kicker(p):
    """The control row's first words: the week the band below covers."""
    since, to = p.get("week_since"), p.get("today")
    span = f"{dday(since)} to {dday(to)}" if since and to else NO_DATA
    return (f'<div class="uw-kick0"><span class="lbl">The week</span>'
            f'<span class="dt">{esc(span)}</span></div>')


def bars_mini(rows, colour, fmt=lambda v: f"{v:,}"):
    """Up to three labelled bars on one scale, drawn 1:1 at the mini's size: the week's
    longest slips in days, or the companies with most labels revised."""
    rows = [(t, v) for t, v in rows or [] if v][:3]
    if not rows:
        return ""
    mx = max(v for _t, v in rows)
    o = [_mini_open()]
    for i, (t, v) in enumerate(rows):
        y = 1 + i * 9
        bw = max(30 * v / mx, 1)
        o.append(text(0, y + 7, t, 9, T["muted"], mono=True))
        o.append(f'<rect x="32" y="{y + 1.5}" width="{bw:.1f}" height="5" fill="{colour}"/>')
        o.append(text(32 + bw + 3, y + 7, fmt(v), 9, T["text"], mono=True))
    o.append("</svg>")
    return "".join(o)


def _ekey(e):
    """A dated event's sort key: a month-only date sorts at its month's end."""
    return e["date"] + ("-99" if e.get("month") else "")


def vb(text, verbatim=True):
    """A source's own words, marked so (a quoted headline or a filing's title); house
    style governs every other string on the page."""
    return f'<span class="vb">{esc(text)}</span>' if verbatim else esc(text)


def _tk_marks(p, tickers, limit=4):
    """The tickers an item names, each opening the company; ``ALL`` is the whole group."""
    if tickers == ["ALL"]:
        return f'<span class="uw-tks"><b class="all">All {len(_cos(p))}</b></span>'
    f = _focal(p)
    marks = [f'<b class="{"me" if t == f else ""}" data-ticker="{esc(t)}">{esc(t)}</b>'
             for t in tickers[:limit]]
    more = f'<b class="all">+{len(tickers) - limit}</b>' if len(tickers) > limit else ""
    return f'<span class="uw-tks">{"<i>·</i>".join(marks)}{more}</span>'


def feed_item(p, it):
    """One item of the week's feed as its parts, for the group: the live week_item's
    parts for the kinds it draws, this page's for the rest. No row names the company in
    focus, so the item reads the same whichever company is picked."""
    kind = it.get("kind")
    if kind in _LIVE_KINDS:
        x = week_item(p, it)
        x["rows"] = [(k, v) for k, v in x["rows"] if not str(k).startswith("For ")]
        if it.get("quote"):
            x["rows"][:0] = [("Source title", it["quote"])] + (
                [("Quoted from", it["quote_src"])] if it.get("quote_src") else [])
        if kind == "deal" and not it.get("value_usd"):
            x.update(fig="not stated", sub="value", fcls="none")
        if kind == "approval":
            x["head"] = "FDA label expansions: " + ", ".join(it.get("brands") or [])
    else:
        m = it.get("mini") or {}
        mini = ""
        if m.get("type") == "slipbars":
            mini = bars_mini(m.get("rows"), T["orange"], lambda v: f"{v:,}d")
        elif m.get("type") == "dates" and m.get("a") and m.get("b"):
            mini = dates_mini(m.get("dates") or [], m.get("a"), m.get("b"))
        tickers = it.get("tickers") or []
        if kind == "notice" and tickers:
            mini = stock_mini((p.get("closes") or {}).get(tickers[0]) or [], [it.get("date")])
        elif kind == "earnings" and it.get("call"):
            days = (_d(it["call"]) - _d(p.get("today"))).days if _d(p.get("today")) else None
            if days is not None and 0 <= days <= 30:
                mini = countdown_mini(days, 30)
        elif kind == "labels":
            mini = bars_mini([(t, len(str(v).split("; "))) for t, v in it.get("rows") or []],
                             T["muted"])
        rows = [(k, dlong(v) if _d(v) and len(str(v)) == 10 else v)
                for k, v in it.get("rows") or []]
        x = {"tag": it.get("tag") or kind, "head": it.get("head") or "", "mini": mini,
             "fig": it.get("fig") or NO_DATA, "sub": it.get("fig_sub") or "", "fcls": "",
             "rows": rows, "title": "", "url": it.get("url"), "src": it.get("src") or ""}
    x["kind"] = kind
    x["accent"] = KIND_COLOUR.get(kind, "var(--rule-strong)")
    x["verbatim"] = bool(it.get("verbatim"))
    x["focus"] = _focal(p) in (it.get("tickers") or [])
    return x


def _item_card(p, it, x, cls=""):
    """An item's detail: the full headline, its rows, its note and its source, and whether
    the headline is the source's own words. Opens on hover and holds on a click."""
    rows = "".join(f'<div class="uv-kv"><span>{esc(k)}</span>'
                   f'<span>{vb(v, str(k).startswith("Filed ") or k == "Source title")}</span></div>'
                   for k, v in x["rows"])
    note = f'<div class="nt">{esc(it["note"])}</div>' if it.get("note") else ""
    title = f'<div class="nt">{vb(x["title"])}</div>' if x.get("title") else ""
    link = (f'<a href="{esc(x["url"])}" target="_blank" rel="noopener">source</a>'
            if x.get("url") else "")
    words = "headline as the source wrote it" if x["verbatim"] else "in our words"
    return (f'<div class="uw-card {cls}"><div class="ck"><span class="uw-tag" '
            f'style="--accent:{x["accent"]}">{esc(x["tag"])}</span>'
            f'{_tk_marks(p, it.get("tickers") or [], 8)}'
            f'<span class="uw-dt">{esc(dlong(it.get("date")))}</span></div>'
            f'<div class="hh">{vb(x["head"], x["verbatim"])}</div>{title}{rows}{note}'
            f'<div class="src"><span>{esc(x["src"])} · {words}</span>{link}</div></div>')


# ------------------------------------------------------------------------ the lead story
def consideration_svg(up, ms, up_s, ms_s, w=220, h=38):
    """A deal's announced value split on one bar: the upfront solid, the milestones pale,
    each part named under its own end."""
    total = up + ms
    w1 = max((w - 2) * up / total, 2)
    return (f'<svg class="uw-cons" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Upfront {esc(up_s)}, milestones {esc(ms_s)}">'
            f'<rect x="0" y="4" width="{w1:.1f}" height="14" fill="{T["purple"]}"/>'
            f'<rect x="{w1 + 2:.1f}" y="4" width="{w - w1 - 2:.1f}" height="14" '
            f'fill="{T["purple"]}" fill-opacity="0.32"/>'
            + text(0, 32, f"{up_s} upfront", 10.5, T["text"], mono=True)
            + text(w, 32, f"{ms_s} milestones", 10.5, T["muted"], "end", mono=True) + "</svg>")


def day_spark(p, t, day, move, w=120, h=24, n=16):
    """A company's last closes with the news day dashed and the day's move beside it. A
    close not yet in prints as such, never as zero."""
    rows = ((p.get("closes") or {}).get(t) or [])[-n:]
    vals = [c for _d0, c in rows]
    f = _focal(p)
    lab = (f'<span class="mv {"down" if move < 0 else "up" if move > 0 else ""}">'
           f'{esc(pc(move))}</span>' if move is not None
           else '<span class="mv none">no close yet</span>')
    tk = f'<b class="{"me" if t == f else ""}" data-ticker="{esc(t)}">{esc(t)}</b>'
    if len(vals) < 2:
        return f'<div class="uw-ds">{tk}<span class="mv none">{NO_DATA}</span>{lab}</div>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1

    def sx(i):
        return 2 + i / (len(vals) - 1) * (w - 6)

    def sy(v):
        return h - 3 - (v - lo) / span * (h - 6)
    pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(vals))
    k = next((i for i, (d0, _c) in enumerate(rows) if day and d0 >= day), None)
    mark = ""
    if k is not None:
        mark = (f'<line x1="{sx(k):.1f}" x2="{sx(k):.1f}" y1="0" y2="{h}" stroke="{T["muted"]}" '
                f'stroke-width="1" stroke-dasharray="2 2"/>'
                f'<circle cx="{sx(k):.1f}" cy="{sy(vals[k]):.1f}" r="2.6" fill="{T["text"]}"/>')
    svg = (f'<svg class="uw-spk" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
           f'<polyline points="{pts}" fill="none" stroke="{T["text"]}" stroke-width="1.3" '
           f'stroke-opacity="0.85"/>{mark}</svg>')
    return f'<div class="uw-ds">{tk}{svg}{lab}</div>'


def rate_spark(vals, w=300, h=40):
    """The 10-year's path over the quarter, its first and last levels at either end."""
    vals = [v for v in vals or [] if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    iw = w - 92
    pts = " ".join(f"{46 + i / (len(vals) - 1) * iw:.1f},{h - 4 - (v - lo) / span * (h - 8):.1f}"
                   for i, v in enumerate(vals))
    ey = h - 4 - (vals[-1] - lo) / span * (h - 8)
    return (f'<svg class="uw-spk" width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="{T["text"]}" stroke-width="1.4"/>'
            f'<circle cx="{46 + iw:.1f}" cy="{ey:.1f}" r="2.4" fill="{T["text"]}"/>'
            + text(40, h - 4 - (vals[0] - lo) / span * (h - 8) + 3.5, f"{vals[0] * 100:.2f}%",
                   10.5, T["muted"], "end", mono=True)
            + text(50 + iw + 2, ey + 3.5, f"{vals[-1] * 100:.2f}%", 10.5, T["text"], mono=True)
            + "</svg>")


def _lead_chart(p, it, x):
    """The lead story's chart, by kind: a deal's consideration and each party's closes
    either side of the day; a result's closes either side of its day; the rate's path; any
    other kind its own mini at 1:1."""
    kind = it.get("kind")
    m = it.get("mini") or {}
    day = it.get("date")
    cap = f'<div class="uw-cap">last 16 closes, {esc(dday(day))} dashed; move on the day</div>'
    if kind == "deal":
        moves = next((v for k, v in it.get("rows") or [] if str(k).startswith("Day move")), [])
        sparks = "".join(day_spark(p, t, day, mv) for t, mv in moves or [])
        terms = it.get("terms") or {}
        bar = ""
        if m.get("type") == "deal" and m.get("upfront") and m.get("milestones"):
            bar = consideration_svg(m["upfront"], m["milestones"],
                                    terms.get("upfront") or f'${m["upfront"] / 1e9:.1f}bn',
                                    terms.get("milestones") or f'${m["milestones"] / 1e9:.1f}bn')
        return (f'<div class="uw-lbar">{bar}</div>' if bar else "") + \
            (f'<div class="uw-lmv">{sparks}{cap}</div>' if sparks else "")
    if kind in ("readout", "readout2", "notice") and (it.get("tickers") or []):
        t = it["tickers"][0]
        return (f'<div class="uw-lmv">{day_spark(p, t, day, it.get("fig_move"), w=260, h=34)}'
                f'{cap}</div>')
    if m.get("type") == "spark":
        return (f'<div class="uw-lmv">{rate_spark(m.get("values"))}'
                f'<div class="uw-cap">10-year Treasury, the quarter to {esc(dday(day))}</div></div>')
    return f'<div class="uw-lmv">{x["mini"]}</div>' if x["mini"] else ""


def lead_story(p, it):
    """Rank 1 as the lead story: the kicker (kind, tickers, date), a headline built from
    the item's own fields, the source's own title quoted as the deck and attributed, then
    the figure and the kind's own chart. The detail rows open from the kicker."""
    x = feed_item(p, it)
    kind = it.get("kind")
    tks = it.get("tickers") or []
    who = _name(p, tks[0]) if tks and tks != ["ALL"] else ""
    head, fig, sub, fcls = x["head"], x["fig"], x["sub"], x["fcls"]
    deck, deck_by = it.get("quote"), it.get("quote_src")
    if kind == "deal" and it.get("value_usd"):
        terms = it.get("terms") or {}
        parties = it.get("parties") or []
        party = terms.get("counterparty") or (parties[1]["short"] if len(parties) > 1 else "")
        lead = f"{who} and {party}" if party else who
        head = (f'{lead}: {terms["upfront"]} upfront, up to {terms["milestones"]} in milestones'
                if terms.get("upfront") and terms.get("milestones")
                else f"{lead}: {fig} announced")
        sub = "announced value"
    elif kind in ("readout", "readout2"):
        ph = it.get("phase")
        head = f"{who}: Phase {ph} result" if ph else f"{who}: a result"
        deck, deck_by = x["head"], "the company's announcement"
        sub = f"on the day, {dday(it.get('date'))}"
    elif x["verbatim"]:
        head = f"{who}: {LEAD_WORDS.get(kind, x['tag'])}"
        deck, deck_by = x["head"], "the company's announcement"
    deck_html = (f'<p class="uw-deck">&ldquo;{vb(deck)}&rdquo;'
                 f'<span class="by">{esc(deck_by or "")}</span></p>' if deck else "")
    link = (f'<a class="uw-src" href="{esc(x["url"])}" target="_blank" rel="noopener">source</a>'
            if x.get("url") else "")
    return (f'<article class="uw-lead" tabindex="0" style="--accent:{x["accent"]}">'
            f'<div class="uw-kick"><span class="uw-tag">{esc(x["tag"])}</span>'
            f'{_tk_marks(p, tks)}<span class="uw-dt">{esc(dday(it.get("date")))}</span>'
            f'<span class="uw-more">detail ▾</span>{link}</div>'
            f'<h2 class="uw-hd" title="{esc(head)}">{esc(head)}</h2>{deck_html}'
            f'<div class="uw-viz"><div class="uw-fig"><b class="{fcls}">{esc(fig)}</b>'
            f'<small>{esc(sub)}</small></div>{_lead_chart(p, it, x)}</div>'
            f'{_item_card(p, it, x, "uw-lc")}</article>')


# --------------------------------------------------------------------- this week, ranked
def _rank_row(p, it, n):
    x = feed_item(p, it)
    me = " me" if x["focus"] else ""
    return (f'<div class="uw-it{me}" tabindex="0" style="--accent:{x["accent"]}">'
            f'<span class="n">{n}</span>'
            f'<div class="bd"><div class="k"><span class="uw-tag">{esc(x["tag"])}</span>'
            f'{_tk_marks(p, it.get("tickers") or [], 3)}'
            f'<span class="uw-dt">{esc(dday(it.get("date")))}</span></div>'
            f'<div class="h">{vb(x["head"], x["verbatim"])}</div></div>'
            f'<span class="ch">{x["mini"]}</span>'
            f'<span class="f"><b class="{x["fcls"]}">{esc(x["fig"])}</b>'
            f'<small>{esc(x["sub"])}</small></span>{_item_card(p, it, x)}</div>')


def ranked_html(p, start=2, rows=RANK_ROWS):
    """"This week, ranked" under the lead: the feed from rank ``start``, two columns of
    ``rows``, read down the first and then the second. Each item has its kind, its
    tickers, its headline, its small chart and its figure; a hover or a click opens its
    detail. The ranks the column has no room for are one hover away in the head."""
    items = p.get("week_items") or []
    shown = items[start - 1:start - 1 + 2 * rows]
    rest = items[start - 1 + 2 * rows:]
    since, to = p.get("week_since"), p.get("today")
    span = f"{dday(since)} to {dday(to)}" if since and to else ""
    if not shown:
        body = ('<div class="uv-empty">Nothing more across the group in the last seven '
                'days.</div>' if items else "")
        return (f'<section class="uw-rk"><div class="uw-rkh"><span class="lbl">This week, '
                f'ranked</span><span class="c">{esc(span)}</span></div>{body}</section>')
    cols = [shown[:rows], shown[rows:]]
    html_cols = "".join(
        f'<div class="col">{"".join(_rank_row(p, it, start + ci * rows + i) for i, it in enumerate(c))}</div>'
        for ci, c in enumerate(cols))
    more = ""
    if rest:
        lines = "".join(
            f'<div class="uw-mr"><span class="n">{start + 2 * rows + i}</span>'
            f'<span class="uw-tag" style="--accent:{KIND_COLOUR.get(it.get("kind"), "var(--rule-strong)")}">'
            f'{esc(feed_item(p, it)["tag"])}</span>'
            f'<span class="h">{_tk_marks(p, it.get("tickers") or [], 3)} '
            f'{vb(feed_item(p, it)["head"], bool(it.get("verbatim")))}</span>'
            f'<span class="f">{esc(feed_item(p, it)["fig"])}</span></div>'
            for i, it in enumerate(rest))
        more = (f'<span class="uw-moreh" tabindex="0">{len(rest)} more ▾'
                f'<div class="uw-card uw-mc"><div class="ck"><b>Also ranked this week</b></div>'
                f'{lines}</div></span>')
    last = start - 1 + len(shown)
    count = f"{span} · {start} to {last} of {len(items)}" if span else f"{start} to {last} of {len(items)}"
    return (f'<section class="uw-rk"><div class="uw-rkh"><span class="lbl">This week, ranked'
            f'</span><span class="c">{esc(count)}{more}</span></div>'
            f'<div class="uw-rkc">{html_cols}</div></section>')


# ----------------------------------------------------------------------- the company board
def _event_words(e):
    """A dated event in words: its stage (PDUFA, FDA, Ph 3) and its drug, or its
    condition's study where the registry title names no drug."""
    if e.get("regulatory"):
        stage = "PDUFA" if (e.get("type") or "").upper() == "PDUFA" else "FDA"
    else:
        stage = STAGE.get(e.get("phase") or "", "")
    name = e.get("name") or e.get("short") or ""
    return " ".join(w for w in (stage, name) if w) or (e.get("type") or NO_DATA)


def _event_date(e):
    """A dated event's date as the board prints it: the day, or the month alone, which
    the 90-day window makes unambiguous."""
    if e.get("month"):
        m = _d(str(e["date"])[:7] + "-01")
        return f"{m:%b}" if m else str(e["date"])
    return dday(e["date"])


def _news_line(x):
    kinds = {"deal": "deal", "result": "result", "fda": "FDA", "company": "filing",
             "slip": "slip"}
    return (f'<div class="bn"><span class="d">{esc(dday(x.get("date")))}</span>'
            f'<span class="uw-tag" style="--accent:{GRID_COLOUR.get(x.get("kind"), "var(--muted)")}">'
            f'{esc(kinds.get(x.get("kind"), x.get("kind")))}</span>'
            f'<span class="t">{vb(x.get("text"), bool(x.get("verbatim")))}</span></div>')


def board_html(p):
    """The company board: one row per company, washed for the company in focus but not
    pinned. The week's move as a tinted figure, the week's news count, the next dated event
    in words (FDA dates in amber, a firm date marked, an estimate muted) and the count of
    dated events in 90 days. Three sorts, switched in the browser; the week sort draws
    XLV's week where it falls. A row's hover lists the company's news of the week; a click
    opens the company."""
    cos = _cos(p)
    tks = _tickers(p)
    f = _focal(p)
    w = p.get("week") or {}
    news = w.get("news") or {}
    nxt = w.get("next") or {}
    wk = {t: cos[t]["change_5d"] for t in tks if (cos.get(t) or {}).get("change_5d") is not None}
    mx = max([abs(v) for v in wk.values()] or [0]) or 1
    xlv = (p.get("xlv_week") or {}).get("change")
    by_wk = sorted(tks, key=lambda t: (t not in wk, -wk.get(t, 0), t))
    by_nw = sorted(tks, key=lambda t: (-len(news.get(t) or []), t not in wk, -wk.get(t, 0), t))
    by_nx = sorted(tks, key=lambda t: (nxt.get(t) is None,
                                       _ekey(nxt[t]) if nxt.get(t) else "", t))
    o_wk = {t: 2 * i for i, t in enumerate(by_wk)}
    o_nw = {t: 2 * i for i, t in enumerate(by_nw)}
    o_nx = {t: 2 * i for i, t in enumerate(by_nx)}
    rows = []
    for t in tks:
        c = cos.get(t) or {}
        me = " me" if t == f else ""
        if t in wk:
            v = wk[t]
            tone = "up" if v > 0 else "down" if v < 0 else ""
            wcell = (f'<span class="wk {tone}" style="--uw-a:{10 + 48 * abs(v) / mx:.0f}%">'
                     f'{esc(pc(v))}</span>')
        else:
            wcell = f'<span class="wk none">{NO_DATA}</span>'
        mine = news.get(t) or []
        ncell = f'<span class="nw{"" if mine else " z"}">{len(mine) if mine else "·"}</span>'
        e = nxt.get(t)
        if e:
            fda = " fda" if e.get("regulatory") else ""
            est = "" if e.get("firm") else " est"
            firm = " firm" if e.get("firm") else ""
            ecell = (f'<span class="nd{fda}{est}{firm}">{esc(_event_date(e))}</span>'
                     f'<span class="nx{fda}">{esc(_event_words(e))}</span>')
        else:
            ecell = '<span class="nd est">·</span><span class="nx none">none dated in 90 days</span>'
        n90 = c.get("n90")
        cnt = f'<span class="c9{"" if n90 else " z"}">{n90 if n90 is not None else NO_DATA}</span>'
        lines = "".join(_news_line(x) for x in mine[:6])
        if len(mine) > 6:
            lines += f'<div class="bn none">and {len(mine) - 6} more under Every change</div>'
        if not lines:
            lines = '<div class="bn none">No news this week: no deal, result, approval, filing or Phase 3 slip.</div>'
        when = (f'{_event_date(e)} {_event_words(e)}, '
                + ("a firm date" if e.get("firm") else "a month only" if e.get("month")
                   else "a registry estimate") if e else "none dated")
        move = (f"week {pc(wk[t])}" + (f", XLV {pc(xlv)}" if xlv is not None else "")
                if t in wk else f"week: {NO_DATA}")
        card = (f'<div class="uw-bcard"><div class="ck"><b>{esc(c.get("short") or t)}</b>'
                f'<span>{esc(t)} · {esc(move)}</span></div>'
                f'<div class="bs">This week, {len(mine)} news item{"" if len(mine) == 1 else "s"}</div>{lines}'
                f'<div class="bs">Next dated event</div><div class="bn"><span class="t">{esc(when)}; '
                f'{n90 if n90 is not None else NO_DATA} dated in 90 days</span></div>'
                f'<div class="hint">Click the row for the company</div></div>')
        rows.append(f'<div class="uw-br{me}" data-ticker="{esc(t)}" '
                    f'style="--uw-ow:{o_wk[t]};--uw-on:{o_nw[t]};--uw-ox:{o_nx[t]}" '
                    f'aria-label="{esc(c.get("short") or t)}"><span class="tk">{esc(t)}</span>'
                    f'{wcell}{ncell}{ecell}{cnt}{card}</div>')
    xrule = ""
    if xlv is not None and wk:
        k = sum(1 for v in wk.values() if v > xlv)
        xrule = (f'<div class="uw-bx" style="--uw-ow:{2 * k - 1}" '
                 f'title="XLV {esc(pc(xlv))} over the same week"></div>')
    sorts = ('<input class="uw-r" type="radio" name="uwbs" id="uwbs-w" checked>'
             '<input class="uw-r" type="radio" name="uwbs" id="uwbs-n">'
             '<input class="uw-r" type="radio" name="uwbs" id="uwbs-x">')
    head = ('<div class="uw-bh"><span class="lbl">Company board</span><span class="uw-sort">'
            '<span>sort</span><label for="uwbs-w">week move</label><label for="uwbs-n">news</label>'
            '<label for="uwbs-x">next date</label></span></div>')
    span = (f'{dday((cos.get(tks[0]) or {}).get("close_5d_as_of"))} to {dday(p.get("price_date"))} close'
            if tks else "")
    key = (f'<div class="uw-bk"><span>week: {esc(span)}'
           + (f'; dashed rule XLV {esc(pc(xlv))}' if xlv is not None else "")
           + '</span><span><i class="dia"></i>firm date · <em>grey: estimate</em> · '
             '<em class="fda">amber: FDA</em></span></div>')
    cols = ('<div class="uw-bcols"><span>Co.</span><span class="r">Week</span>'
            '<span class="c" title="News this week: deals, results, approvals, filings and '
            'Phase 3 slips">News</span><span class="nh">Next dated event</span>'
            '<span class="r" title="Dated events in the next 90 days">90d</span></div>')
    return (f'<section class="uw-board" data-from="the board">{sorts}{head}{key}{cols}'
            f'<div class="uw-bb">{"".join(rows)}{xrule}</div></section>')


# ----------------------------------------------------------------- cheap to expensive
def ribbon_html(p):
    """The group from cheapest to most expensive on the model's 12-month upside, green for
    cheap fading through to red for expensive, a rule where value meets the price, and any
    company with no model value last as "no free data". The company in focus is outlined.
    A tile's hover gives the close, the model's 12-month value and rating and the street
    target; a click opens the company."""
    cos = _cos(p)
    f = _focal(p)
    tks = _tickers(p)
    up = {t: (cos[t].get("model") or {}).get("upside") for t in tks}
    order = [t for t in ((p.get("week") or {}).get("value_order") or []) if t in cos] or \
        sorted([t for t in tks if up[t] is not None], key=lambda t: -up[t])
    have = [t for t in order if up.get(t) is not None]
    miss = [t for t in tks if up.get(t) is None]
    cells, placed = [], False
    seq = have + miss
    for i, t in enumerate(seq):
        c = cos.get(t) or {}
        m = c.get("model") or {}
        s = c.get("street") or {}
        u = up.get(t)
        if u is not None and u < 0 and not placed and i:
            cells.append('<div class="uw-zero"><span>value = price</span></div>')
            placed = True
        if u is None:
            style, cls, v = "", " na", NO_DATA
        else:
            a = round(12 + 50 * min(abs(u) / 0.6, 1))
            col = "var(--up)" if u > 0 else "var(--down)" if u < 0 else "var(--muted)"
            style = f' style="--uw-bg:color-mix(in oklab, {col} {a}%, var(--ground))"'
            cls, v = "", pc(u)
        me = " me" if t == f else ""
        side = " rt" if i >= len(seq) - 6 else ""
        cur = c.get("currency") or ""
        close = (f'Close {num(c.get("price"))} {esc(cur)}, {esc(dday(c.get("price_as_of")))}'
                 if c.get("price") is not None else f"Close: {NO_DATA}")
        model = (f'Model value in 12 months {num(m.get("forward_12m"))}, {pc(u)}, '
                 f'{esc(m.get("rating") or "no rating")}' if u is not None
                 else f"Model value: {NO_DATA}")
        street = (f'Street target {num(s.get("value"))}, {pc(s.get("upside"))}; '
                  + ", ".join(f'{s.get(k)} {k}' for k in ("buy", "hold", "sell")
                              if s.get(k) is not None)
                  if s.get("upside") is not None else f"Street target: {NO_DATA}")
        card = (f'<div class="uw-rc"><div class="ck"><b>{esc(c.get("short") or t)}</b>'
                f'<span>{esc(t)}</span></div><div>{close}</div><div>{model}</div>'
                f'<div>{street}</div></div>')
        cells.append(f'<div class="uw-tile{cls}{me}{side}" data-ticker="{esc(t)}"{style}>'
                     f'<b class="tk">{esc(t)}</b><span class="v">{esc(v)}</span>{card}</div>')
    return (f'<section class="uw-rib" data-from="the ribbon"><div class="lab"><b>Cheap to '
            f'expensive</b><span>model 12-month upside</span></div>'
            f'<div class="uw-cells">{"".join(cells)}</div></section>')


def front_html(p):
    """Everything the uvboard frame draws: the news and the board side by side, the ribbon
    under them."""
    items = p.get("week_items") or []
    lead = (lead_story(p, items[0]) if items else
            '<div class="uv-empty">Nothing material across the group in the last seven days.</div>')
    return (f'<div class="uv uv-frame uw-front"><div class="uw-band">'
            f'<div class="uw-news" data-from="the news">{lead}{ranked_html(p)}</div>'
            f'{board_html(p)}</div>{ribbon_html(p)}</div>')


# -------------------------------------------------------------------------- every change
def changes_grid_html(p):
    """Every change of the week, company by kind: a column per company, most changes
    first, a row per kind with its total. A cell is its count, tinted in its kind's colour
    by its share of the row's largest; a hover lists the cell's changes. Counts are feed
    rows, not events: a deal's filings are each a change."""
    w = p.get("week") or {}
    grid = w.get("grid") or {}
    if not grid:
        return f'<div class="uv-empty">{NO_DATA}: no change feed for the week.</div>'
    labels = w.get("kind_labels") or {}
    kinds = list(labels) or list(GRID_COLOUR)
    f = _focal(p)
    tks = [t for t in _tickers(p) if t in grid]
    tot = {t: sum(len(grid[t].get(k) or []) for k in kinds) for t in tks}
    cols = sorted(tks, key=lambda t: (-tot[t], tks.index(t)))
    total = sum(tot.values())
    routine = w.get("routine_filings") or 0
    half = len(cols) // 2
    o = [f'<div class="uw-grid" style="--uw-n:{len(cols)}">'
         f'<div class="gh lab"><b>Every change</b><span>{total} this week'
         + (f', {routine} routine filings left out' if routine else "") + '</span></div>']
    for t in cols:
        o.append(f'<div class="gh{" me" if t == f else ""}" title="{esc(_name(p, t))}: '
                 f'{tot[t]} changes this week"><span class="t">{esc(t)}</span>'
                 f'<span class="v">{tot[t]}</span></div>')
    for k in kinds:
        n_k = (w.get("kinds") or {}).get(k, sum(len(grid[t].get(k) or []) for t in cols))
        rmx = max([len(grid[t].get(k) or []) for t in cols] or [0]) or 1
        o.append(f'<div class="gl" style="--accent:{GRID_COLOUR.get(k, "var(--muted)")}">'
                 f'<span>{esc(labels.get(k, k))}</span><b>{n_k}</b></div>')
        for i, t in enumerate(cols):
            its = grid[t].get(k) or []
            me = " me" if t == f else ""
            if not its:
                o.append(f'<div class="gc z{me}"></div>')
                continue
            a = round(12 + 40 * len(its) / rmx)
            lines = "".join(
                f'<div class="li"><span>{esc(dday(x.get("date")))}</span>'
                f'<span>{vb(x.get("text"), bool(x.get("verbatim")))}</span></div>' for x in its[:8])
            more = f'<div class="li mo">and {len(its) - 8} more</div>' if len(its) > 8 else ""
            side = " lf" if i >= half else ""
            o.append(f'<div class="gc{me}" tabindex="0" style="--accent:'
                     f'{GRID_COLOUR.get(k, "var(--muted)")};--uw-a:{a}%"><span>{len(its)}</span>'
                     f'<div class="uw-gcard{side}"><div class="ck"><b>{esc(t)}</b>'
                     f'<span>{esc(labels.get(k, k))}, {len(its)}</span></div>{lines}{more}</div></div>')
    o.append("</div>")
    return "".join(o)


def week_panel_tabs(p, w=None):
    """The slim panel under the ribbon, as [(tab label, body markup)]: every change of the
    week first, then the year's approvals and readouts, the prices, rates and currencies,
    Medicare and exclusivity, the policy calendar and the company in focus against the
    group. Only the last reads the company picked."""
    f = _focal(p)
    svg = lanes_svg(p, pin=False)
    every = _tab("", changes_grid_html(p))
    lane = _tab(tab_head(lanes_legend(p, pin=False), lanes_counts(p)),
                f'<div class="chart-mount wide">{svg}</div>' if svg else
                f'<div class="uv-empty">{NO_DATA}: no approval or dated catalyst on file.</div>')
    sms = prices_html(p)
    prices = _tab(tab_head(esc(prices_basis(p)) + ", one scale; XLV on total return, dashed",
                           prices_count(p)),
                  sms or f'<div class="uv-empty">{NO_DATA}: no closes on file.</div>')
    rates = _tab(tab_head("30-day change", "FRED, ECB, Yahoo"), rates_html(p, focal=False))
    exposure = _tab(tab_head("Share of revenue, each chart ranked on its own measure",
                             "CMS, FDA books"), exposure_html(p, focal_caption=False))
    policy = _tab(tab_head("Federal Register documents this year, by lane", policy_count(p)),
                  policy_html(p))
    strip = _tab(spotlight_section(p, w), spotlight_html(p, w))
    return [("Every change", every), ("Approvals and readouts", lane),
            ("Prices, 12 months", prices), ("Rates and FX", rates),
            ("Medicare and exclusivity", exposure), ("Policy calendar", policy),
            (f"{f} against the group", strip)]
