"""The forecast object: patients x price to revenue, revenue to FCFF, FCFF to rNPV.

Pure functions over an assumptions dict; nothing here touches the database. The loader in
``assumptions.py`` builds the input, this module computes, and the split is what makes the
engine testable against the CASGEVY workbook's own numbers.

Two design rules carried from docs/ROADMAP.md:

- **Nothing is invented.** A missing required assumption raises ``ForecastError`` naming
  the key, and a mode that cannot run without a number (the pool identity without
  incidence) is reported unavailable rather than run with a guess. Optional funnel
  factors that are absent simply make the funnel coarser, and the output says so.
- **The pool is an identity, not a drawing.** The workbook types its patient curve by
  hand: 5, 45, 120, ... 350, a hump drawn from feel, and computes a 46,000-patient
  addressable pool two sheets away that the curve never references. Here
  ``new(t) = min(capacity, penetration x (pool + incidence))`` and
  ``pool(t+1) = pool + incidence - new(t)``, so the hump falls out of arithmetic, the
  tail converges on the incidence run rate, and no forecast can treat more patients than
  exist. An explicit hand series still wins where the analyst supplies one; both are
  returned so they can be argued against each other.

The valuation mechanics mirror the workbook exactly, because reproducing it is the
milestone: FCFF = revenue - COGS - SG&A - R&D - tax with no capex or working capital
line, mid-year discounting, and terminal value as a perpetuity of the final year's FCFF.
For a one-time therapy that perpetuity is coherent with the identity: the tail year is
the incidence run rate, which is exactly what a zero-growth perpetuity capitalises.
"""

from __future__ import annotations

import math

# Keys the engine cannot compute without. Everything else is optional and its absence is
# either a coarser model (funnel factors) or a reported unavailability (derived mode).
REQUIRED = ("therapy_mode", "net_price_per_patient")

# One-time therapies bill the patient once, so COGS rides per patient; chronic therapies
# bill per year and carry COGS as a share of revenue.
MODES = ("one_time", "chronic")


class ForecastError(ValueError):
    """A required assumption is missing. Carries the key names, so the caller can say
    exactly what to supply instead of showing a blank."""

    def __init__(self, missing):
        self.missing = list(missing)
        super().__init__("missing required assumptions: " + ", ".join(self.missing))


# --- penetration and patients ----------------------------------------------

def s_curve(year_index: float, peak: float, midpoint: float, steepness: float) -> float:
    """Penetration in a given year: a logistic ramp to ``peak``.

    ``midpoint`` is in years from the series start, ``steepness`` the logistic k. At the
    midpoint penetration is half the peak, which is what an analyst moving the curve
    expects the handle to mean.
    """
    return peak / (1.0 + math.exp(-steepness * (year_index - midpoint)))


def derive_new_patients(pool: float, incidence: float, penetration,
                        years: int, capacity=None) -> list[float]:
    """The identity. ``penetration`` is a callable of year index; ``capacity`` an
    optional per-year list of treatment slots.

    The pool never goes negative and the tail converges on incidence x penetration,
    both by construction rather than by assertion.
    """
    remaining = float(pool)
    out = []
    for i in range(years):
        eligible = max(0.0, remaining + incidence)
        new = penetration(i) * eligible
        if capacity is not None and capacity[i] is not None:
            new = min(new, capacity[i])
        new = min(new, eligible)
        out.append(new)
        remaining = max(0.0, remaining + incidence - new)
    return out


