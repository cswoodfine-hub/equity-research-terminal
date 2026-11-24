"""The Portfolio tab's asset cards: a marketed product and a pipeline compound, each read
at a glance.

A card was three label and value lines, the same three on all forty-four of a large
company's products, and a compound in development had no card at all: it was a row of a
list of studies. Both are cards here and each draws the two things its kind is judged on.

A marketed product is what it earns and how long it is protected. The revenue stands
with its share of the company's tagged revenue and, where more than one year is on file,
a column for each year, so growth or decline is seen before it is read. Exclusivity is a
bar of the years left on one scale across every card, so two products can be compared by
the length of their bars without reading either date.

A compound is how far it has come and what happens next. The phase is a track of four
steps, the next event is named with how far off it is, and the book's odds and value a
share stand on one line where the book prices the compound, the odds in their band's
colour and the value in small type, with the reason where it does not. A study date the
registry moved stands on the card of the compound or product it belongs to. The studies
are counted on the card and listed in full one click away. The compounds by disease area
are a ring beside the cards, its hover the stylesheet's.

Pure functions from payload rows to markup: nothing here reads a network, a clock or
Streamlit, so the caller passes today's date. A null is never drawn as a zero. Colour is
the stylesheet's, by class; the only inline styles are the lengths of the bars.
"""

from __future__ import annotations

import datetime as dt
import html
import math
import re

MINUS = "−"
NO_DATA = "no free data"
MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# The scale every exclusivity bar is drawn on. Fifteen years holds a new approval's whole
# protection, so a full bar is a product at the start of its life and not merely a long one.
RUNWAY_YEARS = 15
# The track's four steps. A seamless study (Phase 1/2, Phase 2/3) stands between two.
STEPS = (("Phase 1", "P1"), ("Phase 2", "P2"), ("Phase 3", "P3"), ("FDA review", "FDA"))
HISTORY_YEARS = 5
HISTORY_H = 22          # the tallest column of a revenue history, in pixels
# A registry status that means patients are being taken on now.
ENROLLING = ("recruiting", "enrolling by invitation")


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def num(value, places: int = 2) -> str:
    """A figure with a true minus, or the words for none."""
    if value is None:
        return NO_DATA
    return f"{MINUS if value < 0 else ''}{abs(value):,.{places}f}"


def pct(value, places: int = 0) -> str:
    return NO_DATA if value is None else f"{value * 100:.{places}f}%"


# --- dates -----------------------------------------------------------------------------
def _year_month(text):
    """(year, month) of "2027-01" or "2027-01-15", or None."""
    m = re.match(r"(\d{4})-(\d{2})", str(text or ""))
    if not m or not 1 <= int(m[2]) <= 12:
        return None
    return int(m[1]), int(m[2])


def month_text(text) -> str:
    """"Jan 2027" for a date the registry gives to the month or the day."""
    ym = _year_month(text)
    return f"{MON[ym[1] - 1]} {ym[0]}" if ym else ""


