"""The horizon rail: one persistent time spine, present in every view.

Pharma time is not linear in importance. The next 90 days are what an analyst is
positioned for, the following two years are the planning window, and everything past
that is the exclusivity cliff. So the rail carries a broken scale in three segments,
each with its own resolution, rather than one linear axis that would compress the
actionable window into a few pixels.

Ticks take the modality colour, so the rail reads as Orange Book against Purple Book.
Pure: this module builds SVG from a list of dated items and knows nothing about the API.
"""

from __future__ import annotations

import datetime as dt
import html

from theme import P

W = 208
PAD_L = 12
PAD_R = 10
# Height when a segment has items. An empty segment collapses to EMPTY_H instead:
# holding 232px of blank for a window with nothing in it reads as broken, and the
# scale only has to stay stable within a segment that actually carries ticks.
SEG = {"near": 210, "mid": 170, "cliff": 132}
EMPTY_H = 20
GAP = 30
HEAD_DROP = 22          # clear space under a segment label, so nothing collides with it
# The axis line is today and carries its own label, so day zero starts below it rather
# than on it. Without this a catalyst dated today prints straight through that label.
LEAD_IN = 13
NEAR_DAYS = 90
MID_MONTHS = 24


def _colour(item) -> str:
    if item.get("significance") == "high":
        return P.oxblood
    modality = (item.get("modality") or "").lower()
    if modality.startswith("small"):
        return P.orange_book
    if modality.startswith("bio"):
        return P.purple_book
    return P.ink


def _parse(value):
    """ISO date, or a YYYY-MM month placed at its first day.

    ClinicalTrials.gov reports some primary completion dates to the month only, and
    those are 15% of the derived readouts. Rejecting them dropped every one of those
    ticks off the rail without a word. The day is a position here, not a stored claim.
    """
    text = str(value or "")[:10]
    try:
        return dt.date.fromisoformat(text)
    except (ValueError, TypeError):
        pass
    try:
        return dt.date.fromisoformat(text[:7] + "-01")
    except (ValueError, TypeError):
        return None


def _esc(text, limit=22):
    text = str(text or "")
    return html.escape(text if len(text) <= limit else text[: limit - 1] + "…")


def _label(item) -> str:
    """Short label. The headline already names the company, so strip it back."""
    head = item.get("label") or item.get("headline") or ""
    for prefix in (" LOE: ", " PDUFA: ", " FDA approval: "):
        if prefix in head:
            head = head.split(prefix, 1)[1]
            break
    else:
        parts = head.split(" ", 1)
        head = parts[1] if len(parts) > 1 else head
    for tail in (" loses exclusivity", "):"):
        head = head.split(tail)[0]
    return head.strip()


