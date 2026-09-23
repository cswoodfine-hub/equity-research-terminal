"""What happens when several assets are each given the whole of the same patient pool.

``forecast.build`` values one asset at a time, which is right for almost everything and
wrong for a crowded indication. The pool identity in ``derive_new_patients`` starts from
the prevalence, takes this drug's share of it, and depletes the pool by this drug's
patients alone. Run eight times for eight competitors it hands each of them a private
copy of the same population.

Obesity is where that bites. Eight modelled assets share one pool of 107,592,242 US
adults, and the sum of what they claim is not checked anywhere, because nothing in the
engine sees more than one asset. Measured on the book as it stands, the eight together
start 29.8mm patients in 2045, 27.7% of the pool in a single year, and hold a treated
stock of 45.8mm, 42.6% of every obese adult in the United States. That is before the
marketed incumbents, which treat perhaps 7 to 8% of the same pool today and are modelled
separately off their own reported revenue.

This module does not decide how large the class will get. No free source publishes that,
and inventing one would be the fabrication this repository forbids. It does something
narrower and defensible: it runs the same identity once over one shared pool instead of
once per asset, so the population is depleted a single time. Each analyst's curve keeps
its shape and its size relative to the others; what goes is the arithmetic in which one
patient is available to eight drugs at once.

Where the claims exceed what is left in a year, every claimant is scaled by the same
factor. That is the neutral rule: it expresses that the pool ran out, not a view about
which competitor wins, which would be a judgement and is not one this module is entitled
to make.

The module reports rather than mutates. ``solve`` returns each asset's crowded and
uncrowded series and the ratio between them, so the cost of the correction can be read
before it is taken.
"""

from __future__ import annotations

import forecast

# Funnel factors the pool identity multiplies through, in the engine's own order.
_FUNNEL = ("diagnosed_pct", "referred_pct", "payer_approved_pct", "accepts_pct")


def _inputs(scalars: dict) -> dict | None:
    """The pool identity's inputs for one asset, or None where it has no funnel."""
    need = ("prevalence", "eligible_pct", "incidence", "penetration_peak_pct",
            "ramp_midpoint_year", "ramp_steepness")
    if any(scalars.get(k) is None for k in need):
        return None
    funnel = 1.0
    for key in _FUNNEL:
        if scalars.get(key) is not None:
            funnel *= scalars[key]
    multiple = 1.0 + (scalars.get("exus_multiple") or 0.0)
    return {"prevalence": scalars["prevalence"], "eligible_pct": scalars["eligible_pct"],
            "incidence": scalars["incidence"], "peak": scalars["penetration_peak_pct"],
            "midpoint": scalars["ramp_midpoint_year"],
            "steepness": scalars["ramp_steepness"], "funnel": funnel,
            "multiple": multiple,
            "carryover": scalars.get("untreated_carryover_pct")}


# Everything the pool identity needs, and where the engine reads each from. Pool factors
# are per indication; the rest are asset-level scalars.
_PER_INDICATION = ("prevalence", "eligible_pct", "incidence", "penetration_peak_pct",
                   "ramp_midpoint_year", "ramp_steepness", "untreated_carryover_pct",
                   "exus_multiple") + _FUNNEL
_PER_ASSET = ("discontinuation_pct", "forecast_start_year")


def claimants(conn, prevalence: float, scenario: str = "base") -> list[dict]:
    """Every modelled asset drawing on the same pool, with the inputs it draws with.

    Assets are matched on the prevalence figure rather than the indication name, because
    the same population is written under several names: obesity, overweight and type 2
    diabetes all carry the 107,592,242 row on these assets.

    Reads the rows directly rather than through ``assumptions.load``. That is deliberate
    and load-bearing: load applies the crowding factor this module computes, so going
    through it here would be a cycle, and the ratio has to be derived from what each
    analyst wrote rather than from an already-adjusted number.
    """
    rows = conn.execute(
        """SELECT DISTINCT s.asset_id, s.indication_id, a.generic_name, c.ticker
             FROM assumptions s
             JOIN assets a ON a.id = s.asset_id
             JOIN companies c ON c.id = a.owner_company_id
            WHERE s.key = 'prevalence' AND s.value = ? AND s.scenario = ?
              AND s.indication_id IS NOT NULL
            ORDER BY c.ticker, a.generic_name""", (prevalence, scenario)).fetchall()
    out = []
    for row in rows:
        per_ind = {r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM assumptions WHERE asset_id = ? AND indication_id = ?"
            "   AND scenario = ? AND year IS NULL",
            (row["asset_id"], row["indication_id"], scenario))}
        per_asset = {r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM assumptions WHERE asset_id = ? AND indication_id IS"
            "  NULL AND scenario = ? AND year IS NULL", (row["asset_id"], scenario))}
        got = _inputs(per_ind)
        if not got or abs(got["prevalence"] - prevalence) > 0.5:
            continue
        name = conn.execute("SELECT name FROM indications WHERE id = ?",
                            (row["indication_id"],)).fetchone()
        out.append({"asset_id": row["asset_id"], "name": row["generic_name"],
                    "ticker": row["ticker"], "indication": name["name"] if name else None,
                    "indication_id": row["indication_id"],
                    "start": per_asset.get("forecast_start_year"),
                    "stop": per_asset.get("discontinuation_pct"), **got})
    return out


