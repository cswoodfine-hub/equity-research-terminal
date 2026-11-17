"""An asset's cash profile: what is spent before it sells and what comes back after.

A view beside the valuation, never in it, as ``development`` is. The valuation discounts
the forecast's free cash flow and stops there; this lays the same cash flows out by
calendar year beside the cost still to be spent reaching the market, and reads three
things off the pair: the cumulative curve, the internal rate of return and the year the
outlay is earned back.

Two cases are drawn, because they answer different questions.

  If it succeeds. Every stage's remaining cost in full and the forecast's cash flows in
  full: what a sponsor who carries the programme to approval lays out and gets back.

  Weighted by its chances. Each stage's cost times the chance the stage is entered (the
  first is being run; a later one is reached only if every gate before it passes) and
  the cash flows times the probability in force, the one the rNPV uses. This is the
  expected profile, and the one a buyer pricing the risk would discount.

What the figures rest on, and where they lean:

- The inflows are ``forecast``'s FCFF by year: after cost of sales, SG&A, the company's
  R&D ratio, other costs, tax and growth investment, at the company's share of the
  asset. The R&D ratio on revenue is the company funding its pipeline, so the trial
  costs laid out here are charged beside it, not netted against it. The return
  therefore reads low rather than high.
- The outlays are ``development``'s: published per-patient and per-programme costs
  (Sertkaya 2024, analogue-graded), only the spend still ahead, after tax where the
  deduction can be used. Where development cannot read a cost (a marketed product, a
  vaccine, stated legs, a study with no enrolment) there is no outlay on file, the
  profile is the inflows alone, and no return is stated: a return on an unknown outlay
  is not a number.
- The return counts the model's terminal value in the final forecast year, as the
  valuation does. The cumulative curve and the payback year do not: they are the
  explicit years only.
- Flows are taken mid-year, as the valuation takes them.

Nothing here is estimated. A figure that cannot be had is None with the reason.
"""

from __future__ import annotations

import datetime as dt

import development
import forecast_view

# A return is searched for between these. Above the upper one the spend still ahead is
# small beside what comes back (an asset a year from approval), and the figure is
# arithmetic rather than information, so it is reported as "above" and not stated.
IRR_LOW, IRR_HIGH = -0.99, 2.0


def irr(flows: list) -> float | None:
    """The rate at which dated flows net to nil, or None where they never change sign
    (an outlay with nothing back, or cash with no outlay) or no rate in the bracket
    solves it. ``flows`` is [(years from the first flow, amount)]."""
    amounts = [a for _, a in flows if a]
    if not amounts or min(amounts) >= 0 or max(amounts) <= 0:
        return None

    def npv(rate: float) -> float:
        return sum(a / (1.0 + rate) ** t for t, a in flows)

    lo, hi = IRR_LOW, IRR_HIGH
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None            # outside the bracket: see irr_above
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-9 or hi - lo < 1e-10:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def irr_above(flows: list) -> bool:
    """True where the flows change sign and still net positive at IRR_HIGH: the return
    is above the bracket."""
    amounts = [a for _, a in flows if a]
    if not amounts or min(amounts) >= 0 or max(amounts) <= 0:
        return False
    return sum(a / (1.0 + IRR_HIGH) ** t for t, a in flows) > 0


def _case(years: list, outlay: list, cash: list, terminal: float) -> dict:
    """One case's rows and what is read off them. ``outlay`` is positive money out."""
    net = [c - o for o, c in zip(outlay, cash)]
    cumulative, run = [], 0.0
    for value in net:
        run += value
        cumulative.append(run)
    low = min(cumulative) if cumulative else 0.0
    trough = cumulative.index(low) if cumulative and low < 0 else None
    payback = None
    if trough is not None:
        payback = next((years[i] for i in range(trough, len(years)) if cumulative[i] >= 0),
                       None)
    flows = [(i + 0.5, v) for i, v in enumerate(net)]
    if flows and terminal:
        flows[-1] = (flows[-1][0], flows[-1][1] + terminal)
    return {"net": net, "cumulative": cumulative,
            "deepest": low if trough is not None else None,
            "deepest_year": years[trough] if trough is not None else None,
            "payback_year": payback, "irr": irr(flows), "irr_above": irr_above(flows),
            "total": cumulative[-1] if cumulative else None}


