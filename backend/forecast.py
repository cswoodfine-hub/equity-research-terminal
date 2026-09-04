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
MODES = ("one_time", "chronic", "marketed", "franchise")


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


def patients_for_indication(ind: dict, years: list[int], notes: list,
                            curve_defaults=None, mode=None) -> dict:
    """One indication's patient series: the explicit hand series where the analyst gave
    one, the derived identity beside it where its inputs exist.

    Returns {"used": [...], "explicit": [...] | None, "derived": [...] | None,
    "basis": str, "curve_basis": str | None}. ``used`` is what revenue is built on.

    ``curve_defaults`` are the placeholder peak and midpoint from data/curve_defaults.csv,
    used only where an indication has every other pool input and lacks exactly those
    two. Six of eight pipeline assets were blocked on them and drew nothing. An asset on
    the placeholder draws a curve to be argued with, says so in ``curve``, and is kept out
    of any per-share number by the caller until a real value is committed.
    """
    scalars = ind.get("scalars") or {}
    series = ind.get("series") or {}
    curve_basis = None

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
    placeholder = (curve_defaults or {}).get(mode)
    if (placeholder and None not in (prevalence, eligible_pct, incidence, steepness)
            and (peak is None or midpoint is None)):
        peak = float(placeholder["penetration_peak_pct"]) if peak is None else peak
        midpoint = (float(placeholder["ramp_midpoint_year"]) if midpoint is None
                    else midpoint)
        curve_basis = f"placeholder curve, {placeholder['source']}"
        notes.append(f"{ind.get('name', 'indication')}: drawn on a placeholder curve, "
                     f"{peak:.0%} of the eligible pool at peak and half of it by year "
                     f"{midpoint:.0f}. Not a forecast of uptake; set both from the curve "
                     f"shaper")
    elif peak is not None and midpoint is not None:
        curve_basis = "stated"
    if None not in (prevalence, eligible_pct, incidence, peak, midpoint, steepness):
        multiple = 1.0 + (scalars.get("exus_multiple") or 0.0)
        pool = prevalence * eligible_pct * multiple
        # Incidence feeds the same eligible pool, so it passes the same eligibility
        # filter as prevalence. Feeding raw births into a severe-and-of-age pool
        # overstated the inflow 6x for sickle cell: 2,000 births a year are not 2,000
        # patients with two crises a year aged twelve or more. The ex-US multiple scales
        # it too, which is an assumption of its own and is said aloud.
        inc = incidence * eligible_pct * multiple
        if scalars.get("exus_multiple"):
            notes.append(f"{ind.get('name', 'indication')}: incidence filtered by the "
                         f"eligibility share ({eligible_pct:.0%}) and scaled with the "
                         f"pool by the ex-US multiple ({multiple:.1f}x US)")
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
            "explicit": explicit, "derived": derived, "basis": basis,
            "curve_basis": curve_basis}


# --- money -------------------------------------------------------------------

def treated_stock(new_patients, discontinuation, opening=0.0):
    """The patients on therapy each year, from the patients who start each year.

    A chronic therapy is not billed once. Someone who starts in 2027 and stays on it is
    revenue in 2028 and 2029 too, so the number that meets the annual price is the stock
    still being treated, not the year's new starts.

    Until this existed both modes ran the same line, and the pool identity that feeds it
    computes new starts while depleting a prevalent pool. That is the shape of a one-time
    therapy, which is why Zolgensma plateaued, and it is the wrong shape for a drug people
    take every week: it understated the stock in every year after the first and then
    decayed to an incidence run rate that a chronic product does not have.

        stock(t) = stock(t-1) * (1 - discontinuation) + new(t)

    ``discontinuation`` is the share of the treated stock that stops each year. At 1.0
    nobody carries over and the series collapses to new starts, which is exactly the old
    behaviour. ``opening`` is the stock already on therapy in the year before the first,
    which is what separates a launch from a product that is already selling.
    """
    out, stock = [], float(opening)
    for started in new_patients:
        stock = stock * (1.0 - discontinuation) + started
        out.append(stock)
    return out