def patients_for_indication(ind: dict, years: list[int], notes: list) -> dict:
    """One indication's patient series: the explicit hand series where the analyst gave
    one, the derived identity beside it where its inputs exist.

    Returns {"used": [...], "explicit": [...] | None, "derived": [...] | None,
    "basis": str}. ``used`` is what revenue is built on.
    """
    scalars = ind.get("scalars") or {}
    series = ind.get("series") or {}

    explicit = None
    if "new_patients" in series:
        explicit = [series["new_patients"].get(y) for y in years]
        explicit = [0.0 if v is None else float(v) for v in explicit]

    derived = None
    prevalence = scalars.get("prevalence")
    eligible_pct = scalars.get("eligible_pct")
    incidence = scalars.get("incidence")
    peak = scalars.get("penetration_peak_pct")
    midpoint = scalars.get("ramp_midpoint_year")
    steepness = scalars.get("ramp_steepness")
    if None not in (prevalence, eligible_pct, incidence, peak, midpoint, steepness):
        multiple = 1.0 + (scalars.get("exus_multiple") or 0.0)
        pool = prevalence * eligible_pct * multiple
        # The same multiple scales incidence, which is an assumption of its own and is
        # said aloud rather than buried.
        inc = incidence * multiple
        if scalars.get("exus_multiple"):
            notes.append(f"{ind.get('name', 'indication')}: ex-US pool and incidence "
                         f"scaled by the seeded multiple ({multiple:.1f}x US)")
        # Optional funnel refinements. Absent factors leave the funnel coarser, which is
        # the workbook's own shape (eligible_pct carries the whole funnel there).
        funnel = 1.0
        for factor in ("diagnosed_pct", "referred_pct", "payer_approved_pct",
                       "accepts_pct"):
            if scalars.get(factor) is not None:
                funnel *= scalars[factor]
        mid = midpoint - years[0] if midpoint > 100 else midpoint  # year or offset
        curve = lambda i: s_curve(i, peak * funnel, mid, steepness)
        capacity = None
        if "capacity_patients" in series:
            capacity = [series["capacity_patients"].get(y) for y in years]
        derived = derive_new_patients(pool, inc, curve, len(years), capacity)
    else:
        missing = [k for k, v in (("prevalence", prevalence),
                                  ("eligible_pct", eligible_pct),
                                  ("incidence", incidence),
                                  ("penetration_peak_pct", peak),
                                  ("ramp_midpoint_year", midpoint),
                                  ("ramp_steepness", steepness)) if v is None]
        notes.append(f"{ind.get('name', 'indication')}: derived patient mode "
                     f"unavailable, missing {', '.join(missing)}")

    if explicit is not None:
        basis = "analyst series"
    elif derived is not None:
        basis = "derived from pool identity"
    else:
        basis = "none"
    return {"used": explicit if explicit is not None else derived,
            "explicit": explicit, "derived": derived, "basis": basis}


# --- money -------------------------------------------------------------------

def net_price(scalars: dict):
    """Net price per patient, given directly or as list price less gross-to-net."""
    if scalars.get("net_price_per_patient") is not None:
        return scalars["net_price_per_patient"]
    lp, gtn = scalars.get("list_price_per_patient"), scalars.get("gross_to_net_pct")
    if lp is not None and gtn is not None:
        return lp * (1.0 - gtn)
    return None


def wacc(scalars: dict):
    """(wacc, basis). Given directly, or derived CAPM from components."""
    if scalars.get("wacc") is not None:
        return scalars["wacc"], "stated"
    needed = ("risk_free", "erp", "beta", "cost_of_debt", "debt_weight")
    if any(scalars.get(k) is None for k in needed):
        return None, None
    tax = scalars.get("tax_rate") or 0.0
    ke = scalars["risk_free"] + scalars["beta"] * scalars["erp"]
    kd = scalars["cost_of_debt"] * (1.0 - tax)
    dw = scalars["debt_weight"]
    return (1.0 - dw) * ke + dw * kd, "CAPM from components"


def pos(scalars: dict, phase=None, pos_defaults=None):
    """(pos, basis). Composite factors where stated, else the phase-gated default.

    A launched asset states its factors (the workbook's regulatory x launch x
    reimbursement x durability); a pipeline asset without them falls to the curated
    phase ramp, and the basis says which happened.
    """
    factors = [scalars.get(k) for k in ("pos_regulatory", "pos_launch",
                                        "pos_reimbursement", "pos_durability")]
    if any(f is not None for f in factors):
        composite = 1.0
        for f in factors:
            composite *= 1.0 if f is None else f
        return composite, "composite factors"
    if scalars.get("pos") is not None:
        return scalars["pos"], "stated"
    if phase and pos_defaults and phase in pos_defaults:
        return pos_defaults[phase]["pos"], (f"phase default ({phase}), "
                                            f"{pos_defaults[phase]['source']}")
    return None, None


def erode(revenue: list[float], years: list[int], loe_year,
          year1_pct, decay_pct) -> list[float]:
    """Revenue after loss of exclusivity: a year-one drop, then decay of the remainder.

    Years at or before the LOE year are untouched. Where the horizon ends at LOE, which
    is the CASGEVY case, nothing changes and nothing pretends to.
    """
    if loe_year is None or year1_pct is None:
        return list(revenue)
    out = []
    factor = 1.0
    for year, value in zip(years, revenue):
        if year == loe_year + 1:
            factor = 1.0 - year1_pct
        elif year > loe_year + 1:
            factor *= (1.0 - (decay_pct or 0.0))
        out.append(value * factor if year > loe_year else value)
    return out


