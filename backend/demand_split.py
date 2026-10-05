"""Medicare growth split: each brand's Medicare spend growth into patients, use per
patient and price (docs/design/medicare-demand-split.md).

The identity. CMS Spending by Drug gives, per drug and year, total spending S, claims C
and distinct beneficiaries B. Spending is exactly

    S = B x (C / B) x (S / C)

so a year's change multiplies through the same three factors:

    1 + spend = (1 + patients) x (1 + use per patient) x (1 + cost per claim)

with patients = B1/B0 - 1, use per patient = (C1/B1)/(C0/B0) - 1 and cost per claim =
(S1/C1)/(S0/C0) - 1. Nothing is estimated; every factor is a ratio of two published
counts, and the product of the factors is the spend change to rounding. Each factor is
also given in points of spend growth by its log share, pts_f = g ln(1+f) / ln(1+g), and
because the logs of the factors add to the log of the whole, the points add exactly to g.

What a claim is differs by part, in CMS's own data dictionary: in Part D a claim is a
prescription fill, original or refill, so the middle factor is fills per patient and the
last is cost per fill. In Part B it is a claim for the drug, so the factors are claims
per patient and cost per claim. A cross-check splits cost per claim into units per claim
and cost per unit, which shows a move from 30-day to 90-day fills in Part D and a dose
change in Part B.

Medicare only, and never the US market: Medicaid and commercial payers are absent.
Part D spending is gross drug cost, including what the plan and the patient paid,
before manufacturer rebates and other price concessions, which CMS is prohibited from
disclosing. Part B covers fee-for-service beneficiaries only (Medicare Advantage is out)
and is the full value of the product paid, Medicare's payment plus the patient's
deductible and coinsurance, most of it set at average sales price plus 6%. A
beneficiary is a distinct patient on the drug during the year, so patient growth is net
additions, never new starts.

This module is a read-only lens. It writes nothing and moves no assumption, rNPV or
rating; a direction that disagrees with the model is a flag, never an edit.
"""

from __future__ import annotations

import math

# A part carrying less than this share of a brand's latest Medicare spend is reported,
# not split: the factors of a $2mm Part D sliver of a Part B drug are noise beside the
# brand, and a reader adds nothing by reading them.
MATERIAL_PART_SHARE = 0.05
# Units per claim moving more than about 5% in a year (in log terms) means the fill or
# the dose changed, so cost per claim is no longer a like-for-like price and the reader
# is pointed at cost per unit. Eliquis moved 1.3% in 2024 and is under it.
FILL_SIZE_FLAG = 0.05
# Growth inside one point either way is read as flat when comparing directions, so a
# +0.4% patient year does not disagree with a -0.2% model.
DIRECTION_DEADBAND = 0.01
# Below this |ln(1+g)| a year is flat and the log-share rule would divide by nothing,
# so each factor's points are its own log instead.
_FLAT = 1e-12


# --- the identity, pure ---------------------------------------------------------------
def _pos(value) -> float | None:
    """A count or amount that can be divided by: present and above nil."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _ratio(num, den) -> float | None:
    num, den = _pos(num), _pos(den)
    return num / den if num is not None and den is not None else None


def _change(new, old) -> float | None:
    new, old = _pos(new), _pos(old)
    return new / old - 1.0 if new is not None and old is not None else None


def step(prev: dict, cur: dict) -> dict:
    """The change from one year to the next, each factor a fraction or None.

    Each argument is {year, spending, claims, beneficiaries, units}. A missing or nil
    count gives None for every factor that needs it, never a zero: a suppressed
    beneficiary count leaves claims and price present and patients and use per patient
    None.
    """
    s0, s1 = prev.get("spending"), cur.get("spending")
    c0, c1 = prev.get("claims"), cur.get("claims")
    b0, b1 = prev.get("beneficiaries"), cur.get("beneficiaries")
    u0, u1 = prev.get("units"), cur.get("units")
    return {
        "from": prev.get("year"), "to": cur.get("year"),
        "spend": _change(s1, s0),
        "claims": _change(c1, c0),
        "patients": _change(b1, b0),
        "intensity": _change(_ratio(c1, b1), _ratio(c0, b0)),
        "price": _change(_ratio(s1, c1), _ratio(s0, c0)),
        "units_per_claim": _change(_ratio(u1, c1), _ratio(u0, c0)),
        "price_per_unit": _change(_ratio(s1, u1), _ratio(s0, u0)),
    }


def factors_of(st: dict) -> tuple | None:
    """The factors a step splits into: three where both patient counts are on file,
    claims and price where they are not, None where even that cannot be split."""
    if all(st.get(k) is not None for k in ("patients", "intensity", "price")):
        return ("patients", "intensity", "price")
    if all(st.get(k) is not None for k in ("claims", "price")):
        return ("claims", "price")
    return None


def points(st: dict) -> dict | None:
    """Each factor in points of spend growth, as fractions that add to ``spend``.

    pts_f = g ln(1+f) / ln(1+g). A flat year (|ln(1+g)| under 1e-12) takes each
    factor's own log instead, so it still splits rather than dividing by nothing.
    """
    g = st.get("spend")
    names = factors_of(st)
    if g is None or names is None or g <= -1.0:
        return None
    if any(st[k] <= -1.0 for k in names):
        return None
    whole = math.log1p(g)
    if abs(whole) < _FLAT:
        return {k: math.log1p(st[k]) for k in names}
    return {k: g * math.log1p(st[k]) / whole for k in names}


_SPAN_KEYS = ("spend", "claims", "patients", "intensity", "price", "units_per_claim",
              "price_per_unit")


def span(series: list, start: int, end: int) -> dict | None:
    """Compound annual growth per factor from ``start`` to ``end``, read on the end
    years only, with the same points rule. The CAGRs multiply exactly as the yearly
    factors do, since an nth root of a product is the product of the nth roots. None
    when either end year is missing or the span is under one year."""
    by_year = {r.get("year"): r for r in series}
    if start not in by_year or end not in by_year or end <= start:
        return None
    n = end - start
    whole = step(by_year[start], by_year[end])
    cagr = {k: ((1.0 + whole[k]) ** (1.0 / n) - 1.0) if whole[k] is not None
            and whole[k] > -1.0 else None for k in _SPAN_KEYS}
    out = {"from": start, "to": end, "years": n, **cagr}
    out["points"] = points(out)
    return out


def combine(parts: list) -> dict | None:
    """A brand's growth across two Medicare parts, in points only.

    Each part is {part, prior_spend, step}. The weights are the prior year's spend, so
    sum w_p g_p is the brand's total spend growth exactly. Factor points are the
    weighted sum of each part's own points. There is no combined patient count: a
    patient can be in both parts, and adding the two counts would count them twice.
    """
    usable = [p for p in parts if _pos(p.get("prior_spend")) is not None
              and (p.get("step") or {}).get("spend") is not None]
    if not usable:
        return None
    total = sum(p["prior_spend"] for p in usable)
    by_part, factor_pts, growth = {}, {}, 0.0
    for p in usable:
        w = p["prior_spend"] / total
        g = p["step"]["spend"]
        growth += w * g
        by_part[p["part"]] = w * g
        own = points(p["step"])
        if own is None:
            # A part that cannot be split still carries its growth, as its own share.
            factor_pts["unsplit"] = factor_pts.get("unsplit", 0.0) + w * g
            continue
        for k, v in own.items():
            factor_pts[k] = factor_pts.get(k, 0.0) + w * v
    return {"spend": growth, "by_part": by_part, "points": factor_pts,
            "weights": {p["part"]: p["prior_spend"] / total for p in usable}}