def grown_revenue(base: float, growth: float, years: int,
                  fade_to: float | None = None, fade_years: int = 5,
                  ceiling: float | None = None) -> list:
    """A launched product's revenue, carried forward from what it actually did.

    Nobody rebuilds the patient funnel for a drug already selling ten billion a year. The
    reported number is the anchor, growth is the judgement, and the erosion the LOE map
    already carries does the rest.

    Growth fades, because a near-term rate is not a long-run one and holding one constant
    across a fifteen-year window produces arithmetic rather than a forecast. Vertex guides
    the CF franchise to about 9.6% for one year; held flat to 2037 that is 31bn of
    Trikafta, which at its net price is close to three times the entire US CF population.
    Journavx's launch rate of 66% held to 2043 is 570bn, which is larger than the industry.
    Neither is a view anybody holds, and both came out of the model before this existed.

    So the rate decays linearly from ``growth`` to ``fade_to`` across ``fade_years`` and
    stays there. With ``fade_to`` unset the rate is constant, which is the old behaviour
    and still right for a short horizon.

    A fading rate is not always enough. Vertex is switching its CF patients from Trikafta
    to Alyftrek, and read off the halves those two grow at -4.6% and +176%: one pool of
    patients, moving. Alyftrek compounded off its own launch rate passes the entire CF
    franchise in three years and reaches 26bn in five, because nothing in a growth rate
    knows the pool is finite. ``ceiling`` is that bound, and it binds the level rather
    than the rate, so a product that reaches it stays there instead of growing through it.

    Year one is the base grown once, because the base is last year's reported figure and
    the forecast starts after it.
    """
    out, level = [], base
    for i in range(years):
        if fade_to is None or fade_years <= 0:
            rate = growth
        elif i >= fade_years:
            rate = fade_to
        else:
            rate = growth + (fade_to - growth) * (i / fade_years)
        level *= (1.0 + rate)
        if ceiling is not None:
            level = min(level, ceiling)
        out.append(level)
    return out



def share_path(now: float, plateau: float, ramp: float, years: int) -> list:
    """A product's share of its franchise, closing the gap to a plateau each year.

    ``share(t) = plateau + (now - plateau) * exp(-ramp * t)``. Monotone, bounded between
    the two, and it runs in either direction: the product taking share approaches its
    plateau from below, the one giving it up approaches from above. ``ramp`` is the rate
    the remaining gap closes, so ln(2)/ramp is the half-life of the switch.

    Two products that share one pool of patients cannot be forecast apart. Trikafta and
    Alyftrek were, on their own growth rates of -4.6% and +176%, and the pair carried 40%
    more revenue by 2028 than the franchise they are both inside. Growth is the wrong
    quantity: it is share that Vertex reports and share that is well behaved. Alyftrek
    went 2.0%, 5.4%, 14.6%, 17.9% across four quarters while Trikafta went 92.4%, 87.9%,
    80.8%, 77.8%, which is one number and its complement.

    Members of one franchise sharing a ramp is what makes the split an identity rather
    than an arrangement. The shares then sum to

        sum(plateau) + (sum(now) - sum(plateau)) * exp(-ramp * t)

    so shares that sum to one at the base year and at the plateau sum to one in every
    year between, whatever the ramp. Nothing can be counted twice, and no member needs to
    know what the others hold.
    """
    return [plateau + (now - plateau) * math.exp(-ramp * (i + 1)) for i in range(years)]


def net_price(scalars: dict):
    """Net price per patient, given directly or as list price less gross-to-net."""
    if scalars.get("net_price_per_patient") is not None:
        return scalars["net_price_per_patient"]
    lp, gtn = scalars.get("list_price_per_patient"), scalars.get("gross_to_net_pct")
    if lp is not None and gtn is not None:
        return lp * (1.0 - gtn)
    return None