def for_asset(db_path, ticker: str, asset_id: int, scenario: str = "base",
              today: dt.date | None = None) -> dict | None:
    """The cash profile of one asset, or None where the company holds no such asset."""
    try:
        view = forecast_view.asset_forecast(db_path, ticker, asset_id, scenario)
    except LookupError:
        return None
    if view is None:
        return None
    base = {"ticker": ticker.upper(), "asset_id": asset_id, "name": view.get("name"),
            "scenario": scenario}
    if not view.get("ok"):
        return {**base, "ok": False, "reason": "no_forecast",
                "why": "No forecast builds for this asset, so there is no cash flow to lay out."}
    result = view["result"]
    f_years, pnl = list(result["years"]), result["pnl"]
    dev = development.for_asset(db_path, ticker, asset_id, today) if scenario == "base" else None
    spend = (dev or {}).get("spend_by_year") if (dev or {}).get("ok") else None
    if dev and dev.get("ok"):
        portion = dev["portion"]
    else:
        share = result.get("economics_share")
        portion = share if share is not None else 1.0
    pos = result.get("pos")

    if spend is not None:
        first = min([y for s in spend for y in s["years"]] + [f_years[0]])
        outlay_why = None
    else:
        first = f_years[0]
        outlay_why = ((dev or {}).get("why") if dev and not dev.get("ok") else
                      "A stage's cost cannot be read from the registry."
                      if dev and dev.get("ok") else
                      "The cost view reads the base scenario only." if scenario != "base"
                      else "No cost to reach the market is on file for this asset.")
    years = list(range(first, f_years[-1] + 1))
    cash = [0.0] * len(years)
    for year, row in zip(f_years, pnl):
        cash[years.index(year)] = row["fcff"] * portion
    full = [0.0] * len(years)
    risked = [0.0] * len(years)
    for stage in spend or []:
        for year, amount in stage["years"].items():
            if year in years:
                full[years.index(year)] += amount
                risked[years.index(year)] += amount * stage["p_enter"]
    terminal = (result.get("terminal_value") or 0.0) * portion
    success = _case(years, full, cash, terminal)
    weighted = (_case(years, risked, [c * pos for c in cash], terminal * pos)
                if pos is not None else None)
    if spend is None:
        # No outlay on file: the curves are the inflows alone and no return is stated.
        for case in (success, weighted):
            if case:
                case.update({"irr": None, "irr_above": False, "payback_year": None,
                             "deepest": None,
                             "deepest_year": None})
    return {
        **base, "ok": True, "currency": (dev or {}).get("currency"),
        "mode": result.get("mode"), "portion": portion, "pos": pos, "wacc": result.get("wacc"),
        "years": years, "launch_year": f_years[0], "loe_year": result.get("loe_year"),
        "cash": cash, "outlay": full if spend is not None else None,
        "outlay_risked": risked if spend is not None else None,
        "outlay_why": outlay_why,
        "outlay_reason": ((dev or {}).get("reason") if dev and not dev.get("ok") else None),
        "outlay_total": sum(full) if spend is not None else None,
        "irr_ceiling": IRR_HIGH,
        "outlay_stages": ([{"gate": s["gate"], "label": s["label"], "p_enter": s["p_enter"],
                            "amount": sum(s["years"].values())} for s in spend]
                          if spend is not None else None),
        "terminal_value": terminal, "success": success, "weighted": weighted,
        "after_tax": (dev or {}).get("after_tax"), "tax_basis": (dev or {}).get("tax_basis"),
        "sources": (dev or {}).get("sources"),
        "notes": ["The inflows are the forecast's free cash flow, after the company's R&D "
                  "ratio on revenue; the trial costs here are charged beside that, so the "
                  "return reads low rather than high.",
                  "The return counts the model's terminal value in the final forecast "
                  "year. The curve and the payback year count the explicit years only."],
    }
