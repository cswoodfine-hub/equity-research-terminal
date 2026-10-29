"""A product's value at the bear, base and bull ends of its LOE range.

``loe.date_range`` gives the dates: the molecule patent at the bear end, the latest
substance or product patent at the bull end, the book's own date in between (the range
held 89% of 122 past generic launches, work/patents/BACKTEST.md). This values each end
through the engine's own stated-year lever, the one the LOE slider uses, so the three
figures differ only in the cliff year.

A view beside the valuation, never in it: the base date stays the value everywhere.
"""

from __future__ import annotations

import copy

import assumptions as assumptions_module
import forecast
import loe as loe_module


def _npv(inputs: dict, year: int | None):
    built = copy.deepcopy(inputs)
    if year is not None:
        built.setdefault("scalars", {})["loe_year"] = year
    try:
        return forecast.build(built).get("npv")
    except forecast.ForecastError:
        return None


def for_asset(conn, asset_id: int, scenario: str = "base", found=None,
              inputs=None) -> dict | None:
    """{bear, base, bull: {date, npv}, why...} or None where the asset has no LOE date or
    no forecast. A range of one date (a settled date, or nothing either side) is returned
    with the three ends equal, so a reader sees that it has none.

    ``found`` (the asset's ``loe.for_assets`` entry) and ``inputs`` (its loaded
    assumptions) may be passed by a caller that already holds them, as the company view
    does for every product at once."""
    if found is None:
        found = loe_module.for_assets(conn, [asset_id], exclude_orphan=True).get(asset_id)
    rng = loe_module.date_range(found)
    if not rng:
        return None
    if inputs is None:
        inputs = assumptions_module.load(conn, asset_id, scenario)
    if not inputs or not inputs.get("scalars"):
        return None
    base_npv = _npv(inputs, None)
    if base_npv is None:
        return None
    out = {"why_bear": rng.get("bear_why") or rng.get("why"),
           "why_bull": rng.get("bull_why") or rng.get("why")}
    for end in ("bear", "base", "bull"):
        date = rng[end]
        npv = base_npv if end == "base" or date == rng["base"] else _npv(inputs, int(date[:4]))
        out[end] = {"date": date, "npv": npv}
    return out