# {(prevalence, scenario): {asset_id: ratio}} for the life of a process. The solve is
# cheap but it runs once per asset build, and a book-wide valuation builds hundreds.
_CACHE: dict = {}


def clear_cache() -> None:
    _CACHE.clear()


def ratios(conn, prevalence: float, scenario: str = "base") -> dict:
    """{asset_id: the share of its own forecast this asset keeps once the pool is
    counted once}. Empty where nothing shares the pool, so the common case costs one
    query and changes nothing."""
    key = (round(float(prevalence), 2), scenario)
    if key in _CACHE:
        return _CACHE[key]
    claims = claimants(conn, prevalence, scenario)
    if len(claims) < 2:
        _CACHE[key] = {}
        return _CACHE[key]
    starts = [c["start"] for c in claims if c["start"]]
    first = int(min(starts)) if starts else 0
    last = int(max(starts)) if starts else 0
    got = solve(claims, years=(last - first) + 22, first_year=first)
    out = {a["asset_id"]: a["ratio"] for a in got["assets"]
           if a["pooled"] and a["ratio"] < 1.0 - 1e-9}
    _CACHE[key] = out
    return out


def solve(claims: list[dict], years: int = 30, first_year: int | None = None,
          recycle: bool = True) -> dict:
    """One pool, depleted once, against the same pool depleted once per asset.

    Returns {"years": [...], "assets": [{name, crowded, uncrowded, ratio, ...}],
    "shared": {...}}. ``ratio`` is the crowded peak over the uncrowded peak, which is the
    share of its own forecast an asset keeps once the population is only counted once.

    ``recycle`` returns the patients who stop to the untreated pool, at the asset's own
    discontinuation rate. It matters more here than anywhere else in the book: these
    drugs are stopped by 64.8% of starters within a year, so without it a patient who
    takes one month of therapy in 2032 is treated for ever and the pool drains to nothing.
    The engine does not recycle, because for most products the rate is small and the
    forecast is short. Run over eight competitors and thirty years it is neither, and
    leaving it off charges the whole of a depletion that does not happen to whichever
    asset launches last. Both runs use the same rule, so the comparison is fair either
    way; the default is on because it is the more defensible reading of these assets.
    """
    if not claims:
        return {"years": [], "assets": [], "shared": {}}
    starts = [c["start"] for c in claims if c["start"]]
    first = first_year or (min(starts) if starts else 0)
    calendar = [first + i for i in range(years)]

    def curve(claim, year):
        """This asset's penetration in a calendar year, nil before it launches."""
        offset = year - (claim["start"] or first)
        if offset < 0:
            return 0.0
        mid = claim["midpoint"]
        mid = mid - (claim["start"] or first) if mid > 100 else mid
        return forecast.s_curve(offset, claim["peak"] * claim["funnel"], mid,
                                claim["steepness"])

    # Uncrowded: the engine's own answer, one private pool each.
    uncrowded = {}
    for claim in claims:
        pool = claim["prevalence"] * claim["eligible_pct"] * claim["multiple"]
        inc = claim["incidence"] * claim["eligible_pct"] * claim["multiple"]
        carry = 1.0 if claim["carryover"] is None else claim["carryover"]
        stop = (claim["stop"] or 0.0) if recycle else 0.0
        remaining, series, treated = pool, [], 0.0
        for year in calendar:
            eligible = max(0.0, remaining + inc)
            new = min(curve(claim, year) * eligible, eligible)
            series.append(new)
            quitting = treated * stop
            treated = treated + new - quitting
            remaining = max(0.0, remaining + inc - new + quitting) * carry
        uncrowded[claim["asset_id"]] = series

    # Crowded: one pool for all of them. Where the claims exceed what is left, every
    # claimant is scaled by the same factor, which says the pool ran out without saying
    # who wins.
    #
    # Only assets whose pool is the same population may share it. An asset carrying an
    # ex-US multiple is drawing on a larger one: Pfizer's berobenatide is priced against
    # 166.4mm where the other seven use the US 107.6mm, and pooling those two
    # denominators would be an arithmetic error of the same kind this module exists to
    # correct. The largest group of assets that agree on the pool is the one solved, and
    # any that disagree are returned as ``unpooled`` rather than quietly folded in.
    sizes = {}
    for claim in claims:
        size = round(claim["prevalence"] * claim["eligible_pct"] * claim["multiple"], 2)
        sizes.setdefault(size, []).append(claim)
    shared_size = max(sizes, key=lambda k: (len(sizes[k]), -k))
    pooled = sizes[shared_size]
    unpooled = [c for c in claims if c not in pooled]
    lead = pooled[0]
    pool = shared_size
    inc = lead["incidence"] * lead["eligible_pct"] * lead["multiple"]
    carry = 1.0 if lead["carryover"] is None else lead["carryover"]
    claims_in = pooled
    crowded = {c["asset_id"]: [] for c in claims}
    stops = {c["asset_id"]: ((c["stop"] or 0.0) if recycle else 0.0) for c in claims}
    held = {c["asset_id"]: 0.0 for c in claims}
    remaining, shared = pool, []
    for year in calendar:
        eligible = max(0.0, remaining + inc)
        wanted = {c["asset_id"]: curve(c, year) * eligible for c in claims_in}
        total = sum(wanted.values())
        scale = min(1.0, eligible / total) if total > 0 else 1.0
        quitting = 0.0
        for asset_id, value in wanted.items():
            new = value * scale
            crowded[asset_id].append(new)
            leaving = held[asset_id] * stops[asset_id]
            held[asset_id] = held[asset_id] + new - leaving
            quitting += leaving
        taken = total * scale
        shared.append({"year": year, "started": taken, "pool": eligible,
                       "share": taken / eligible if eligible else 0.0,
                       "treated": sum(held.values()),
                       "rationed": scale < 1.0 - 1e-9})
        remaining = max(0.0, remaining + inc - taken + quitting) * carry

    assets = []
    for claim in claims:
        up = uncrowded[claim["asset_id"]]
        cp = crowded[claim["asset_id"]]
        in_pool = claim in claims_in
        assets.append({**{k: claim[k] for k in ("asset_id", "name", "ticker",
                                                "indication", "peak", "start")},
                       "uncrowded": up, "crowded": cp if in_pool else up,
                       "pooled": in_pool,
                       "ratio": (max(cp) / max(up)) if (in_pool and max(up)) else 1.0})
    return {"years": calendar, "assets": assets, "shared": shared, "pool": pool,
            "unpooled": [{"name": c["name"], "ticker": c["ticker"],
                          "pool": round(c["prevalence"] * c["eligible_pct"]
                                        * c["multiple"], 2)} for c in unpooled],
            "rationed_years": sum(1 for s in shared if s["rationed"])}


def summary(got: dict) -> dict:
    """The two numbers a reader needs: what the uncrowded book claims of the pool, and
    what one pool can actually supply."""
    if not got.get("shared"):
        return {}
    pool = got["pool"]
    per_year = []
    for i, row in enumerate(got["shared"]):
        want = sum(a["uncrowded"][i] for a in got["assets"] if a.get("pooled", True))
        per_year.append({"year": row["year"], "uncrowded": want, "crowded": row["started"],
                         "uncrowded_share": want / pool if pool else 0.0,
                         "crowded_share": row["started"] / pool if pool else 0.0})
    worst = max(per_year, key=lambda r: r["uncrowded_share"])
    return {"peak_year": worst["year"], "uncrowded_share": worst["uncrowded_share"],
            "crowded_share": worst["crowded_share"], "by_year": per_year,
            "rationed_years": got["rationed_years"]}