def fcff(revenue: list[float], patients: list[float], scalars: dict,
         mode: str) -> list[dict]:
    """The workbook's P&L per year: COGS, SG&A, R&D, tax, NOPAT = FCFF.

    No capex and no working capital line, matching the reference model, and the
    simplification is stated in the output notes rather than hidden.
    """
    sga = scalars.get("sga_pct") or 0.0
    rd = scalars.get("rd_pct") or 0.0
    tax = scalars.get("tax_rate") or 0.0
    rows = []
    for rev, pats in zip(revenue, patients):
        if mode == "one_time":
            cogs = (scalars.get("cogs_per_patient") or 0.0) * pats
        else:
            cogs = (scalars.get("cogs_pct") or 0.0) * rev
        ebit = rev - cogs - sga * rev - rd * rev
        taxed = max(0.0, ebit * tax)
        rows.append({"revenue": rev, "cogs": cogs, "ebit": ebit, "tax": taxed,
                     "fcff": ebit - taxed})
    return rows


def discount(values: list[float], rate: float, midyear: bool = True) -> list[float]:
    """Present values, mid-year convention by default (periods 0.5, 1.5, ...)."""
    offset = 0.5 if midyear else 1.0
    return [v / (1.0 + rate) ** (i + offset) for i, v in enumerate(values)]


def terminal_value(last_fcff: float, growth: float, rate: float,
                   periods: float) -> tuple[float, float]:
    """(terminal value, its present value), zero-growth perpetuity included.

    Discounted at the final mid-year period, matching the workbook.
    """
    if rate - growth <= 0:
        return 0.0, 0.0
    tv = last_fcff * (1.0 + growth) / (rate - growth)
    return tv, tv / (1.0 + rate) ** periods


# --- the whole build --------------------------------------------------------