def day_text(text) -> str:
    """"14 Feb 2029" for a date the registry gives to the day, else the month."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(text or ""))
    if m and 1 <= int(m[2]) <= 12:
        return f"{int(m[3])} {MON[int(m[2]) - 1]} {m[1]}"
    return month_text(text)


def how_far(text, today: dt.date) -> str:
    """How far off a dated event is, to the month: "in 2 months", "this month", or that
    the date has passed. Empty where there is no date."""
    ym = _year_month(text)
    if not ym:
        return ""
    months = (ym[0] - today.year) * 12 + ym[1] - today.month
    if months < 0:
        return "date passed"
    if months == 0:
        return "this month"
    if months == 1:
        return "in 1 month"
    if months < 24:
        return f"in {months} months"
    years = f"{months / 12:.1f}".rstrip("0").rstrip(".")
    return f"in {years} years"


# --- the phase track -------------------------------------------------------------------
def phase_position(phase):
    """Where a phase stands on the four steps, 1 to 4, a seamless phase at the half, or
    None for anything the track does not hold (a Phase 4, a stage named in a filing)."""
    text = str(phase or "").strip()
    if text.lower() in ("filed", "fda review", "nda", "bla"):
        return 4.0
    m = re.fullmatch(r"Phase (\d)(?:/(\d))?", text)
    if not m:
        return None
    first, second = int(m[1]), int(m[2]) if m[2] else None
    at = (first + second) / 2 if second else float(first)
    return at if 1 <= at <= 3 else None


def phase_track_html(phase) -> str:
    """Four steps with the ones reached filled. A seamless phase fills the step it has
    left and half-fills the one it is running into. A phase off the track prints as
    words: no step is filled on a guess."""
    at = phase_position(phase)
    if at is None:
        return f'<div class="pc-stage">{esc(phase or "phase not stated")}</div>'
    parts = []
    for i, (name, short) in enumerate(STEPS, 1):
        state = "on" if i <= at else "half" if i - 0.5 == at else ""
        if i > 1:
            parts.append(f'<span class="l {state}"></span>')
        parts.append(f'<span class="n {state}" title="{esc(name)}"><i></i><b>{short}</b></span>')
    return (f'<div class="pc-track" role="img" aria-label="{esc(phase)}">'
            f'{"".join(parts)}</div>')


# --- the studies -----------------------------------------------------------------------
def studies_summary(studies) -> dict:
    """{"n", "enrolling", "patients"} of a compound's studies. Patients is the enrolment
    the registry lists, planned or actual, summed over the studies that state one, and
    None where none does."""
    studies = studies or []
    sizes = [s.get("enrollment") for s in studies
             if isinstance(s.get("enrollment"), (int, float)) and s.get("enrollment")]
    return {"n": len(studies),
            "enrolling": sum(1 for s in studies
                             if str(s.get("status") or "").strip().lower() in ENROLLING),
            "patients": int(sum(sizes)) if sizes else None}


def studies_line(studies) -> str:
    s = studies_summary(studies)
    if not s["n"]:
        return ""
    parts = [f'{s["n"]} {"trial" if s["n"] == 1 else "trials"}']
    if s["enrolling"]:
        parts.append(f'{s["enrolling"]} enrolling')
    if s["patients"]:
        parts.append(f'{s["patients"]:,} patients')
    return " · ".join(parts)


# --- the book --------------------------------------------------------------------------
def book_from_verdict(verdict) -> dict:
    """{asset id: what the book says of it} from the forecast verdict.

    ``state`` is "valued" for a line the forecast carries, "held" for one run on a
    placeholder curve and left out of the company's total, and "refused" for one the
    engine would not run, with the inputs it lacked. A compound in none of the three is
    not in the dict: the book has not looked at it.
    """
    verdict = verdict or {}
    shares = verdict.get("diluted_shares") or 0
    out = {}
    for m in verdict.get("refused") or []:
        if m.get("asset_id"):
            out[m["asset_id"]] = {"state": "refused", "missing": m.get("missing") or []}
    for m in verdict.get("placeholders") or []:
        if m.get("asset_id"):
            share = m.get("rnpv_share")
            out[m["asset_id"]] = {
                "state": "held",
                "per_share": share * 1e6 / shares if share is not None and shares else None}
    for m in verdict.get("modelled") or []:
        if m.get("asset_id"):
            out[m["asset_id"]] = {
                "state": "valued", "per_share": m.get("per_share"), "pos": m.get("pos"),
                "pass": m.get("per_share_success"), "miss": m.get("per_share_failure"),
                "gate": m.get("gate") or {}, "marketed": bool(m.get("is_marketed")),
                "launch": m.get("launch")}
    return out


# The odds' colour by band: green from even odds, amber from one in five, red below. A way
# of reading the book's own probability at a glance, not a finding about the compound:
# most Phase 1 work sits in red and most Phase 3 work in green because that is where the
# base rates put them.
ODDS_BANDS = ((0.5, "hi"), (0.2, "mid"))
ODDS_TIP = ("The book's probability the compound reaches the market. Green from 50%, "
            "amber from 20%, red below.")
# The launch floor's tone, as the Forecast and Catalysts tabs read it (``_launch_flag`` in
# streamlit_app.py): red where the model launches before the earliest approval the registry
# and the FDA clock allow, amber where the seed cites a reason for doing so.
LAUNCH_TONES = {"before_floor": "red", "before_floor_cited": "amber"}


def odds_band(pos) -> str:
    """"hi", "mid" or "lo" for a probability, or "" for none."""
    if pos is None:
        return ""
    return next((band for floor, band in ODDS_BANDS if pos >= floor), "lo")


def launch_tone(launch) -> str:
    """"red", "amber" or "" for a valued line's launch floor."""
    if not isinstance(launch, dict):
        return ""
    tone = launch.get("flag") or LAUNCH_TONES.get(launch.get("status"), "")
    return tone if tone in ("red", "amber") else ""


def _value_block(b) -> str:
    """One line: the book's odds, coloured by band, and its value a share in small type, or
    why the book has no figure."""
    if not b:
        return ('<div class="pc-book"><span class="v none" title="The forecast holds no '
                'line for this compound.">not modelled</span></div>')
    if b["state"] == "refused":
        lacks = ", ".join(str(x) for x in b.get("missing") or []) or "inputs"
        return (f'<div class="pc-book"><span class="v none" '
                f'title="{esc("The forecast would not run it. It lacks: " + lacks)}">'
                f'not valued</span></div>')
    value = b.get("per_share")
    if b["state"] == "held":
        return (f'<div class="pc-book"><span class="v none" '
                f'title="Run on a placeholder curve and left out of the company total.">'
                f'{esc(num(value))} held</span></div>')
    pos = b.get("pos")
    odds = (f'<span class="k">odds</span><span class="odds {odds_band(pos)}" '
            f'title="{esc(ODDS_TIP)}">{esc(pct(pos))}</span>' if pos is not None else "")
    legs = ""
    if b.get("pass") is not None and b.get("miss") is not None:
        legs = (f' title="{esc(num(b["pass"]))} a share if the next gate passes, '
                f'{esc(num(b["miss"]))} if it fails."')
    figure = esc(num(value))
    tone = launch_tone(b.get("launch"))
    if tone:
        message = str((b.get("launch") or {}).get("message") or "")
        tip = f' title="{esc(message)}"' if message else ""
        figure = f'<span class="lf {tone}"{tip}>{figure}</span>'
    return (f'<div class="pc-book">{odds}<span class="sv"{legs}>{figure}'
            f'<em>a share</em></span></div>')


# --- completion dates that moved --------------------------------------------------------
def _months_between(was, now):
    a, b = _year_month(was), _year_month(now)
    if not a or not b:
        return None
    return (b[0] - a[0]) * 12 + b[1] - a[1]


def moved_by_asset(slips, trials) -> dict:
    """{asset id: the moved completion dates of its studies}, the largest move first.

    ``slips`` are ``dates_view.slip_rows`` (one a study, first date to last) and ``trials``
    the company's registry studies, which carry the compound each is bound to. A study
    bound to no compound has no card to sit on and is left out here; the caller counts it.
    """
    owner = {t.get("nct_id"): t for t in trials or [] if t.get("asset_id") is not None}
    out: dict = {}
    for s in slips or []:
        t = owner.get(s.get("nct"))
        if t is None:
            continue
        out.setdefault(t["asset_id"], []).append({**s, "phase": t.get("phase")})
    for rows in out.values():
        rows.sort(key=lambda r: -abs(r.get("days") or 0))
    return out


