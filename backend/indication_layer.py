"""What an unapproved indication adds to a product that is already selling.

``forecast.build`` values a marketed product top-down: a reported revenue grown at a
rate to a ceiling, with ``per_indication`` empty and no patient funnel at all. That is
right for the business it already has, and it leaves nothing for a readout to move. A
label expansion therefore read as "outside the gate model" on every marketed product in
the book, which is not the same as being worth nothing.

This values the expansion the way the book values anything not yet approved: bottom-up
over the indication's own pool, patients times price, through the same engine and the
same identity a pipeline asset goes through. The marketed line is untouched, so the
layer is an addition to it rather than a restatement of it, and the gate's stake is the
layer's own value between its legs.

Three rules keep it honest.

**Only an indication the label does not already cover.** The approved business is inside
the reported revenue the marketed line is grown from, so building it again bottom-up
would buy it twice. ``forecast_view._approved_indications`` is the test, and this module
refuses rather than guesses when it cannot be applied.

**The franchise ceiling is a ceiling on the franchise.** A marketed line carries
``revenue_ceiling_musd``, and where that figure is somebody's forecast of the whole
product at peak it already contains the expansions. Adding a layer under it would count
them twice over. So the sum is checked against it and reported, never silently capped:
``ceiling_binds`` says the two together pass the published peak, which is a fact about
the assumptions a reader should see rather than an arithmetic to hide.

**Nothing is invented.** A layer with no pool, no price or no curve is not built; the
keys it wants are named and the caller reports them, the same way a forecast that cannot
be built names what it lacks.
"""

from __future__ import annotations

import copy

import assumptions as assumptions_module
import forecast

# What the layer needs beyond the company economics the marketed line already carries.
# The price is the asset's; everything else belongs to the indication.
#
# The ramp belongs here and was missing from it. A layer is built on the pool identity,
# which turns a pool into patients a year and then needs a curve to say how quickly they
# arrive; without one the engine has no patient series and refuses with "supply
# new_patients rows or the pool identity inputs", which names neither key and reads like
# a fault in the engine rather than a gap in the seed. Six layers carried every other
# key and failed that way. This module's whole promise is that it names what it lacks,
# so it has to name these two.
INDICATION_KEYS = ("prevalence", "eligible_pct", "penetration_peak_pct",
                   "ramp_midpoint_year", "ramp_steepness")
ASSET_KEYS = ("discontinuation_pct",)

# Carried by the marketed line and meaningless in a bottom-up build: the layer is the
# business the product does not have yet, so it starts from no revenue.
_MARKETED_ONLY = ("base_revenue", "revenue_growth_pct", "revenue_ceiling_musd",
                  "growth_fade_years")


def _missing(built: dict, entry: dict) -> list:
    out = [k for k in ASSET_KEYS if built["scalars"].get(k) is None]
    out += [k for k in INDICATION_KEYS if (entry.get("scalars") or {}).get(k) is None]
    if forecast.net_price(built["scalars"]) is None:
        out.append("net_price_per_patient")
    return out


