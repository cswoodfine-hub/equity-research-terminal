"""What the price implies, stated as claims the filings can later test.

The break-points (breakpoints.py) solve one assumption at a time, and a price far from
the book sends a single lever somewhere nobody would hold: Lilly's price is reached by
one lever alone only with Mounjaro peaking near $370bn. A price is a claim on the whole
book, so this asks it the questions an analyst would put to a market price:

- **Revenue level.** One factor on every product's and line's revenue path, its level
  and its ceiling together, so each path keeps its shape. The current year is held at the
  model, since it is mostly reported and guided: its extra cash flow is taken back out at
  its present value, which is exact because the engine charges every cost as a share of
  revenue. Read as the revenue the price needs in each of the next years beside the
  model's, and the top product's peak beside its modelled peak. Revenue is reported every
  quarter, so this is the claim a filing settles first.
- **Durability.** Every product's loss of exclusivity moved by the same number of years,
  at the model's revenue. Lines are held: they carry no single cliff.
- **Both together.** The revenue factor needed with exclusivity held 5 and 10 years
  longer, so the trade between how big and how long reads off one row.
- **The return on offer.** One shift on every discount rate: the rate at which the
  model's cash flows meet the price. Where the model reads above the price it is the
  return the price offers if the model is right; below, what the market accepts.

Every trial runs the real engine through breakpoints.Book, so the future pipeline and the
growth charge move with each trial exactly as they do for a break-point. Nothing is
written: the claims are read, not stored.
"""

from __future__ import annotations

import math

import breakpoints as B
import db
import fair_value as FV
import forecast
import forecast_view as V

YEARS_AHEAD = 4                     # the years of revenue shown after the guided year
SCALE = (0.05, 20.0)                # the revenue factor, as a multiple of the model's
EXTRA = (-10, 40)                   # years of exclusivity added to every product
FRONTIER = (5, 10)                  # the extra years the revenue factor is solved at
RATE_SHIFT = (-0.07, 0.20)          # one shift on every discount rate


def _scaled(inputs: dict, factor: float) -> dict | None:
    """A product's inputs with its revenue path moved by ``factor``: the reported base and
    the ceiling for a marketed product, the pool for a franchise, the net price for a
    product built from patients. None where the product has no level to move."""
    scalars = dict(inputs.get("scalars") or {})
    if scalars.get("base_revenue"):
        scalars["base_revenue"] *= factor
        if scalars.get("revenue_ceiling_musd"):
            scalars["revenue_ceiling_musd"] *= factor
        return {**inputs, "scalars": scalars}
    if scalars.get("franchise_revenue"):
        scalars["franchise_revenue"] *= factor
        return {**inputs, "scalars": scalars}
    price = forecast.net_price(scalars)
    if price:
        return V.apply_lever(inputs, "net_price_per_patient", price * factor)
    return None


def _later(part: dict, inputs: dict, extra: int) -> dict | None:
    """A product's inputs with its loss of exclusivity ``extra`` years later. None where
    it has no cliff ahead: none on file, or one the reported revenue already shows. An
    earlier cliff stops at the year before the forecast window, as a break-point does."""
    loe = part.get("loe_year")
    if not extra or loe is None or part.get("loe_in_base"):
        return None
    years = part.get("years") or []
    year = loe + extra
    if years:
        year = max(year, years[0] - 1)
    return V.apply_lever(inputs, "loe_year", int(year))


def held_year_value(book: B.Book, year: int) -> float:
    """Equity per share in the year's free cash flow across the book, at each part's own
    rate, mid-year from the valuation anchor and carried to the price date as the book
    is. Pipeline cash flow is risked at its probability, as the model holds it."""
    total = 0.0
    for part in book.parts:
        years = list(part.get("dcf_years") or [])
        rows = part.get("pnl_share") or []
        if year not in years or years.index(year) >= len(rows):
            continue
        at = years.index(year)
        fcff = rows[at].get("fcff") or 0.0
        if "asset_id" in part and not part.get("is_marketed"):
            fcff *= part.get("pos") if part.get("pos") is not None else 1.0
        total += fcff / (1.0 + (part.get("wacc") or 0.07)) ** (at + 0.5)
    return book.per_share(total * book.carry)


