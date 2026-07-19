"""The exclusivity cliff: what falls off protection each year, and how much of that
figure is actually known.

Revenue per product has to be typed in, so at any moment some of the cliff is quantified
and some is not. A chart that showed only the quantified part would read as a small
cliff rather than a poorly covered one, which is the opposite of the truth. So the panel
carries two registers:

  bars   revenue at risk, for the products with a figure on file
  comb   one mark per product underneath, filled where a figure exists and hollow where
         it does not, so the gap between what is drawn and what is known is visible
         rather than inferred

At zero coverage the bars are empty and the comb carries the whole story, which is a
count-based cliff and says so. As figures are entered the bars grow into it. Nothing is
estimated to fill the gap.

Pure: builds SVG from the exposure payload and knows nothing about the API.
"""

from __future__ import annotations

import html

from theme import MINUS, P

W = 832
BAR_TOP = 18
BAR_H = 96          # the revenue register, when there is revenue to put in it
EMPTY_H = 22        # what it collapses to when there is not
COMB_H = 44         # the coverage register
PAD_L = 42
PAD_R = 12
MARK = 7            # side of one product mark in the comb
MARK_GAP = 3


def _fmt(value, currency=None, scale=1e9) -> str:
    """A billions figure, with the scale on the number and the currency after it."""
    if value is None:
        return "—"
    text = f"{MINUS if value < 0 else ''}{abs(value) / scale:,.2f}bn"
    return f"{text} {currency}" if currency else text


def _label(bucket) -> str:
    year = bucket["year"]
    return "later" if year in (None, "later") else str(year)[-2:]


def render(exposure: dict) -> str:
    """SVG for the cliff, or "" when nothing is at risk.

    Every year in the window is drawn, including the ones where nothing expires. The
    empty years are the shape: dropping them would leave a row of labels reading 31, 32,
    later, which says nothing about when the cliff arrives or how far off it is.
    """
    buckets = list(exposure.get("buckets") or [])
    if not any(b["products"] for b in buckets):
        return ""

    currency = exposure.get("currency")
    peak_revenue = max((b["revenue"] for b in buckets), default=0.0)
    # The revenue register collapses to a line of text when nothing is priced, rather
    # than holding an empty 96px of axis. It grows back the moment a figure is entered.
    bar_h = BAR_H if peak_revenue > 0 else EMPTY_H
    baseline = BAR_TOP + bar_h
    height = baseline + COMB_H + 26

    slot = (W - PAD_L - PAD_R) / len(buckets)
    bar_w = min(slot * 0.5, 34)

    def x(index):
        return PAD_L + slot * (index + 0.5)

    out = [f'<svg viewBox="0 0 {W} {height}" width="100%"'
           f' style="max-width:{W}px;font-family:Public Sans,sans-serif" role="img"'
           f' aria-label="Exclusivity cliff by year, with revenue coverage">']

    out.append(f'<line x1="{PAD_L - 8}" y1="{baseline}" x2="{W - PAD_R}"'
               f' y2="{baseline}" stroke="{P.rule_strong}" stroke-width="1"/>')

    # --- revenue register ---
    if peak_revenue > 0:
        out.append(f'<text x="{PAD_L - 12}" y="{BAR_TOP + 4}" font-size="9"'
                   f' text-anchor="end" fill="{P.stale}">'
                   f'{_fmt(peak_revenue)}</text>')
        out.append(f'<text x="{PAD_L - 12}" y="{baseline + 3}" font-size="9"'
                   f' text-anchor="end" fill="{P.stale}">0</text>')
        for index, bucket in enumerate(buckets):
            if not bucket["revenue"]:
                continue
            bar = bucket["revenue"] / peak_revenue * bar_h
            out.append(
                f'<rect x="{x(index) - bar_w / 2:.1f}" y="{baseline - bar:.1f}"'
                f' width="{bar_w:.1f}" height="{bar:.1f}" fill="{P.oxblood}"/>')
            out.append(
                f'<text x="{x(index):.1f}" y="{baseline - bar - 4:.1f}"'
                f' font-size="9" font-weight="600" text-anchor="middle"'
                f' fill="{P.ink}">{bucket["revenue"] / 1e9:,.1f}</text>')
    else:
        # Nothing priced yet. Say so in the register that would have held it rather
        # than drawing an empty axis and leaving the reader to work out why.
        out.append(f'<text x="{PAD_L}" y="{BAR_TOP + 8}" font-size="10"'
                   f' fill="{P.stale}">No product revenue on file, so this counts '
                   f'products rather than money.</text>')

    # --- coverage register ---
    comb_top = baseline + 9
    for index, bucket in enumerate(buckets):
        marks = bucket["covered"] + bucket["uncovered"]
        per_row = max(int((bar_w + MARK_GAP) // (MARK + MARK_GAP)), 1)
        for position, product in enumerate(marks):
            row, column = divmod(position, per_row)
            my = comb_top + row * (MARK + MARK_GAP)
            if my + MARK > comb_top + COMB_H:
                break              # deeper stacks are reported by the count beneath
            mx = (x(index) - (per_row * (MARK + MARK_GAP) - MARK_GAP) / 2
                  + column * (MARK + MARK_GAP))
            priced = product.get("revenue") is not None
            # Filled means priced, hollow means unknown. Hollow is not zero, and the
            # outline is what stops a thin table reading as a small cliff.
            out.append(
                f'<rect x="{mx:.1f}" y="{my:.1f}" width="{MARK}" height="{MARK}"'
                + (f' fill="{P.oxblood}"/>' if priced
                   else f' fill="none" stroke="{P.stale}" stroke-width="1"/>'))

    # --- year labels ---
    for index, bucket in enumerate(buckets):
        empty = not bucket["products"]
        out.append(
            f'<text x="{x(index):.1f}" y="{height - 6}" font-size="9"'
            f' text-anchor="middle" fill="{P.stale if empty else P.ink}">'
            f'{html.escape(_label(bucket))}</text>')
        if not empty:
            out.append(
                f'<text x="{x(index):.1f}" y="{height - 17}" font-size="8.5"'
                f' text-anchor="middle" fill="{P.stale}">{bucket["products"]}</text>')

    out.append("</svg>")
    return "".join(out)


def caption(exposure: dict) -> str:
    """One sentence stating the exposure and, plainly, how much of it is priced."""
    products = exposure.get("products_at_risk") or 0
    if not products:
        return ""
    covered = exposure.get("products_covered") or 0
    currency = exposure.get("currency")
    parts = []
    if covered:
        parts.append(
            f"{_fmt(exposure['revenue_at_risk'], currency)} of revenue sits on "
            f"{covered} of the {products} products that lose protection inside the "
            "window.")
        if covered < products:
            parts.append(
                f"The other {products - covered} carry no revenue figure, so the bars "
                "understate the cliff by an unknown amount rather than by nothing.")
    else:
        parts.append(
            f"{products} products lose protection inside the window and none has a "
            "revenue figure on file, so this is a count rather than a sum. Add figures "
            "from the product table of the 10-K to price it.")
    if exposure.get("mixed_currency"):
        parts.append("Figures are on file in more than one currency and are not "
                     "converted, so no total is shown.")
    return " ".join(parts)
