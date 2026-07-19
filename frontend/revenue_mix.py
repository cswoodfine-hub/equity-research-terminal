"""Where a company's product revenue comes from: the drivers, and everything else.

A pie is only readable while the slices are few and different in size, which is exactly
the shape of a pharma portfolio: two or three products carry it and a long tail does
not. So the largest are drawn individually and the tail is bracketed into one slice,
rather than shaving the circle into twenty wedges nobody can compare.

Hue is not available here. The palette keeps orange and purple for modality, so the
slices take the ordinal ramp in size order, brightest first, and the bracketed tail
takes the muted grey that means "not itemised" everywhere else in the app.

The figures cover only the products the filing tags and the app could match to an
asset, so the total is not company revenue and the panel never calls it that.

Pure: builds SVG from a list of products and knows nothing about the API.
"""

from __future__ import annotations

import html
import math

from theme import P, ordinal_ramp

W = 832
H = 300
RADIUS = 104
INNER = 52                # a donut: the hole carries the total, and thin slices read
CX = 150                  # better against an arc than against a point
CY = H // 2
TOP_SLICES = 6            # beyond this the wedges stop being comparable
MIN_SHARE = 0.02          # a slice under 2% is a sliver; it joins the tail
LEGEND_X = 300
LEGEND_TOP = 34
ROW_H = 26


def _arc(cx, cy, radius, start, end) -> str:
    """An arc path from ``start`` to ``end`` radians, clockwise from twelve o'clock."""
    x1, y1 = cx + radius * math.sin(start), cy - radius * math.cos(start)
    x2, y2 = cx + radius * math.sin(end), cy - radius * math.cos(end)
    large = 1 if end - start > math.pi else 0
    return f"M {x1:.2f} {y1:.2f} A {radius:.2f} {radius:.2f} 0 {large} 1 {x2:.2f} {y2:.2f}"


def _wedge(start, end, outer, inner) -> str:
    if end - start >= 2 * math.pi - 1e-9:      # a single product carrying everything
        return (f'M {CX} {CY - outer} A {outer} {outer} 0 1 1 {CX - 0.01} {CY - outer} Z '
                f'M {CX} {CY - inner} A {inner} {inner} 0 1 0 {CX - 0.01} {CY - inner} Z')
    outer_arc = _arc(CX, CY, outer, start, end)
    inner_end_x = CX + inner * math.sin(end)
    inner_end_y = CY - inner * math.cos(end)
    large = 1 if end - start > math.pi else 0
    inner_start_x = CX + inner * math.sin(start)
    inner_start_y = CY - inner * math.cos(start)
    return (f"{outer_arc} L {inner_end_x:.2f} {inner_end_y:.2f} "
            f"A {inner:.2f} {inner:.2f} 0 {large} 0 "
            f"{inner_start_x:.2f} {inner_start_y:.2f} Z")


def split(products, top: int = TOP_SLICES, min_share: float = MIN_SHARE):
    """(drivers, tail) sorted largest first.

    A product is a driver when it is inside the top ``top`` and carries at least
    ``min_share`` of the total. Everything else is bracketed, and the bracket keeps its
    members so the panel can say how many are in it.
    """
    ranked = sorted((p for p in products if (p.get("value") or 0) > 0),
                    key=lambda p: -p["value"])
    total = sum(p["value"] for p in ranked)
    if not total:
        return [], []
    drivers, tail = [], []
    for index, product in enumerate(ranked):
        if index < top and product["value"] / total >= min_share:
            drivers.append(product)
        else:
            tail.append(product)
    return drivers, tail


def residual(products, company_revenue) -> float | None:
    """Company revenue the filing does not attribute to any product.

    Lilly tags 50.07bn of products against 65.18bn reported. The rest is collaboration
    revenue, products rolled into an "other" line, and products this app holds no asset
    for. Drawing only the attributed part would imply the company earned 50bn.
    """
    if not company_revenue:
        return None
    gap = company_revenue - sum(p["value"] for p in products if p.get("value"))
    return gap if gap > 0 else None