class Claims:
    """One company's book, asked what the price implies."""

    def __init__(self, book: B.Book, held_year: int | None = FV.GUIDED_YEAR):
        self.book = book
        # A revenue factor moves the held year too; its extra cash flow is taken back
        # out so the claim falls on the years still to be reported.
        self.held = held_year_value(book, held_year) if held_year is not None else 0.0

    def gap(self, factor: float = 1.0, extra: int = 0, shift: float = 0.0) -> float:
        """Equity per share less the close with every revenue path moved by ``factor``,
        every product's exclusivity ``extra`` years later and every discount rate moved
        by ``shift``."""
        def asset_trial(part, inputs):
            trial = inputs
            if factor != 1.0:
                trial = _scaled(trial, factor) or trial
            if extra:
                trial = _later(part, trial, extra) or trial
            if shift:
                trial = V.apply_lever(trial, "wacc", (part.get("wacc") or 0.07) + shift)
            return None if trial is inputs else trial

        def line_trial(part, scalars):
            out = dict(scalars)
            if factor != 1.0 and out.get("base_revenue"):
                out["base_revenue"] *= factor
                if out.get("revenue_ceiling_musd"):
                    out["revenue_ceiling_musd"] *= factor
            if shift:
                out["wacc"] = (part.get("wacc") or 0.07) + shift
            return None if out == scalars else out
        return self.book.gap_with(asset_trial, line_trial) - (factor - 1.0) * self.held

    def revenue_factor(self, extra: int = 0) -> dict:
        return B.solve(lambda k: self.gap(factor=k, extra=extra), 1.0, *SCALE)

    def durability(self) -> dict:
        return B.solve(lambda d: self.gap(extra=int(d)), 0, *EXTRA, integer=True)

    def rate_shift(self) -> dict:
        return B.solve(lambda s: self.gap(shift=s), 0.0, *RATE_SHIFT)


def _currency(db_path, company_id: int) -> str | None:
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT reporting_currency FROM companies WHERE id = ?",
                           (company_id,)).fetchone()
        return row["reporting_currency"] if row else None
    finally:
        conn.close()


def company(db_path, ticker: str) -> dict | None:
    """The claims the price makes on one company's book. None for an unknown ticker;
    {"ok": False, "reason"} where the value or the price is not on file."""
    book = B.Book(db_path, ticker)
    if book.verdict is None:
        return None
    if not book.ok:
        return {"ok": False, "ticker": book.verdict["ticker"], "reason": book.reason}
    claims = Claims(book)
    found = claims.revenue_factor()
    factor = found["value"]
    first = FV.GUIDED_YEAR
    revenue = []
    for year in range(first, first + YEARS_AHEAD + 1):
        model = FV.model_revenue(book, year)["total"]
        held = year == first
        revenue.append({"year": year, "model": model, "held": held,
                        "implied": (model if held else model * factor)
                        if factor is not None else None})
    top = max(book.counted, key=lambda p: abs(p.get("rnpv_share") or 0.0), default=None)
    peak = None
    if top is not None and top.get("peak_revenue"):
        # The product's own revenue before any partner's share, as the verdict states it.
        model_peak = top["peak_revenue"]
        peak = {"name": top["name"], "year": top.get("peak_year"), "model": model_peak,
                "implied": model_peak * factor if factor is not None else None}
    later = claims.durability()
    frontier = [{"extra_years": 0, "factor": factor, "reachable": found["reachable"]}]
    for extra in FRONTIER:
        got = claims.revenue_factor(extra)
        frontier.append({"extra_years": extra, "factor": got["value"],
                         "reachable": got["reachable"]})
    model_rate = (book.sotp.get("future") or {}).get("wacc") or 0.07
    shift = claims.rate_shift()
    return {
        "ok": True, "ticker": book.ticker, "name": book.name, "close": book.close,
        "equity_per_share": book.equity, "gap_per_share": book.close - book.equity,
        "direction": "up" if book.equity < book.close else "down",
        "currency": _currency(db_path, book.company_id),
        "revenue": {"factor": factor, "reachable": found["reachable"], "years": revenue,
                    "basis": ("every product's and line's revenue path moved by one "
                              f"factor, level and ceiling together, {first} held at the "
                              "model; pipeline revenue risked, as the model holds it")},
        "peak": peak,
        "durability": {"extra_years": later["value"], "reachable": later["reachable"],
                       "basis": ("every product's loss of exclusivity moved by the same "
                                 "years at the model's revenue; lines held")},
        "frontier": frontier,
        "rate": {"model": model_rate,
                 "implied": (model_rate + shift["value"]
                             if shift["value"] is not None else None),
                 "reachable": shift["reachable"],
                 "basis": ("one shift on every product's and line's discount rate; the "
                           "book's revenue-weighted rate is shown")},
        "held": ["every other assumption", "the cost of equity carrying the year-end "
                 "value to the price date"],
    }