def render(items, exclusivities=None, today=None, label_limit=7) -> str:
    """SVG for the rail.

    ``items`` are feed rows carrying date, kind, significance, and modality.
    ``exclusivities`` are the company's full LOE list, which is what reaches past the
    24 month window and forms the cliff.
    """
    today = today or dt.date.today()
    exclusivities = exclusivities or []

    near_end = today + dt.timedelta(days=NEAR_DAYS)
    mid_end = today + dt.timedelta(days=MID_MONTHS * 31)

    near, mid = [], []
    for item in items:
        when = _parse(item.get("date"))
        if when is None or when < today:
            continue          # the rail is forward-looking only
        (near if when <= near_end else mid).append((when, item))
    near.sort(key=lambda p: p[0])
    mid.sort(key=lambda p: p[0])

    # Beyond 24 months the question is not which product but how much lands per year.
    cliff = {}
    for asset in exclusivities:
        when = _parse(asset.get("loe"))
        if when and when > mid_end:
            cliff[when.year] = cliff.get(when.year, 0) + 1

    near_h = SEG["near"] if near else EMPTY_H
    mid_h = SEG["mid"] if mid else EMPTY_H
    cliff_h = (min(len(cliff), 6) * 16 + 6) if cliff else EMPTY_H
    total = HEAD_DROP * 3 + near_h + mid_h + cliff_h + GAP * 2 + 24

    out = [f'<svg viewBox="0 0 {W} {total}"'
           f' width="100%" style="max-width:{W}px;font-family:Public Sans,sans-serif"'
           ' role="img" aria-label="Horizon rail: dated events ahead">']

    def seg_head(text, sub, baseline):
        out.append(
            f'<text x="{PAD_L}" y="{baseline}" font-size="9.5" font-weight="700"'
            f' letter-spacing="0.9" fill="{P.ink}">{html.escape(text)}</text>'
            f'<text x="{W - PAD_R}" y="{baseline}" font-size="9" text-anchor="end"'
            f' fill="{P.stale}">{html.escape(sub)}</text>')

    def empty(top, text):
        out.append(f'<text x="{PAD_L}" y="{top + 9}" font-size="9.5"'
                   f' fill="{P.stale}">{text}</text>')

    # --- Segment one: the actionable window, day resolution ---
    y = 12
    seg_head("NEXT 90 DAYS", "day scale", y)
    top = y + HEAD_DROP
    if near:
        out.append(f'<line x1="{PAD_L}" y1="{top}" x2="{PAD_L}" y2="{top + near_h}"'
                   f' stroke="{P.rule_strong}" stroke-width="1"/>')
        out.append(f'<line x1="{PAD_L - 5}" y1="{top}" x2="{W - PAD_R}" y2="{top}"'
                   f' stroke="{P.ink}" stroke-width="1.5"/>')
        out.append(f'<text x="{PAD_L}" y="{top - 6}" font-size="9" font-weight="600"'
                   f' fill="{P.stale}">today {today.isoformat()}</text>')
        for index, (when, item) in enumerate(near):
            ty = top + LEAD_IN + ((when - today).days / NEAR_DAYS) * (near_h - LEAD_IN)
            out.append(f'<rect x="{PAD_L - 3}" y="{ty - 2.5}" width="7" height="5"'
                       f' fill="{_colour(item)}"/>')
            if index < label_limit:
                out.append(
                    f'<text x="{PAD_L + 9}" y="{ty + 3}" font-size="9.5" fill="{P.ink}">'
                    f'<tspan font-weight="600">{when.strftime("%m-%d")}</tspan> '
                    f'{_esc(_label(item))}</text>')
    else:
        empty(top, f"nothing to {near_end.isoformat()}")

    # --- Segment two: the planning window, month resolution ---
    y = top + near_h + GAP
    seg_head("3 TO 24 MONTHS", "month scale", y)
    top = y + HEAD_DROP
    if mid:
        out.append(f'<line x1="{PAD_L}" y1="{top}" x2="{PAD_L}" y2="{top + mid_h}"'
                   f' stroke="{P.rule_strong}" stroke-width="1"/>')
        span = max((mid_end - near_end).days, 1)
        for index, (when, item) in enumerate(mid):
            ty = top + min((when - near_end).days / span, 1.0) * mid_h
            out.append(f'<rect x="{PAD_L - 3}" y="{ty - 2}" width="7" height="4"'
                       f' fill="{_colour(item)}"/>')
            if index < label_limit:
                out.append(
                    f'<text x="{PAD_L + 9}" y="{ty + 3}" font-size="9.5" fill="{P.ink}">'
                    f'<tspan font-weight="600">{when.strftime("%Y-%m")}</tspan> '
                    f'{_esc(_label(item), 18)}</text>')
    else:
        empty(top, "nothing inside 24 months")

    # --- Segment three: the cliff, counts per year ---
    y = top + mid_h + GAP
    seg_head("EXCLUSIVITY CLIFF", "24m+", y)
    top = y + HEAD_DROP - 8
    if cliff:
        peak = max(cliff.values())
        bar_w = W - PAD_L - PAD_R - 34
        for index, year in enumerate(sorted(cliff)[:6]):
            by = top + index * 16
            width = max(2, (cliff[year] / peak) * bar_w)
            out.append(f'<text x="{PAD_L}" y="{by + 7}" font-size="9.5"'
                       f' fill="{P.stale}">{year}</text>')
            out.append(f'<rect x="{PAD_L + 26}" y="{by}" width="{width:.1f}" height="9"'
                       f' fill="{P.ink}" opacity="0.82"/>')
            out.append(f'<text x="{PAD_L + 30 + width:.1f}" y="{by + 7.5}" font-size="9"'
                       f' fill="{P.stale}">{cliff[year]}</text>')
    else:
        empty(top, "no expiries past 24 months")

    out.append("</svg>")
    return "".join(out)
