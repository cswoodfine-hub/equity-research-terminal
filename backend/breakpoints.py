"""What the price assumes: for each assumption, the value at which the model meets it.

A sum of the parts to the cent is a precise answer to a question nobody asks. What a
reader needs is which assumptions carry the number and how far each can move before the
conclusion flips. The tornado pushes every lever a fifth either way, which says what
moves the answer and nothing about whether the answer survives; a fifth of a growth rate
is noise on one product and a franchise on another.

So each lever is solved instead. For every assumption the company's value rests on, the
break-point is the value at which, moved alone, equity per share equals the last close:
the growth, LOE year, erosion, peak uptake, price, persistence, probability or discount
rate the price implies. Where the model reads below the price it is what would have to
be true to get there; where it reads above, how far the assumption can fall before the
price is no longer supported. Two company-wide levers sit beside the products: one shift
applied to every discount rate, and the launch productivity the future pipeline earns.

Every trial runs the real engine. The product is rebuilt with the lever set, put back into
the book, and the future pipeline recomputed from the book's new R&D, since a product's
spend buys the launches after it. Two things are held: the cost of equity that carries
the year-end value to the price date, and every other assumption.

An rNPV of nil is not asked for. The engine charges development as a share of revenue,
with no fixed cost to clear, so every lever but the discount rate only reaches nil at nil
itself; the question with an answer is the one against the price.

Each break-point carries the evidence grade of the row it rests on (evidence.py), so the
list reads as "this rests on a filing and would have to move a quarter; that rests on a
judgement and would have to move a tenth".
"""

from __future__ import annotations

import math

import assumptions as assumptions_module
import company_lines
import db
import evidence
import forecast
import forecast_view as V

TOP_ASSETS = 6          # products and lines by value, beyond which a lever cannot matter
TOP_LINES = 3
ITERATIONS = 48
# Where a lever is searched. Wide enough that "not reachable" means the price cannot be
# got to by that lever alone, not that the bracket was timid.
BOUNDS = {"wacc": (0.02, 0.30), "revenue_growth_pct": (-0.95, 3.0),
          "terminal_growth_pct": (-0.30, None), "erosion_year1_pct": (0.0, 1.0),
          "pos": (0.0001, 1.0), "discontinuation_pct": (0.01, 1.0)}
SCALE = (0.01, 20.0)    # net price and peak uptake, as a multiple of the model's
YEARS = (-15, 30)       # an LOE year, relative to the model's
CAPM_KEYS = ("wacc", "risk_free", "erp", "beta", "cost_of_debt", "debt_weight")
PRICE_KEYS = ("net_price_per_patient", "list_price_per_patient", "gross_to_net_pct")


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def solve(f, current: float, lo: float, hi: float, integer: bool = False) -> dict:
    """The value between the bounds where ``f`` crosses nil, searched from the current
    value toward whichever bound changes its sign. Assumes the lever moves the value one
    way, which every lever here does. A year is stepped one at a time, since the engine
    reads it as a whole year. A trial the engine refuses counts as not crossing.
    {"value", "reachable", "bound"}."""
    f0 = f(current)
    if math.isnan(f0):
        return {"value": None, "reachable": False, "bound": None}
    if f0 == 0:
        return {"value": current, "reachable": True, "bound": None}

    def crossed(x):
        fx = f(x)
        return (not math.isnan(fx)) and (fx == 0 or _sign(fx) != _sign(f0)), fx

    for bound in (hi, lo):
        if bound is None or bound == current:
            continue
        hit, _ = crossed(bound)
        if not hit:
            continue
        if integer:
            step = 1 if bound > current else -1
            year = int(current)
            while year != int(bound):
                year += step
                if crossed(year)[0]:
                    return {"value": year, "reachable": True, "bound": None}
            return {"value": int(bound), "reachable": True, "bound": None}
        near, far = current, bound          # near has not crossed, far has
        for _ in range(ITERATIONS):
            mid = (near + far) / 2.0
            if crossed(mid)[0]:
                far = mid
            else:
                near = mid
        return {"value": (near + far) / 2.0, "reachable": True, "bound": None}
    candidates = [bd for bd in (lo, hi) if bd is not None]
    scored = [(abs(v), bd) for bd in candidates for v in [f(bd)] if not math.isnan(v)]
    return {"value": None, "reachable": False,
            "bound": min(scored)[1] if scored else None}