def _moved_tip(rows) -> str:
    lines = [f'{r["nct"]}{" (" + r["phase"] + ")" if r.get("phase") else ""}: '
             f'{month_text(r["was"])} to {month_text(r["now"])}'
             f'{" over " + str(r["moves"]) + " moves" if r.get("moves", 1) > 1 else ""}'
             for r in rows]
    return ("Estimated primary completion moved in the registry: " + "; ".join(lines)
            + ". A registry estimate, not a result date.")


def _moved_html(rows) -> str:
    """The largest move of a study date as a line on the card, with every move in the
    tooltip. A date pushed later is in the flag colour; one brought forward is muted."""
    if not rows:
        return ""
    r = rows[0]
    months = _months_between(r["was"], r["now"])
    days = r.get("days") or 0
    later = days > 0
    sign = "+" if later else MINUS
    if months:
        shift = f'{"+" if months > 0 else MINUS}{abs(months)} mo'
        was, now = month_text(r["was"]), month_text(r["now"])
    else:
        # A move inside one month: the days say it, and the dates go to the day where the
        # registry gives one, so the line does not read as a date moved to itself.
        shift = f"{sign}{abs(days)} days" if days else ""
        was, now = day_text(r["was"]), day_text(r["now"])
    more = f' <span class="more">+{len(rows) - 1} more</span>' if len(rows) > 1 else ""
    return (f'<div class="pc-moved {"later" if later else "earlier"}" '
            f'title="{esc(_moved_tip(rows))}"><span class="k">date moved</span>'
            f'<span class="v">{esc(was)} → {esc(now)}</span>'
            f'<span class="far">{esc(shift)}</span>{more}</div>')


# --- the pipeline card -----------------------------------------------------------------
OVERDUE_TIP = "The registry date has passed and no readout is on file."


def next_event(programme, b) -> tuple:
    """(what, when, overdue) of the compound's next dated event: the gate the book prices,
    where it has one with a date, else the next study the registry dates. Overdue is the
    forecast's own word for a gate whose registry date has passed with no readout on
    file, which a date in the current month cannot say for itself."""
    gate = (b or {}).get("gate") or {}
    if gate.get("date"):
        return gate.get("label") or "next gate", gate["date"], bool(gate.get("due"))
    if programme.get("next_readout"):
        return "next study due", programme["next_readout"], False
    return "", None, False


def _far(when, overdue: bool, today: dt.date) -> tuple:
    """(words, whether the date is one to go and check)."""
    if overdue:
        return "overdue", True
    words = how_far(when, today)
    return words, words == "date passed"


def pipeline_card_html(programme, b, today: dt.date, moved=None) -> str:
    """One compound: its name and area, the phase track, the next event and how far off it
    is, any study date that moved, the book's odds and value, and its studies counted with
    the registry's next due date where the next event shown is the book's gate."""
    areas = programme.get("areas") or []
    filing = programme.get("source") == "filing"
    area = (programme.get("indication") if filing else (areas[0] if areas else "")) or ""
    more = f" +{len(areas) - 1}" if len(areas) > 1 and not filing else ""
    if filing:
        # Named in a filing, with no registered study: the stage is the filer's sentence,
        # so it prints as words and never as a step of the track.
        where = (f'<div class="pc-stage" title="{esc(programme.get("evidence"))}">'
                 f'{esc(programme.get("stage") or "named in the filing")}</div>')
        foot = (f'{esc(programme.get("form_type") or "filing")} '
                f'{esc(str(programme.get("filed_date") or "")[:10])}').strip()
    else:
        where = phase_track_html(programme.get("phase"))
        foot = esc(studies_line(programme.get("studies")))
    what, when, overdue = next_event(programme, b)
    due = programme.get("next_readout")
    if not filing and due and when and when != due:
        # The gate leads the card, so the registry's own next date goes in the foot.
        foot = " · ".join(x for x in (foot, f"next study {esc(month_text(due))}") if x)
    if when:
        far, late = _far(when, overdue, today)
        tip = f' title="{OVERDUE_TIP}"' if overdue else ""
        nxt = (f'<div class="pc-next"><span class="k">{esc(what)}</span>'
               f'<span class="v">{esc(month_text(when))}</span>'
               f'<span class="far{" late" if late else ""}"{tip}>{esc(far)}</span></div>')
    else:
        nxt = ('<div class="pc-next"><span class="k">next</span>'
               '<span class="v none">no date on file</span></div>')
    return (f'<div class="pf-card pc pipe">'
            f'<div class="pf-head"><span class="pf-brand">{esc(programme.get("name"))}</span>'
            f'<span class="pf-mod">{esc(programme.get("modality") or "")}</span></div>'
            f'<div class="pf-generic" title="{esc(", ".join(areas))}">{esc(area)}{esc(more)}</div>'
            f'{where}{nxt}{_moved_html(moved)}{_value_block(b)}'
            f'<div class="pc-foot">{foot}</div></div>')


def pipeline_order(programmes, book) -> list:
    """Most valuable first, then soonest: the compounds the book prices lead, and among
    the rest the one with the nearest dated study."""
    def key(p):
        value = (book.get(p.get("asset_id")) or {}).get("per_share")
        return (value is None, -(value or 0), p.get("next_readout") or "9999",
                str(p.get("name") or "").lower())
    return sorted(programmes, key=key)