def _bn(mm: float | None, currency: str | None) -> str:
    if mm is None or (isinstance(mm, float) and math.isnan(mm)):
        return "n/a"
    symbol = "$" if currency in (None, "USD") else f"{currency} "
    return f"{symbol}{mm / 1000:,.0f}bn" if abs(mm) >= 10_000 else f"{symbol}{mm / 1000:,.1f}bn"


def sentence(result: dict) -> list[str]:
    """The claims as a few analyst sentences, the number first."""
    if not result.get("ok"):
        return []
    cur = result["currency"]
    name, close = result["name"], result["close"]
    rev, rate = result["revenue"], result["rate"]
    out = []
    factor = rev["factor"]
    if factor is not None:
        target = next((r for r in rev["years"] if r["year"] == FV.GUIDED_YEAR + 2), None)
        lead = (f"At ${close:,.2f} the price implies every product sells {factor:.2f} times "
                f"what the model forecasts")
        if target:
            lead += (f": {_bn(target['implied'], cur)} of revenue in {target['year']} "
                     f"against the model's {_bn(target['model'], cur)}")
        out.append(lead + ".")
        peak = result.get("peak")
        if peak and peak["implied"] is not None:
            out.append(f"That puts {peak['name']} at {_bn(peak['implied'], cur)} at peak "
                       f"against {_bn(peak['model'], cur)}.")
    else:
        out.append(f"No single revenue factor between {SCALE[0]} and {SCALE[1]} times the "
                   f"model meets the ${close:,.2f} price.")
    up = result["direction"] == "up"
    later = result["durability"]
    if later["extra_years"] is not None:
        years = later["extra_years"]
        word = "later" if years > 0 else "earlier"
        out.append(f"At the model's revenue it {'needs' if up else 'holds with'} every loss "
                   f"of exclusivity {abs(years)} year{'s' if abs(years) != 1 else ''} {word}.")
    elif up:
        out.append("Exclusivity alone does not get there: no shift of every loss of "
                   f"exclusivity up to {EXTRA[1]} years meets the price.")
    else:
        out.append("Every loss of exclusivity brought forward, to the year before the "
                   "forecast at the earliest, still leaves the model above the price.")
    steps = [f for f in result["frontier"][1:] if f["factor"] is not None]
    if up and factor is not None and steps:
        out.append("With exclusivity held longer it needs " + ", or ".join(
            f"{f['factor']:.2f} times with {f['extra_years']} more years" for f in steps)
            + ".")
    if rate["implied"] is not None:
        said = (f"The price discounts the model's cash flows at {rate['implied']:.1%} "
                f"against the model's {rate['model']:.1%}")
        out.append(said + (": the return on offer if the model is right."
                           if rate["implied"] > rate["model"] else
                           ", a lower return than the model asks."))
    return out