def build(conn, asset_id: int, indication_id: int, scenario: str = "base") -> dict | None:
    """The unrisked value of one unapproved indication on a marketed product.

    Returns None where the asset carries no assumptions at all. Otherwise a dict with
    ``ok``; when false, ``missing`` names the keys that would build it.

    Unrisked on purpose. The probability belongs to the gate, which applies it to both
    legs, and a value already risked once cannot be risked again.
    """
    loaded = assumptions_module.load(conn, asset_id, scenario)
    if not loaded or not loaded.get("scalars"):
        return None
    entry = next((e for e in loaded.get("indications") or []
                  if e.get("indication_id") == indication_id), None)
    if entry is None:
        return {"ok": False, "missing": list(INDICATION_KEYS),
                "why": "The indication carries no assumptions of its own."}

    # The share of the pool already inside the approved business, which the marketed
    # line scales the layer by (forecast._indication_layers). The gate built it at full
    # size, so Imfinzi's bladder layer, 94% inside the business it already sells to, was
    # staked at 2,080mm where the forecast adds 125mm. The pool is narrowed rather than
    # the answer scaled, so the peak, the patients and the value all say the same thing.
    # Asked before the keys a pool needs: a layer wholly inside the business needs no pool,
    # and reporting "missing prevalence" for it read as unfinished research.
    overlap = (entry.get("scalars") or {}).get("base_pool_overlap_pct")
    # On a selling product built from patients, an indication is a layer only where the
    # research marked it one, the rule forecast._risk_patient_layers holds the forecast to.
    # Lipfendra carries no label in the book, so its approved hypercholesterolaemia read
    # as unapproved and the gate staked the whole product, 3,953mm at peak, on an
    # open-label safety extension.
    mode = ((loaded.get("scalars") or {}).get("therapy_mode") or "").strip()
    if (loaded.get("is_marketed") and mode in ("chronic", "one_time")
            and overlap is None):
        return {"ok": False, "missing": [],
                "why": "On a product modelled from patients this indication is the "
                       "product's own business unless the research marks it a layer by "
                       "stating base_pool_overlap_pct."}
    if overlap is not None and overlap >= 1.0:
        return {"ok": False, "missing": [],
                "why": "The pool is wholly inside the business already being sold to, so "
                       "the readout moves evidence rather than patients."}

    gaps = _missing(loaded, entry)
    if gaps:
        return {"ok": False, "missing": gaps,
                "why": "The layer needs its own pool and price before it can be built."}

    layer = copy.deepcopy(loaded)
    entry = copy.deepcopy(entry)
    if overlap:
        entry["scalars"]["eligible_pct"] *= 1.0 - overlap
    layer["indications"] = [entry]
    layer["is_marketed"] = False          # the layer is the business not yet won
    scalars = layer["scalars"]
    for key in _MARKETED_ONLY:
        scalars.pop(key, None)
    # A chronic biologic billed per year of therapy. The marketed mode it came from is
    # about a revenue line, not a dosing schedule, so it cannot carry over.
    scalars["therapy_mode"] = "chronic"
    # Unrisked: see the docstring. pos is the gate's to apply.
    scalars["pos"] = 1.0

    try:
        out = forecast.build(layer)
    except forecast.ForecastError as exc:
        return {"ok": False, "missing": list(getattr(exc, "missing", []) or []),
                "why": str(exc)}

    ceiling = (loaded.get("scalars") or {}).get("revenue_ceiling_musd")
    peak = _peak(out)
    base_peak = _base_peak(loaded)
    together = (base_peak or 0.0) + (peak or 0.0)
    return {
        "ok": True,
        "npv": out.get("npv"),
        "peak_revenue": peak,
        "peak_year": out.get("peak_year"),
        "revenue": out.get("revenue"),
        "treated": out.get("treated"),
        "notes": out.get("notes") or [],
        "base_pool_overlap_pct": overlap,
        # The franchise check. Reported, not applied: see the docstring.
        "ceiling": ceiling,
        "base_peak_revenue": base_peak,
        "peak_together": together,
        "ceiling_binds": bool(ceiling is not None and together > ceiling),
    }


def _peak(out: dict):
    """The highest revenue year of a build.

    Read off the revenue path rather than taken from ``peak_revenue``, which the engine
    fills for some shapes and leaves None for others. The path is always there, and the
    maximum of it is the figure either way.
    """
    path = [r for r in (out.get("revenue") or []) if r is not None]
    return max(path) if path else None


def _base_peak(loaded: dict):
    """The marketed line's own peak revenue, for the franchise check.

    Built from the same assumptions the page shows, so the two figures compared are the
    ones a reader would compare. None where the marketed line cannot be built, which
    leaves the check unreported rather than wrong.
    """
    try:
        return _peak(forecast.build(loaded))
    except Exception:                                      # noqa: BLE001
        return None