def _distance(kind: str, model: float, value: float | None) -> float:
    """How far a break-point sits from the model, in the units the tornado already pushes:
    a fifth of the value for a rate, price or scale (a percentage point at least, so a rate
    near nil is not ranked as infinitely fragile), two years for a date. Used for ranking
    only."""
    if value is None:
        return math.inf
    if kind == "year":
        return abs(value - model) / 2.0
    if kind == "scale":
        return abs(value - model) / (0.2 * abs(model))
    return abs(value - model) / max(0.2 * abs(model), 0.01)


def _row_grades(rows: list, keys, indication: bool = False) -> list:
    return [r.get("evidence") for r in rows
            if r["key"] in keys and (r.get("indication_id") is not None) == indication
            and r.get("scenario", "base") == "base"]


def _lever_evidence(key: str, rows: list, built: dict) -> tuple:
    """(grade, basis) for the row or rows a lever rests on."""
    if key == "wacc":
        grades = _row_grades(rows, CAPM_KEYS)
        return evidence.weakest(grades) if grades else None, "the CAPM rows"
    if key == "loe_year":
        grades = _row_grades(rows, ("loe_year",))
        if grades:
            return evidence.weakest(grades), "the stated LOE row"
        return evidence.grade(built.get("loe_basis")), built.get("loe_basis")
    if key == "erosion_year1_pct":
        grades = _row_grades(rows, ("erosion_year1_pct",))
        if grades:
            return evidence.weakest(grades), "the stated erosion row"
        return evidence.grade(built.get("erosion_basis")), built.get("erosion_basis")
    if key == "pos":
        grades = _row_grades(rows, ("pos", "pos_regulatory", "pos_launch",
                                    "pos_reimbursement", "pos_durability"))
        if grades:
            return evidence.weakest(grades), "the probability rows"
        return evidence.grade(built.get("pos_basis")), built.get("pos_basis")
    if key == "net_price_per_patient":
        grades = _row_grades(rows, PRICE_KEYS)
        return (evidence.weakest(grades) if grades else None), "the price rows"
    if key == "penetration_peak_pct":
        grades = _row_grades(rows, ("penetration_peak_pct",), indication=True)
        return (evidence.weakest(grades) if grades else None), "the peak uptake rows"
    grades = _row_grades(rows, (key,))
    return (evidence.weakest(grades) if grades else None), f"the {key} row"


def _peak_scaled(inputs: dict, factor: float) -> dict:
    indications = []
    for ind in inputs.get("indications") or []:
        scalars = dict(ind.get("scalars") or {})
        if scalars.get("penetration_peak_pct") is not None:
            scalars["penetration_peak_pct"] = scalars["penetration_peak_pct"] * factor
        indications.append({**ind, "scalars": scalars})
    return {**inputs, "indications": indications}


def _peaks(inputs: dict) -> list:
    return [(ind.get("name"), ind["scalars"]["penetration_peak_pct"])
            for ind in inputs.get("indications") or []
            if (ind.get("scalars") or {}).get("penetration_peak_pct") is not None]


