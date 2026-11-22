"""The Portfolio tab's asset cards: a marketed product and a pipeline compound, each read
at a glance.

A card was three label and value lines, the same three on all forty-four of a large
company's products, and a compound in development had no card at all: it was a row of the
Trials tab. Both are cards here and each draws the two things its kind is judged on.

A marketed product is what it earns and how long it is protected. The revenue stands
with its share of the company's tagged revenue and, where more than one year is on file,
a column for each year, so growth or decline is seen before it is read. Exclusivity is a
bar of the years left on one scale across every card, so two products can be compared by
the length of their bars without reading either date.

A compound is how far it has come and what happens next. The phase is a track of four
steps, the next event is named with how far off it is, and the book's odds and value a
share stand beside them where the book prices the compound, with the reason where it does
not. The studies are counted on the card and listed in full one click away.

Pure functions from payload rows to markup: nothing here reads a network, a clock or
Streamlit, so the caller passes today's date. A null is never drawn as a zero. Colour is
the stylesheet's, by class; the only inline styles are the lengths of the bars.
"""

from __future__ import annotations

import datetime as dt
import html
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
                "gate": m.get("gate") or {}, "marketed": bool(m.get("is_marketed"))}
    return out


def _value_block(b) -> str:
    """The card's odds and value, or why there is none."""
    if not b:
        return ('<div class="pc-f"><span class="k">value</span>'
                '<span class="v none" title="The forecast holds no line for this compound.">'
                'not modelled</span></div>')
    if b["state"] == "refused":
        lacks = ", ".join(str(x) for x in b.get("missing") or []) or "inputs"
        return (f'<div class="pc-f"><span class="k">value</span><span class="v none" '
                f'title="{esc("The forecast would not run it. It lacks: " + lacks)}">'
                f'not valued</span></div>')
    value = b.get("per_share")
    if b["state"] == "held":
        return (f'<div class="pc-f"><span class="k">value</span><span class="v none" '
                f'title="Run on a placeholder curve and left out of the company total.">'
                f'{esc(num(value))} held</span></div>')
    odds = (f'<div class="pc-f"><span class="k">odds</span><span class="v" title="The '
            f'book\'s probability the compound reaches the market.">{esc(pct(b.get("pos")))}'
            f'</span></div>' if b.get("pos") is not None else "")
    legs = ""
    if b.get("pass") is not None and b.get("miss") is not None:
        legs = (f' title="{esc(num(b["pass"]))} a share if the next gate passes, '
                f'{esc(num(b["miss"]))} if it fails."')
    return (f'{odds}<div class="pc-f"><span class="k">value</span><span class="v strong"{legs}>'
            f'{esc(num(value))}<em>a share</em></span></div>')


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


def pipeline_card_html(programme, b, today: dt.date) -> str:
    """One compound: its name and area, the phase track, the next event and how far off it
    is, the book's odds and value, and its studies counted."""
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
            f'{where}{nxt}<div class="pc-fs">{_value_block(b)}</div>'
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


# --- the studies, in full ---------------------------------------------------------------
def trials_html(programme, b, today: dt.date) -> str:
    """A compound's studies as a table, soonest first: when each is due, its phase, its
    status, its patients and its registry title, linked. Above them, what the card said."""
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
    head = "".join(f'<div><span class="k">{esc(k)}</span><span class="v">{v}</span></div>'
                   for k, v in facts)
    studies = sorted(programme.get("studies") or [],
                     key=lambda s: (not s.get("due"), s.get("due") or "", s.get("nct_id") or ""))
    if not studies:
        body = ('<div class="pt-none">No registered study is bound to this compound.</div>')
    else:
        rows = []
        this_month = (today.year, today.month)
        for s in studies:
            size = s.get("enrollment")
            # A study still open whose registry date is behind today is the one to look
            # up: it has read out and the registry has not caught up, or it has slipped.
            due = _year_month(s.get("due"))
            late = (due is not None and due < this_month
                    and str(s.get("status") or "").strip().lower() != "completed")
            rows.append(
                f'<tr><td class="d{" late" if late else ""}"'
                f'{" title=" + chr(34) + "Past its registry date and still open." + chr(34) if late else ""}>'
                f'{esc(month_text(s.get("due")) or "no date")}</td>'
                f'<td>{esc(s.get("phase") or "")}</td>'
                f'<td>{esc(s.get("status") or "")}</td>'
                f'<td class="n">{f"{int(size):,}" if isinstance(size, (int, float)) and size else NO_DATA}</td>'
                f'<td class="t"><a href="https://clinicaltrials.gov/study/{esc(s.get("nct_id"))}" '
                f'target="_blank" rel="noopener">{esc(s.get("title") or s.get("nct_id"))}</a>'
                f'<span>{esc(s.get("nct_id"))} · {esc(s.get("area") or "")}</span></td></tr>')
        body = ('<table class="pt-tbl"><thead><tr><th>Due</th><th>Phase</th><th>Status</th>'
                '<th class="n">Patients</th><th>Study</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table>')
    line = studies_line(programme.get("studies"))
    return (f'<div class="pt-facts">{head}</div>'
            f'<div class="pt-count">{esc(line)}</div>{body}')


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
    value.
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
            f'{note}<div class="pc-foot">{foot}</div></div>')