def pipeline_summary(programmes, book, today: dt.date) -> dict:
    """The pipeline side's four figures: compounds, how many the book values and at what
    a share, how many are in late-stage study, and the next dated study still ahead."""
    valued = [book[p["asset_id"]]["per_share"] for p in programmes
              if (book.get(p.get("asset_id")) or {}).get("state") == "valued"
              and book[p["asset_id"]].get("per_share") is not None]
    this_month = f"{today.year:04d}-{today.month:02d}"
    ahead = sorted((p["next_readout"][:7], str(p.get("name") or "")) for p in programmes
                   if p.get("next_readout") and p["next_readout"][:7] >= this_month)
    return {"n": len(programmes), "n_valued": len(valued),
            "value": sum(valued) if valued else None,
            "late": sum(1 for p in programmes if (phase_position(p.get("phase")) or 0) >= 2.5),
            "next": ahead[0] if ahead else None}


# --- the disease areas, as a ring --------------------------------------------------------
NO_AREA = "Area not stated"
PIE_SIZE = 196


def lead_area(programme) -> str:
    """The area a compound is counted under: the first the registry gives it, which is the
    one its card names and its area pill files it by, so the ring, the pills and the cards
    count a compound once and in the same place."""
    return ((programme.get("areas") or [])[:1] or [NO_AREA])[0]


def area_counts(programmes, group) -> list:
    """[(area, compounds, {phase heading: compounds})], largest first, the unstated area
    last. ``group`` is the caller's rule for a compound's phase heading."""
    out: dict = {}
    for p in programmes or []:
        a = lead_area(p)
        n, phases = out.get(a, (0, {}))
        g = group(p)
        phases[g] = phases.get(g, 0) + 1
        out[a] = (n + 1, phases)
    return sorted(((a, n, ph) for a, (n, ph) in out.items()),
                  key=lambda r: (r[0] == NO_AREA, -r[1], r[0]))


def _arc(cx, cy, r_out, r_in, a0, a1) -> str:
    def pt(r, a):
        return cx + r * math.cos(a), cy + r * math.sin(a)
    large = 1 if a1 - a0 > math.pi else 0
    x0, y0 = pt(r_out, a0)
    x1, y1 = pt(r_out, a1)
    x2, y2 = pt(r_in, a1)
    x3, y3 = pt(r_in, a0)
    return (f"M{x0:.2f},{y0:.2f} A{r_out},{r_out} 0 {large} 1 {x1:.2f},{y1:.2f} "
            f"L{x2:.2f},{y2:.2f} A{r_in},{r_in} 0 {large} 0 {x3:.2f},{y3:.2f} Z")


def area_pie_html(rows, colours: dict, order=(), short=None) -> str:
    """The compounds by disease area as a ring with its key beside it. Hovering a wedge or
    a row of the key names the area in the middle of the ring with how many compounds it
    holds and how they stand by phase; nothing hovered, the middle holds the total.

    ``rows`` are ``area_counts``; ``colours`` {area: colour} and ``order`` the phase
    headings in the order the breakdown reads. The hover is the stylesheet's (``.apie``),
    so the ring needs no script. Empty where there is nothing to draw.
    """
    short = short or {}
    rows = [r for r in rows or [] if r[1] > 0]
    total = sum(r[1] for r in rows)
    if not total:
        return ""
    size = PIE_SIZE
    c = size / 2
    r_out, r_in = c - 4, round((c - 4) * 0.64, 1)
    wedges, keys = [], []
    angle = -math.pi / 2

    def breakdown(phases) -> str:
        known = [g for g in order if g in phases] + [g for g in phases if g not in order]
        return " · ".join(f"{phases[g]} {g.replace('Phase ', 'Ph ')}" for g in known)

    for i, (area, n, phases) in enumerate(rows):
        sweep = n / total * math.tau
        colour = colours.get(area, "var(--rule-strong)")
        if sweep >= math.tau - 1e-6:
            # A whole ring cannot be one arc: two halves.
            path = (_arc(c, c, r_out, r_in, angle, angle + math.pi) + " "
                    + _arc(c, c, r_out, r_in, angle + math.pi, angle + math.tau))
        else:
            path = _arc(c, c, r_out, r_in, angle, angle + sweep)
        angle += sweep
        name = short.get(area, area)
        word = "compound" if n == 1 else "compounds"
        wedges.append(
            f'<g class="s" data-i="{i}"><path d="{path}" fill="{esc(colour)}"/>'
            f'<title>{esc(area)}: {n} {word} ({n / total * 100:.0f}%). {esc(breakdown(phases))}</title>'
            f'<text class="ct n" x="{c}" y="{c - 6}">{n}</text>'
            f'<text class="ct a" x="{c}" y="{c + 10}">{esc(name)}</text>'
            f'<text class="ct b" x="{c}" y="{c + 24}">{esc(breakdown(phases))}</text></g>')
        keys.append(
            f'<div class="kr" data-i="{i}" title="{esc(breakdown(phases))}">'
            f'<i style="background:{esc(colour)}"></i><span class="l">{esc(area)}</span>'
            f'<span class="c">{n}</span></div>')
    centre = (f'<g class="c0"><text class="n" x="{c}" y="{c - 2}">{total}</text>'
              f'<text class="a" x="{c}" y="{c + 14}">compounds</text></g>')
    return (f'<div class="apie"><svg viewBox="0 0 {size} {size}" width="{size}" '
            f'height="{size}" role="img" aria-label="Compounds by disease area">'
            f'{"".join(wedges)}{centre}</svg><div class="apie-key">{"".join(keys)}</div></div>')