def company(db_path, ticker: str, top: int = TOP_ASSETS) -> dict | None:
    """Break-points for one company's value against its last close. None for an unknown
    ticker; {"ok": False, "reason"} where the value or the price is not on file."""
    verdict = V.company_verdict(db_path, ticker)
    if verdict is None:
        return None
    sotp = verdict.get("sotp") or {}
    close, shares = sotp.get("close"), verdict.get("diluted_shares")
    equity, ev = sotp.get("equity_per_share"), sotp.get("enterprise")
    if None in (close, shares, equity, ev, sotp.get("net_cash")) or not ev:
        return {"ok": False, "ticker": verdict["ticker"],
                "reason": "no value against a price: equity, shares or the close is "
                          "not on file"}
    carry = sotp["enterprise_today"] / ev
    net_cash = sotp["net_cash"]
    counted = [l for l in verdict["modelled"] if l.get("counted", True)]
    streams = list(verdict.get("streams") or [])
    parts = counted + streams
    conn = db.get_connection(db_path)
    try:
        anchor = V._valuation_anchor(conn)
        company_id = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                  (verdict["ticker"],)).fetchone()["id"]
        inputs_by_asset = {l["asset_id"]: assumptions_module.load(conn, l["asset_id"])
                           for l in counted}
        rows_by_asset = {l["asset_id"]: assumptions_module.rows(conn, l["asset_id"])
                         for l in counted}
        line_entries = {e["line"]: e for e in company_lines.load(conn, company_id)}
        line_rows = company_lines.rows(conn, company_id)
    finally:
        conn.close()

    base_future = sotp["future"].get("value") or 0.0
    book = ev - base_future

    def price_gap(new_book: float, new_parts: list, rate=None) -> float:
        future = V._future_pipeline(db_path, new_parts, anchor, verdict["ticker"],
                                    rate_override=rate).get("value") or 0.0
        equity_ps = ((new_book + future) * carry + net_cash) * 1e6 / shares
        return equity_ps - close

    def rebuilt(part: dict, result: dict, share: float, scalars: dict) -> dict:
        return {**part, "rnpv_share": result["rnpv"] * share,
                "pnl_share": [{k: (v * share if isinstance(v, (int, float)) else v)
                               for k, v in row.items()} for row in result.get("pnl") or []],
                "dcf_years": result.get("dcf_years") or [], "wacc": result.get("wacc"),
                "long_run_growth": scalars.get("terminal_growth_pct")}

    out = []

    def lever_row(scope, name, asset_id, label, key, kind, model, found, grade, basis,
                  shown=None):
        out.append({
            "scope": scope, "name": name, "asset_id": asset_id, "lever": label,
            "key": key, "kind": kind, "model": model,
            "break": found["value"], "reachable": found["reachable"],
            "bound": found.get("bound"),
            "distance": _distance(kind, model, found["value"]),
            "evidence": grade, "evidence_class": evidence.evidence_class(grade),
            "basis": basis, "shown": shown})

    # Products, largest first.
    for part in sorted(counted, key=lambda l: -abs(l["rnpv_share"]))[:top]:
        inputs = inputs_by_asset[part["asset_id"]]
        try:
            built = forecast.build(inputs)
        except forecast.ForecastError:
            continue
        share = part.get("share") if part.get("share") is not None else 1.0
        index = parts.index(part)

        def gap_for(trial, part=part, share=share, index=index):
            try:
                result = forecast.build(trial)
            except forecast.ForecastError:
                return math.nan
            new = rebuilt(part, result, share, trial.get("scalars") or {})
            new_parts = parts[:index] + [new] + parts[index + 1:]
            return price_gap(book - part["rnpv_share"] + new["rnpv_share"], new_parts)

        for label, key, current, kind, _step in V.lever_specs(inputs, built):
            if kind == "year":
                lo, hi = current + YEARS[0], current + YEARS[1]
                found = solve(lambda x: gap_for(V.apply_lever(inputs, key, int(x))),
                              current, lo, hi, integer=True)
            elif key == "net_price_per_patient":
                found = solve(lambda x: gap_for(V.apply_lever(inputs, key, x)),
                              current, current * SCALE[0], current * SCALE[1])
            else:
                lo, hi = BOUNDS.get(key, (None, None))
                if key == "terminal_growth_pct":
                    hi = (built.get("wacc") or 0.07) - 0.005
                found = solve(lambda x: gap_for(V.apply_lever(inputs, key, x)),
                              current, lo, hi)
            grade, basis = _lever_evidence(key, rows_by_asset[part["asset_id"]], built)
            lever_row("asset", part["name"], part["asset_id"], label, key,
                      "price" if key == "net_price_per_patient" else kind, current,
                      found, grade, basis)
        peaks = _peaks(inputs)
        if peaks:
            found = solve(lambda x: gap_for(_peak_scaled(inputs, x)), 1.0, *SCALE)
            grade, basis = _lever_evidence("penetration_peak_pct",
                                           rows_by_asset[part["asset_id"]], built)
            lever_row("asset", part["name"], part["asset_id"], "peak uptake",
                      "penetration_peak_pct", "scale", 1.0, found, grade, basis,
                      shown=[{"indication": n, "model": p,
                              "break": (p * found["value"]) if found["value"] else None}
                             for n, p in peaks])

    # Lines no asset carries, largest first: growth and the rate they fade to.
    for part in sorted(streams, key=lambda s: -abs(s["rnpv"]))[:TOP_LINES]:
        entry = line_entries.get(part["line"])
        if entry is None:
            continue
        index = parts.index(part)
        rows = [r for r in line_rows if r["line"] == part["line"]]

        def line_gap(scalars, part=part, index=index, entry=entry):
            got = company_lines.build({**entry, "scalars": scalars})
            if not got["ok"]:
                return math.nan
            result = got["result"]
            new = {**part, "rnpv": result["rnpv"],
                   "pnl_share": result.get("pnl") or [],
                   "dcf_years": result.get("dcf_years") or [], "wacc": result.get("wacc")}
            new_parts = parts[:index] + [new] + parts[index + 1:]
            return price_gap(book - part["rnpv"] + new["rnpv"], new_parts)

        scalars = entry["scalars"]
        for label, key in (("near-term growth", "revenue_growth_pct"),
                           ("long-run growth", "terminal_growth_pct")):
            current = scalars.get(key)
            if current is None:
                continue
            lo, hi = BOUNDS[key]
            if key == "terminal_growth_pct":
                hi = (part.get("wacc") or 0.07) - 0.005
            found = solve(lambda x: line_gap({**scalars, key: x}), current, lo, hi)
            grade = evidence.weakest([r.get("evidence") for r in rows if r["key"] == key]
                                     or [None])
            lever_row("line", part["line"], None, label, key, "rate", current, found,
                      grade, f"the {key} row")

    # One shift on every discount rate in the book.
    def shifted(d: float) -> float:
        new_parts, new_book = [], 0.0
        for part in parts:
            if "asset_id" in part and part["asset_id"] in inputs_by_asset:
                inputs = inputs_by_asset[part["asset_id"]]
                trial = V.apply_lever(inputs, "wacc", (part.get("wacc") or 0.07) + d)
                try:
                    result = forecast.build(trial)
                except forecast.ForecastError:
                    return math.nan
                share = part.get("share") if part.get("share") is not None else 1.0
                new = rebuilt(part, result, share, trial["scalars"])
                new_book += new["rnpv_share"]
            else:
                entry = line_entries.get(part.get("line"))
                if entry is None:
                    new_parts.append(part)
                    new_book += part.get("rnpv") or 0.0
                    continue
                got = company_lines.build(
                    {**entry, "scalars": {**entry["scalars"],
                                          "wacc": (part.get("wacc") or 0.07) + d}})
                if not got["ok"]:
                    return math.nan
                new = {**part, "rnpv": got["result"]["rnpv"],
                       "wacc": got["result"].get("wacc")}
                new_book += new["rnpv"]
            new_parts.append(new)
        return price_gap(new_book, new_parts)

    book_wacc = (sotp["future"].get("wacc") or 0.07)
    found = solve(shifted, 0.0, -0.04, 0.10)
    largest = max(counted, key=lambda l: abs(l["rnpv_share"]), default=None)
    grades = (_row_grades(rows_by_asset[largest["asset_id"]], CAPM_KEYS)
              if largest else [])
    grade = evidence.weakest(grades) if grades else None
    if found["value"] is not None:
        found = {**found, "value": book_wacc + found["value"]}
    lever_row("company", verdict["name"], None, "every discount rate", "wacc_shift",
              "rate", book_wacc, found, grade,
              "one shift on every product's and line's discount rate; the book's "
              "revenue-weighted rate is shown")

    # The launch productivity the future pipeline earns.
    rate = sotp["future"].get("rate_used")
    if rate:
        found = solve(lambda x: price_gap(book, parts, rate=x), rate, 0.0, 1.5)
        lever_row("company", verdict["name"], None, "launch productivity",
                  "launch_rate", "rate", rate, found, "measured",
                  "revenue from drugs approved in the last ten years per R&D dollar, the "
                  "filer's own record blended with the pool")

    out.sort(key=lambda r: r["distance"])
    for row in out:
        if math.isinf(row["distance"]):
            row["distance"] = None          # not reachable by this lever alone
    return {
        "ok": True, "ticker": verdict["ticker"], "name": verdict["name"],
        "close": close, "equity_per_share": equity,
        "gap_per_share": close - equity,
        "direction": "up" if equity < close else "down",
        "levers": out,
        "held": ["every other assumption", "the cost of equity carrying the year-end "
                 "value to the price date"],
    }