def _price_factor(scalars: dict, year_index: int) -> float:
    """What a year's net price is as a share of the first year's.

    A price built from patients and a price per patient was multiplied by one number for
    the whole horizon, so a twenty-year forecast charged 2046 at 2027's price. That is
    not what a net price does in a class with competitors: Lilly reports its US realised
    price falling while volume rises, and holding it flat prices away the discount that
    won the volume.

    Absent, the price is flat and nothing changes. This never carries the fall at loss of
    exclusivity, which the erosion module applies to revenue further down: that is a
    different event with its own evidence, and charging both would count it twice.
    """
    decline = scalars.get("net_price_decline_pct")
    return 1.0 if not decline else (1.0 - decline) ** year_index


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
    """(pos, basis). A stated value first, then composite factors, then the phase ramp.

    The most explicit statement wins. A launched asset usually states its factors (the
    workbook's regulatory x launch x reimbursement x durability) and no single value,
    so factors carry it; but a scenario that writes one ``pos`` row means exactly that
    number, and must not lose to the base factors it inherits alongside. A pipeline
    asset with neither falls to the curated phase ramp, and the basis says which
    happened.
    """
    if scalars.get("pos") is not None:
        return scalars["pos"], "stated"
    factors = [scalars.get(k) for k in ("pos_regulatory", "pos_launch",
                                        "pos_reimbursement", "pos_durability")]
    if any(f is not None for f in factors):
        composite = 1.0
        for f in factors:
            composite *= 1.0 if f is None else f
        return composite, "composite factors"
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
    # What stands between the three expense lines a filer tags and the cash it actually
    # generates: amortisation of acquired intangibles above all, then restructuring and
    # the rest. Cost of sales, SG&A and R&D are the only expenses in the data sets, and
    # for a company that has bought its pipeline they are not most of its costs. Pfizer's
    # three lines leave a 33.8% cash margin against the 12.8% it has actually earned
    # since the COVID years, so a model without this values it at nearly three times the
    # cash it makes. Zero where a company's filed lines already reconcile to its cash.
    other = scalars.get("other_costs_pct") or 0.0
    rows = []
    for rev, pats in zip(revenue, patients):
        if mode == "one_time":
            cogs = (scalars.get("cogs_per_patient") or 0.0) * pats
        else:
            cogs = (scalars.get("cogs_pct") or 0.0) * rev
        ebit = rev - cogs - sga * rev - rd * rev - other * rev
        taxed = max(0.0, ebit * tax)
        rows.append({"revenue": rev, "cogs": cogs, "sga": sga * rev, "rd": rd * rev,
                     "other": other * rev, "ebit": ebit, "tax": taxed,
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
    franchise = None
    curve_basis = None
    price = net_price(scalars)
    missing = [k for k in ("therapy_mode",) if not mode]
    if mode == "marketed":
        # Anchored on reported revenue, so a price per patient is the wrong question.
        if scalars.get("base_revenue") is None:
            missing.append("base_revenue (last reported full year, mm)")
        if scalars.get("revenue_growth_pct") is None:
            missing.append("revenue_growth_pct (annual, before LOE erosion)")
    elif mode == "franchise":
        # Anchored on the pool it takes a share of, so neither a price per patient nor a
        # growth rate of its own is the question.
        for key, what in (
                ("franchise_revenue", "the pool's last reported full year, mm"),
                ("franchise_growth_pct", "annual growth of the pool, not of this product"),
                ("share_now", "this product's share of the pool in the base year"),
                ("share_plateau", "the share it settles at"),
                ("share_ramp_pct", "rate the gap to the plateau closes each year; every "
                                   "member of one franchise must use the same one")):
            if scalars.get(key) is None:
                missing.append(f"{key} ({what})")
    elif price is None:
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

    # A launched product is anchored on what it reported, so it never enters the patient
    # build at all: there is no funnel to rebuild for a drug already selling.
    if mode == "marketed":
        base_rev = scalars["base_revenue"]
        growth = scalars["revenue_growth_pct"]
        ceiling = scalars.get("revenue_ceiling_musd")
        revenue = grown_revenue(
            base_rev, growth, len(years),
            fade_to=scalars.get("terminal_growth_pct"),
            fade_years=int(scalars.get("growth_fade_years") or 5),
            ceiling=ceiling)
        per_indication = {}
        treated = total_patients = [None] * len(years)
        fade = scalars.get("terminal_growth_pct")
        notes.append(
            f"marketed mode: revenue grown from a reported {base_rev:,.0f}mm at "
            f"{growth:+.1%}"
            + (f", fading to {fade:+.1%} over "
               f"{int(scalars.get('growth_fade_years') or 5)} years"
               if fade is not None else " held flat")
            + ", before erosion")
        if ceiling is not None and revenue and max(revenue) >= ceiling - 1e-9:
            notes.append(
                f"revenue is held at a ceiling of {ceiling:,.0f}mm from "
                f"{years[revenue.index(ceiling)] if ceiling in revenue else years[-1]} "
                "onward, so the growth rate above describes the years before it only")
    elif mode == "franchise":
        pool_base = scalars["franchise_revenue"]
        pool_growth = scalars["franchise_growth_pct"]
        fade = scalars.get("terminal_growth_pct")
        pool = grown_revenue(
            pool_base, pool_growth, len(years), fade_to=fade,
            fade_years=int(scalars.get("growth_fade_years") or 5))
        shares = share_path(scalars["share_now"], scalars["share_plateau"],
                            scalars["share_ramp_pct"], len(years))
        revenue = [p * s for p, s in zip(pool, shares)]
        franchise = {"revenue": pool, "share": shares}
        per_indication = {}
        treated = total_patients = [None] * len(years)
        notes.append(
            f"franchise mode: a pool of {pool_base:,.0f}mm growing {pool_growth:+.1%}"
            + (f", fading to {fade:+.1%} over "
               f"{int(scalars.get('growth_fade_years') or 5)} years"
               if fade is not None else " held flat")
            + f", of which this product holds {shares[0]:.1%} in {years[0]} and "
              f"{shares[-1]:.1%} by {years[-1]}, against a plateau of "
              f"{scalars['share_plateau']:.1%}")
        notes.append(
            "the share is what is forecast here, not the revenue. A product taking a "
            "franchise off another cannot be grown at a rate of its own without the two "
            "together outgrowing the pool they share")
    else:
        # Patients, per indication and in total.
        per_indication = {}
        for ind in inputs.get("indications") or []:
            result = patients_for_indication(ind, years, notes,
                                             inputs.get("curve_defaults"), mode)
            if (result.get("curve_basis") or "").startswith("placeholder"):
                curve_basis = result["curve_basis"]
            elif result.get("curve_basis") == "stated" and curve_basis is None:
                curve_basis = "stated"
            if result["used"] is None:
                continue
            per_indication[ind.get("name")
                           or f"indication {len(per_indication) + 1}"] = result
        if not per_indication:
            raise ForecastError(["no indication has a usable patient series: supply "
                                 "new_patients rows or the pool identity inputs"])
        total_patients = [sum(per_indication[n]["used"][i] for n in per_indication)
                          for i in range(len(years))]

    if mode in ("marketed", "franchise"):
        pass                    # revenue is already built above
    elif mode == "one_time":
        # Billed once, so the year's patients are the year's revenue.
        treated = total_patients
        revenue = [p * price * _price_factor(scalars, i)
                   for i, p in enumerate(treated)]
    else:
        discontinuation = scalars.get("discontinuation_pct")
        if discontinuation is None:
            raise ForecastError([
                "discontinuation_pct (share of the treated stock that stops each year; "
                "chronic revenue is the stock still on therapy, not the year's new "
                "starts, and without this the two cannot be told apart)"])
        opening = scalars.get("opening_treated_patients") or 0.0
        treated = treated_stock(total_patients, discontinuation, opening)
        revenue = [p * price * _price_factor(scalars, i)
                   for i, p in enumerate(treated)]
        notes.append(
            f"chronic mode: revenue is the treated stock x annual net price, carried "
            f"forward at {(1 - discontinuation):.0%} persistence a year"
            + (f" from an opening {opening:,.0f} already on therapy" if opening else ""))
        if scalars.get("net_price_decline_pct"):
            fall = scalars["net_price_decline_pct"]
            notes.append(
                f"net price falls {fall:.1%} a year, so the last forecast year is priced "
                f"at {_price_factor(scalars, len(years) - 1):.0%} of the first. Loss of "
                f"exclusivity is not in this and is applied separately")

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
        # total is who started each year; treated is who is still on it, which is what
        # meets the price. They are the same series only for a one-time therapy.
        "patients": {"total": total_patients, "treated": treated,
                     "by_indication": per_indication},
        "revenue": revenue, "revenue_after_loe": eroded, "pnl": pnl,
        # The pool and this product's share of it, for franchise mode. None elsewhere.
        "franchise": franchise,
        "wacc": rate, "wacc_basis": rate_basis,
        "pos": probability, "pos_basis": pos_basis,
        # "stated", or "placeholder curve, ..." where the uptake ceiling and midpoint came
        # from data/curve_defaults.csv rather than the asset. None where no curve is built.
        "curve_basis": curve_basis,
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