def render(products, currency: str | None = None, fiscal_year=None,
           company_revenue: float | None = None) -> str:
    """SVG for the revenue mix, or "" when there is nothing to draw."""
    drivers, tail = split(products)
    if not drivers:
        return ""

    unattributed = residual(products, company_revenue)
    total = sum(p["value"] for p in drivers + tail) + (unattributed or 0)
    slices = [{"label": p["brand_name"], "value": p["value"], "n": 1} for p in drivers]
    if tail:
        slices.append({"label": f"other, {len(tail)} product"
                                f"{'s' if len(tail) > 1 else ''}",
                       "value": sum(p["value"] for p in tail), "n": len(tail),
                       "tail": True})
    if unattributed:
        slices.append({"label": "not broken out by product",
                       "value": unattributed, "n": 0, "residual": True})

    # The ramp runs brightest to dimmest, so the biggest driver reads first. The tail
    # is grey rather than a ramp step: it is not a smaller product, it is several.
    ramp = list(reversed(ordinal_ramp(max(len(drivers), 2))))
    colours = [ramp[min(i, len(ramp) - 1)] for i in range(len(drivers))]
    if tail:
        colours.append(P.stale)
    if unattributed:
        colours.append(None)      # drawn as an outline: it is not a product

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%"'
           f' style="max-width:{W}px;font-family:Public Sans,sans-serif" role="img"'
           f' aria-label="Product revenue mix, largest drivers and the rest">']

    angle = 0.0
    for entry, colour in zip(slices, colours):
        sweep = entry["value"] / total * 2 * math.pi
        path = _wedge(angle, angle + sweep, RADIUS, INNER)
        # The unattributed wedge is hollow. It is not a smaller product, it is revenue
        # with no product against it, and a filled slice would read as one more brand.
        fill = (f'fill="{colour}" stroke="{P.ground}" stroke-width="1.5"' if colour
                else f'fill="none" stroke="{P.stale}" stroke-width="1" '
                     f'stroke-dasharray="3 2"')
        out.append(f'<path d="{path}" {fill}/>')
        angle += sweep

    # The hole carries the total, which is what stops a reader summing the labels.
    out.append(f'<text x="{CX}" y="{CY - 2}" font-size="15" font-weight="700"'
               f' text-anchor="middle" fill="{P.ink}">'
               f'{total / 1e9:,.1f}</text>')
    unit = f"{currency or ''} bn".strip()
    out.append(f'<text x="{CX}" y="{CY + 13}" font-size="9" text-anchor="middle"'
               f' fill="{P.stale}">{html.escape(unit)}</text>')

    # A legend, because a wedge cannot hold a drug name. Ordered as the slices are.
    for index, (entry, colour) in enumerate(zip(slices, colours)):
        y = LEGEND_TOP + index * ROW_H
        share = entry["value"] / total * 100
        swatch = (f'fill="{colour}"' if colour
                  else f'fill="none" stroke="{P.stale}" stroke-dasharray="2 1.5"')
        out.append(f'<rect x="{LEGEND_X}" y="{y - 8}" width="9" height="9" {swatch}/>')
        muted = entry.get("tail") or entry.get("residual")
        out.append(f'<text x="{LEGEND_X + 16}" y="{y}" font-size="12"'
                   f' fill="{P.stale if muted else P.ink}">'
                   f'{html.escape(entry["label"])}</text>')
        out.append(f'<text x="{LEGEND_X + 300}" y="{y}" font-size="12"'
                   f' text-anchor="end" font-weight="600" fill="{P.ink}"'
                   f' style="font-variant-numeric:tabular-nums">'
                   f'{entry["value"] / 1e9:,.2f}</text>')
        out.append(f'<text x="{LEGEND_X + 360}" y="{y}" font-size="11"'
                   f' text-anchor="end" fill="{P.stale}"'
                   f' style="font-variant-numeric:tabular-nums">'
                   f'{share:.1f}%</text>')

    out.append("</svg>")
    return "".join(out)


def caption(products, currency=None, fiscal_year=None,
            company_revenue: float | None = None) -> str:
    """What the panel covers, and what it does not."""
    drivers, tail = split(products)
    if not drivers:
        return ""
    unattributed = residual(products, company_revenue)
    total = sum(p["value"] for p in drivers + tail) + (unattributed or 0)
    lead = drivers[0]
    year = f"FY{fiscal_year} " if fiscal_year else ""
    text = (f"{year}revenue of {total / 1e9:,.1f}bn {currency or ''}, with "
            f"{len(drivers) + len(tail)} products named in the filing. "
            f"{lead['brand_name']} alone is {lead['value'] / total * 100:.0f}% of it.")
    if tail:
        text += (f" The {len(tail)} smallest are bracketed into one slice, since a "
                 "circle cut much finer stops being comparable.")
    if unattributed:
        text += (f" The hollow wedge is {unattributed / 1e9:,.1f}bn the filing does not "
                 "attribute to a product: collaboration revenue, lines reported only as "
                 "a total, and products this app holds no asset for.")
    return text