def build(inputs: dict) -> dict:
    """Assumptions in, forecast out. Raises ForecastError when a required key is absent.

    ``inputs``: {"scalars": {...}, "indications": [{"name", "scalars", "series"}],
    "loe": {"year", "basis"} | None, "actuals": [{"fiscal_year", "period", "value"}],
    "phase": str | None, "pos_defaults": {...}, "erosion_defaults": {...},
    "modality": str | None}.
    """
    scalars = inputs.get("scalars") or {}
    notes: list[str] = []

    mode = (scalars.get("therapy_mode") or "").strip()
    price = net_price(scalars)
    missing = [k for k in ("therapy_mode",) if not mode]
    if price is None:
        missing.append("net_price_per_patient (or list price and gross-to-net)")
    rate, rate_basis = wacc(scalars)
    if rate is None:
        missing.append("wacc (or its CAPM components)")
    if missing:
        raise ForecastError(missing)
    if mode not in MODES:
        raise ForecastError([f"therapy_mode must be one of {MODES}, got '{mode}'"])

    start = int(scalars.get("forecast_start_year") or 0)
    horizon = int(scalars.get("forecast_years") or 10)
    # The display series starts where the analyst's data starts; the DCF window is
    # start..start+horizon-1, which is how the workbook shows 2024 actuals beside a
    # 2026-2035 valuation.
    series_years = set()
    for ind in inputs.get("indications") or []:
        for series in (ind.get("series") or {}).values():
            series_years |= set(series)
    if not start:
        if not series_years:
            raise ForecastError(["forecast_start_year"])
        start = min(series_years)
        notes.append(f"forecast start taken from the earliest series year, {start}")
    first = min(series_years | {start}) if series_years else start
    years = list(range(first, start + horizon))
    dcf_years = list(range(start, start + horizon))

    # Patients, per indication and in total.
    per_indication = {}
    for ind in inputs.get("indications") or []:
        result = patients_for_indication(ind, years, notes)
        if result["used"] is None:
            continue
        per_indication[ind.get("name") or f"indication {len(per_indication) + 1}"] = result
    if not per_indication:
        raise ForecastError(["no indication has a usable patient series: supply "
                             "new_patients rows or the pool identity inputs"])
    total_patients = [sum(per_indication[n]["used"][i] for n in per_indication)
                      for i in range(len(years))]

    if mode == "one_time":
        revenue = [p * price for p in total_patients]
    else:
        revenue = [p * price for p in total_patients]
        notes.append("chronic mode: revenue is treated patients x annual net price")

    # Erosion, only where the horizon runs past the LOE on file or assumed.
    loe = inputs.get("loe") or {}
    loe_year = scalars.get("loe_year") or loe.get("year")
    loe_basis = "assumed" if scalars.get("loe_year") else (loe.get("basis") or None)
    year1 = scalars.get("erosion_year1_pct")
    decay = scalars.get("erosion_decay_pct")
    erosion_basis = "stated" if year1 is not None else None
    if year1 is None and inputs.get("modality") and inputs.get("erosion_defaults"):
        default = inputs["erosion_defaults"].get(inputs["modality"])
        if default:
            year1, decay = default["year1_pct"], default["decay_pct"]
            erosion_basis = (f"curated default ({inputs['modality']}), "
                            f"{default['source']}")
    if loe_year is not None:
        loe_year = int(loe_year)
    eroded = erode(revenue, years, loe_year, year1, decay)
    if loe_year is not None and max(years) <= loe_year:
        notes.append(f"LOE {loe_year} ({loe_basis}) is at or beyond the horizon, "
                     "so no erosion applies inside it")

    # P&L and valuation over the DCF window only.
    window = [i for i, y in enumerate(years) if y in dcf_years]
    pnl = fcff([eroded[i] for i in window], [total_patients[i] for i in window],
               scalars, mode)
    flows = [row["fcff"] for row in pnl]
    pvs = discount(flows, rate)
    growth = scalars.get("terminal_growth") or 0.0
    if (scalars.get("terminal_mode") or "perpetuity") == "perpetuity":
        tv, tv_pv = terminal_value(flows[-1], growth, rate, len(flows) - 0.5)
    else:
        tv, tv_pv = 0.0, 0.0
        notes.append("no terminal value taken")
    npv = sum(pvs) + tv_pv

    probability, pos_basis = pos(scalars, inputs.get("phase"),
                                 inputs.get("pos_defaults"))
    if probability is None:
        raise ForecastError(["pos (factors, a stated value, or a phase for the "
                             "curated default)"])
    rnpv = npv * probability
    share = scalars.get("economics_share")

    # Calibration: the modelled series against every actual on file, partial years shown
    # against the modelled full year they sit inside.
    calibration = []
    modelled_by_year = dict(zip(years, eroded))
    for actual in inputs.get("actuals") or []:
        year = actual.get("fiscal_year")
        if year not in modelled_by_year:
            continue
        modelled = modelled_by_year[year]
        reported = actual.get("value")
        row = {"year": year, "period": actual.get("period"),
               "modelled": modelled, "reported": reported}
        if actual.get("period") == "FY" and reported:
            row["variance_pct"] = (modelled - reported) / reported
        calibration.append(row)

    return {
        "mode": mode, "years": years, "dcf_years": dcf_years,
        "patients": {"total": total_patients, "by_indication": per_indication},
        "revenue": revenue, "revenue_after_loe": eroded, "pnl": pnl,
        "wacc": rate, "wacc_basis": rate_basis,
        "pos": probability, "pos_basis": pos_basis,
        "loe_year": loe_year, "loe_basis": loe_basis, "erosion_basis": erosion_basis,
        "pv_fcff": sum(pvs), "terminal_value": tv, "terminal_pv": tv_pv,
        "npv": npv, "rnpv": rnpv,
        "owner_rnpv": rnpv * share if share is not None else None,
        "partner_rnpv": rnpv * (1.0 - share) if share is not None else None,
        "economics_share": share,
        "calibration": calibration, "notes": notes,
    }


def sensitivity(inputs: dict, x_key: str, x_values, y_key: str, y_values) -> dict:
    """rNPV over a two-axis grid of scalar assumptions.

    Returns {"x_key", "x_values", "y_key", "y_values", "grid": rows of rNPV, y-major}.
    A cell where the build refuses is None rather than a guess.
    """
    grid = []
    for y in y_values:
        row = []
        for x in x_values:
            variant = dict(inputs)
            variant["scalars"] = dict(inputs.get("scalars") or {})
            variant["scalars"][x_key] = x
            variant["scalars"][y_key] = y
            try:
                row.append(build(variant)["rnpv"])
            except ForecastError:
                row.append(None)
        grid.append(row)
    return {"x_key": x_key, "x_values": list(x_values),
            "y_key": y_key, "y_values": list(y_values), "grid": grid}