# --- the studies, in full ---------------------------------------------------------------
def studies_table_html(studies, today: dt.date, moved=None) -> str:
    """Studies as a table, soonest first: when each is due, its phase, its status, its
    patients and its registry title, linked. One builder for a compound's dialog and a
    marketed product's, so a study reads the same way on both. A study whose date moved
    (``moved``, the rows of ``moved_by_asset``) says under its date what it was."""
    studies = sorted(studies or [],
                     key=lambda s: (not s.get("due"), s.get("due") or "", s.get("nct_id") or ""))
    was = {r.get("nct"): r for r in moved or []}
    rows = []
    this_month = (today.year, today.month)
    for s in studies:
        size = s.get("enrollment")
        # A study still open whose registry date is behind today is the one to look
        # up: it has read out and the registry has not caught up, or it has slipped.
        due = _year_month(s.get("due"))
        late = (due is not None and due < this_month
                and str(s.get("status") or "").strip().lower() != "completed")
        tip = ' title="Past its registry date and still open."' if late else ""
        tail = " · ".join(str(x) for x in (s.get("nct_id"), s.get("area")) if x)
        m = was.get(s.get("nct_id"))
        prior = (f'<span class="was" title="{esc(_moved_tip([m]))}">was '
                 f'{esc(month_text(m["was"]))}</span>' if m else "")
        rows.append(
            f'<tr><td class="d{" late" if late else ""}"{tip}>'
            f'{esc(month_text(s.get("due")) or "no date")}{prior}</td>'
            f'<td>{esc(s.get("phase") or "")}</td>'
            f'<td>{esc(s.get("status") or "")}</td>'
            f'<td class="n">{f"{int(size):,}" if isinstance(size, (int, float)) and size else NO_DATA}</td>'
            f'<td class="t"><a href="https://clinicaltrials.gov/study/{esc(s.get("nct_id"))}" '
            f'target="_blank" rel="noopener">{esc(s.get("title") or s.get("nct_id"))}</a>'
            f'<span>{esc(tail)}</span></td></tr>')
    return ('<table class="pt-tbl"><thead><tr><th>Due</th><th>Phase</th><th>Status</th>'
            '<th class="n">Patients</th><th>Study</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def completed_table_html(trials) -> str:
    """Studies that have finished and posted results, newest first: when each completed,
    its phase, its patients, its title linked to the registry's results, and the primary
    outcome the registry names, under the title."""
    rows = []
    for t in sorted(trials or [], key=lambda t: t.get("completion_date") or "", reverse=True):
        size = t.get("enrollment")
        outcome = str(t.get("primary_outcome") or "").strip()
        said = " · primary outcome: " + outcome if outcome else ""
        rows.append(
            f'<tr><td class="d">{esc(month_text(t.get("completion_date")) or "no date")}</td>'
            f'<td>{esc(t.get("phase") or "")}</td>'
            f'<td class="n">{f"{int(size):,}" if isinstance(size, (int, float)) and size else NO_DATA}</td>'
            f'<td class="t"><a href="https://clinicaltrials.gov/study/{esc(t.get("nct_id"))}?tab=results" '
            f'target="_blank" rel="noopener">{esc(t.get("title") or t.get("nct_id"))}</a>'
            f'<span>{esc(t.get("nct_id"))}{esc(said)}</span></td></tr>')
    return ('<table class="pt-tbl done"><thead><tr><th>Completed</th><th>Phase</th>'
            '<th class="n">Patients</th><th>Study and primary outcome</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def bars_html(rows) -> str:
    """A figure a period as a row with its bar, on the block's own scale: [(label, the
    figure as printed, the figure)]. A row with no figure is left out, and a negative one
    is printed with no bar, since a length cannot be less than nothing."""
    rows = [r for r in rows or [] if r[2] is not None]
    if not rows:
        return ""
    top = max((r[2] for r in rows), default=0) or 1.0
    out = []
    for label, shown, value in rows:
        width = max(0.0, value) / top * 100 if top > 0 else 0.0
        out.append(f'<div class="pb-r"><span class="l">{esc(label)}</span>'
                   f'<span class="b"><i style="width:{width:.1f}%"></i></span>'
                   f'<span class="v">{esc(shown)}</span></div>')
    return f'<div class="pb">{"".join(out)}</div>'


def trials_facts_html(programme, b, today: dt.date) -> str:
    """A compound's dialog head. Its studies follow as a table, soonest first: when each is due, its phase, its
    status, its patients and its registry title, linked. Above them, what the card said,
    with the reason the book has no figure where it has none and the launch floor's
    message where the value carries one."""
    what, when, overdue = next_event(programme, b)
    facts = [("phase", esc(programme.get("phase") or programme.get("stage") or NO_DATA))]
    if when:
        far = "overdue, no readout on file" if overdue else how_far(when, today)
        facts.append((what, f"{esc(month_text(when))} · {esc(far)}"))
    if b and b.get("state") == "valued":
        facts.append(("odds", esc(pct(b.get("pos")))))
        facts.append(("value", f"{esc(num(b.get('per_share')))} a share"))
        if b.get("pass") is not None and b.get("miss") is not None:
            facts.append(("if the next gate passes", f"{esc(num(b['pass']))} a share"))
            facts.append(("if it fails", f"{esc(num(b['miss']))} a share"))
        if launch_tone(b.get("launch")) and (b.get("launch") or {}).get("message"):
            facts.append(("launch", esc(b["launch"]["message"])))
    elif b and b.get("state") == "held":
        facts.append(("value", f"{esc(num(b.get('per_share')))} a share, held: run on a "
                               "placeholder curve and left out of the company total"))
    elif b and b.get("state") == "refused":
        lacks = ", ".join(str(x) for x in b.get("missing") or []) or "inputs"
        facts.append(("value", f"not valued: the forecast lacks {esc(lacks)}"))
    else:
        facts.append(("value", "not modelled: no assumptions on file"))
    head = "".join(f'<div><span class="k">{esc(k)}</span><span class="v">{v}</span></div>'
                   for k, v in facts)
    return f'<div class="pt-facts">{head}</div>'


def trials_body_html(programme, today: dt.date, moved=None) -> str:
    """The compound's registry studies under their count, soonest first."""
    studies = programme.get("studies") or []
    body = (studies_table_html(studies, today, moved) if studies else
            '<div class="pt-none">No registered study is bound to this compound.</div>')
    line = studies_line(programme.get("studies"))
    return f'<div class="pt-count">{esc(line)}</div>{body}'


def trials_html(programme, b, today: dt.date, moved=None) -> str:
    """The dialog's facts over the compound's studies, as one piece of markup."""
    return trials_facts_html(programme, b, today) + trials_body_html(programme, today, moved)


# --- the marketed card -----------------------------------------------------------------
def history(rows, asset_id, years: int = HISTORY_YEARS) -> list:
    """[(fiscal year, revenue)] for one product, oldest first, the last few years on file.
    A year with no figure is left out, never carried as nought."""
    points = sorted((r["fiscal_year"], r["value"]) for r in rows or []
                    if r.get("asset_id") == asset_id and r.get("value") is not None
                    and r.get("fiscal_year") is not None)
    return points[-years:]


def growth(points):
    """The latest year on the one before it, where the two are consecutive and the earlier
    is positive, else None: a rate over a gap is not a year's growth."""
    if len(points) < 2:
        return None
    (y0, v0), (y1, v1) = points[-2], points[-1]
    if y1 - y0 != 1 or not v0 or v0 <= 0:
        return None
    return v1 / v0 - 1


def history_html(points, unit: str = "") -> str:
    """A column a year, the latest marked. Nothing for a single year: one column says no
    more than the figure beside it."""
    if len(points) < 2:
        return ""
    top = max(v for _y, v in points) or 1.0
    said = " · ".join(f"FY{y} {v / 1e9:,.2f}" for y, v in points) + f" {unit} bn".rstrip()
    bars = "".join(
        f'<i class="{"now" if i == len(points) - 1 else ""}" '
        f'style="height:{max(2.0, max(v, 0) / top * HISTORY_H):.1f}px"></i>'
        for i, (_y, v) in enumerate(points))
    return f'<span class="pc-hist" role="img" aria-label="{esc(said)}" title="{esc(said)}">{bars}</span>'


def runway_html(years_left, book: str = "", near: bool = False, earliest_left=None) -> str:
    """The years of exclusivity left as a bar on the common scale. Where a small molecule
    has a window of patents, the bar is solid to the earliest and lighter to the latest,
    since a generic can challenge its way to the earlier date. Nothing where there is no
    date: an empty bar would say the protection is gone, which is a different fact."""
    if years_left is None:
        return ""
    full = max(0.0, min(years_left, RUNWAY_YEARS)) / RUNWAY_YEARS * 100
    solid = full
    if earliest_left is not None and earliest_left < years_left:
        solid = max(0.0, min(earliest_left, RUNWAY_YEARS)) / RUNWAY_YEARS * 100
    cls = "pc-run" + (f" {book}" if book else "") + (" near" if near else "")
    window = (f'<i class="w" style="left:{solid:.1f}%;width:{full - solid:.1f}%"></i>'
              if full > solid else "")
    return (f'<span class="{cls}" role="img" aria-label="{years_left} years of exclusivity left, '
            f'on a scale of {RUNWAY_YEARS}"><i class="f" style="width:{solid:.1f}%"></i>{window}</span>')


def marketed_card_html(d: dict) -> str:
    """One marketed product from the facts the tab has already worked out.

    ``d`` carries the words the tab decides (what the exclusivity line is called, whether
    the date is a range, why there is none) with their tooltips, so the card draws and
    judges nothing: brand, generic, modality, area, book ("small" or "bio"), shelved,
    chip_html, approved, revenue, revenue_unit, revenue_tip, share, points, loe_label,
    loe_text, loe_tip, years_left, earliest_left, near, note, note_tip, modality_tip,
    value, moved (the rows of ``moved_by_asset`` for its studies).
    """
    points = d.get("points") or []
    rate = growth(points)
    revenue = d.get("revenue")
    if revenue is not None:
        share = (f'<span class="sh" title="Of the company\'s tagged product revenue.">'
                 f'{esc(pct(d["share"]))} of revenue</span>' if d.get("share") else "")
        moved = ""
        if rate is not None:
            sign = "+" if rate >= 0 else MINUS
            moved = (f'<span class="g {"up" if rate >= 0 else "dn"}" title="Latest fiscal year '
                     f'on the one before.">{sign}{abs(rate) * 100:.0f}%</span>')
        money = (f'<span class="v strong">{revenue / 1e9:,.2f}<em>{esc(d.get("revenue_unit") or "")} bn</em>'
                 f'</span>{moved}{share}')
    else:
        money = f'<span class="v none">{NO_DATA}</span>'
    run = runway_html(d.get("years_left"), d.get("book") or "", bool(d.get("near")),
                      d.get("earliest_left"))
    note = (f'<div class="pc-note" title="{esc(d.get("note_tip"))}">{esc(d.get("note"))}</div>'
            if d.get("note") else "")
    value = (f'<span title="What the forecast values the product at.">book '
             f'{esc(num(d["value"]))} a share</span>' if d.get("value") is not None else "")
    approved = f'approved {esc(str(d["approved"])[:4])}' if d.get("approved") else ""
    foot = " · ".join(x for x in (approved, value) if x)
    cls = "pf-card pc mkt" + (f' {d["book"]}' if d.get("book") else "") + (
        " shelved" if d.get("shelved") else "")
    area = f' · {esc(d["area"])}' if d.get("area") else ""
    return (f'<div class="{cls}">'
            f'<div class="pf-head"><span class="pf-brand">{esc(d.get("brand"))}</span>'
            f'<span class="pf-mod" title="{esc(d.get("modality_tip"))}">'
            f'{esc(d.get("modality") or "")}</span></div>'
            f'<div class="pf-generic">{esc(d.get("generic") or "")}{area}</div>'
            f'{d.get("chip_html") or ""}'
            f'<div class="pc-rev" title="{esc(d.get("revenue_tip"))}"><span class="k">revenue</span>{money}{history_html(points, d.get("revenue_unit") or "")}</div>'
            f'<div class="pc-loe" title="{esc(d.get("loe_tip"))}"><span class="k">{esc(d.get("loe_label"))}</span>'
            f'<span class="v{" near" if d.get("near") else ""}">{esc(d.get("loe_text"))}</span>{run}</div>'
            f'{note}{_moved_html(d.get("moved"))}<div class="pc-foot">{foot}</div></div>')


# --- a completed study, clicked open -------------------------------------------------------
TONE_WORD = {"good": "green", "bad": "red", "neutral": "grey"}


def nct_id_number(nct) -> int | None:
    """The number in an NCT id, the id a clicked row returns."""
    m = re.fullmatch(r"NCT(\d{8})", str(nct or "").strip().upper())
    return int(m[1]) if m else None


def completed_studies(trials, programme=None) -> list:
    """A compound's completed studies: the book's completed studies of it and any of its
    registry studies whose status is completed or terminated, each once, newest first."""
    out = {t["nct_id"]: dict(t) for t in trials or [] if t.get("nct_id")}
    for s in (programme or {}).get("studies") or []:
        status = str(s.get("status") or "").strip().lower()
        if s.get("nct_id") and status in ("completed", "terminated") and s["nct_id"] not in out:
            out[s["nct_id"]] = {"nct_id": s["nct_id"], "title": s.get("title"),
                                "phase": s.get("phase"), "completion_date": s.get("due"),
                                "enrollment": s.get("enrollment"), "has_results": None}
    dated = sorted((t for t in out.values() if t.get("completion_date")),
                   key=lambda t: str(t["completion_date"]), reverse=True)
    return dated + [t for t in out.values() if not t.get("completion_date")]


def completed_label(t) -> str:
    """A past study as the selector lists it: when it completed, its phase, its
    participants, its title, and whether the sponsor has posted results."""
    size = t.get("enrollment")
    posted = t.get("has_results")
    tail = ("results posted" if posted else "no results posted" if posted is False
            else "results not fetched")
    title = str(t.get("title") or t.get("nct_id") or "")
    title = title if len(title) <= 90 else title[:89].rstrip() + "…"
    parts = [month_text(t.get("completion_date")) or "no date", t.get("phase") or "",
             f"{int(size):,} participants" if isinstance(size, (int, float)) and size else "",
             title, tail]
    return " · ".join(p for p in parts if p)


def _count(v) -> str:
    return f"{int(v):,}" if isinstance(v, (int, float)) and v else ""


def _pct_text(v) -> str:
    return NO_DATA if v is None else f"{v:.1f}%"


def _role_tag(role) -> str:
    if role in ("placebo", "control", "comparator"):
        return f' <span class="tr-role ref">{esc(role)}</span>'
    if role == "drug":
        return ' <span class="tr-role">drug</span>'
    return ""


def trial_report_html(r: dict) -> str:
    """A completed study read from what its sponsor posted (``/trials/{nct}/report``): the
    scorecard, the results in words, the primary endpoint by arm with every comparison,
    safety by arm with the commonest adverse events, the company's own words on it, and
    the points to weigh. Every figure is the payload's own."""
    s = r.get("study") or {}
    nct = s.get("nct_id") or ""
    facts = [s.get("phase"), f'{s["enrollment"]:,} participants' if s.get("enrollment") else None,
             (s.get("status") or "").lower() or None,
             f'primary completion {month_text(s.get("primary_completion_date"))}'
             if s.get("primary_completion_date") else None,
             f'results posted {month_text(r.get("results_date"))}' if r.get("results_date") else
             ("results not fetched" if r.get("fetched") is False else
              "no results posted" if not r.get("has_results") else None)]
    link = (f'<a href="https://clinicaltrials.gov/study/{esc(nct)}?tab=results" target="_blank" '
            f'rel="noopener">{esc(nct)} on the registry</a>')
    head = (f'<div class="tr-title">{esc(s.get("title") or nct)}</div>'
            f'<div class="tr-head">{esc(" · ".join(x for x in facts if x))} · {link}</div>')
    card = "".join(
        f'<div class="tr-row {esc(c.get("tone") or "neutral")}" title="{esc(TONE_WORD.get(c.get("tone"), ""))}">'
        f'<i></i><span class="k">{esc(c.get("k"))}</span>'
        f'<span class="v">{esc(c.get("verdict"))}</span>'
        f'<span class="t">{esc(c.get("text"))}</span></div>' for c in r.get("scorecard") or [])
    parts = [head, f'<div class="tr-sub">Clinical scorecard</div><div class="tr-card">{card}</div>',
             f'<div class="tr-sub">Summary of the results</div><p class="tr-sum">{esc(r.get("summary"))}</p>']
    left = []
    primary = r.get("primary") or []
    titles = {}
    if primary:
        p = primary[0]
        for row in p.get("rows") or []:
            titles[row.get("group_id")] = row.get("group_title")
        body = "".join(
            f'<tr><td>{esc(row.get("group_title"))}{_role_tag(row.get("role"))}'
            f'{" · " + esc(row["category"]) if row.get("category") else ""}</td>'
            f'<td class="n">{esc(num(row["value"]) if row.get("value") is not None else (row.get("value_text") or NO_DATA))}</td>'
            f'<td class="n">{esc(num(row["spread"]) if row.get("spread") is not None else "")}</td>'
            f'<td class="n">{_count(row.get("n"))}</td></tr>'
            for row in p.get("rows") or [])
        left.append(f'<div class="tr-sub">Primary endpoint</div>'
                    f'<div class="tr-what">{esc(p.get("title"))}'
                    f'{" · " + esc(p["time_frame"]) if p.get("time_frame") else ""}'
                    f'{" · " + esc(p["unit"]) if p.get("unit") else ""}</div>'
                    '<table class="pt-tbl tr-tbl"><thead><tr><th>Arm</th><th class="n">Value</th>'
                    '<th class="n">Spread</th><th class="n">Analysed</th></tr></thead>'
                    f'<tbody>{body}</tbody></table>')
        comps = r.get("comparisons") or []
        if comps:
            crow = "".join(
                f'<tr><td>{esc(" against ".join(str(titles.get(g, g)) for g in c.get("groups") or []))}</td>'
                f'<td>{esc(c.get("param_type") or "")}</td>'
                f'<td class="n">{esc(num(c.get("value")) if c.get("value") is not None else NO_DATA)}</td>'
                f'<td class="n">{esc(num(c["lo"]) + " to " + num(c["hi"]) if c.get("lo") is not None and c.get("hi") is not None else "")}</td>'
                f'<td class="n">{esc(c.get("p_value") or "not posted")}</td></tr>' for c in comps)
            left.append('<div class="tr-sub">The sponsor\'s comparisons</div>'
                        '<table class="pt-tbl tr-tbl"><thead><tr><th>Arms</th><th>Measure</th>'
                        '<th class="n">Estimate</th><th class="n">Interval</th><th class="n">p</th>'
                        f'</tr></thead><tbody>{crow}</tbody></table>')
    right = []
    safety = r.get("safety") or []
    if safety:
        srow = "".join(
            f'<tr><td>{esc(x.get("group_title"))}{_role_tag(x.get("role"))}</td>'
            f'<td class="n">{esc(_pct_text(x.get("serious_pct")))}</td>'
            f'<td class="n">{esc(_pct_text(x.get("withdrawn_pct")))}</td>'
            f'<td class="n">{esc(str(x["deaths"]) if x.get("deaths") is not None else NO_DATA)}</td>'
            f'<td class="n">{_count(x.get("at_risk"))}</td></tr>'
            for x in safety)
        right.append('<div class="tr-sub">Safety by arm</div>'
                     '<table class="pt-tbl tr-tbl"><thead><tr><th>Arm</th>'
                     '<th class="n">Serious AEs</th><th class="n">Stopped for AE</th>'
                     '<th class="n">Deaths</th><th class="n">At risk</th></tr></thead>'
                     f'<tbody>{srow}</tbody></table>')
    events = r.get("events") or []
    if events:
        arms = [a.get("group_title") for a in (events[0].get("arms") or [])]
        erow = "".join(
            f'<tr><td>{esc(e.get("term"))}{" (serious)" if e.get("serious") else ""}</td>'
            + "".join(f'<td class="n">{esc(_pct_text(a.get("pct")))}</td>' for a in e.get("arms") or [])
            + "</tr>" for e in events)
        right.append('<div class="tr-sub">Commonest adverse events</div>'
                     '<table class="pt-tbl tr-tbl"><thead><tr><th>Event</th>'
                     + "".join(f'<th class="n" title="{esc(a)}">{esc(_short_arm(a))}</th>' for a in arms)
                     + f'</tr></thead><tbody>{erow}</tbody></table>')
    if left or right:
        parts.append(f'<div class="tr-two"><div>{"".join(left)}</div><div>{"".join(right)}</div></div>')
    said = r.get("readouts") or []
    if said:
        quotes = "".join(
            f'<div class="tr-q">“{esc(q.get("sentence"))}”<span>{esc(q.get("source") or "")}'
            f'{" · " + esc(month_text(q.get("date"))) if q.get("date") else ""}'
            f'{" · read as " + esc(q["outcome"]) if q.get("outcome") else ""}</span></div>'
            for q in said[:3])
        parts.append(f'<div class="tr-sub">In the company\'s words</div>{quotes}')
    factors = "".join(f"<li>{esc(f)}</li>" for f in r.get("factors") or [])
    parts.append(f'<div class="tr-sub">Points to weigh</div><ul class="tr-factors">{factors}</ul>')
    return f'<div class="tr">{"".join(parts)}</div>'


def _short_arm(title) -> str:
    """An arm's title cut to a column head; the full title is the head's tooltip."""
    text = str(title or "")
    return text if len(text) <= 18 else text[:17].rstrip() + "…"
