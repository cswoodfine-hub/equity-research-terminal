"""What the price assumes: for each assumption, the value at which the model meets it.

A sum of the parts to the cent is a precise answer to a question nobody asks. What a
reader needs is which assumptions carry the number and how far each can move before the
conclusion flips. The tornado pushes every lever a fifth either way, which says what
moves the answer and nothing about whether the answer survives; a fifth of a growth rate
is noise on one product and a franchise on another.

So each lever is solved instead. For every assumption the company's value rests on, the
break-point is the value at which, moved alone, equity per share equals the last close:
the growth, how long it lasts and where it stops, LOE year, erosion, peak uptake, price,
persistence, probability or discount rate the price implies. Where the model reads below
the price it is what would have to be true to get there; where it reads above, how far
the assumption can fall before the price is no longer supported. Company-wide levers sit
beside the products: one shift applied to every discount rate, one to every growth fade,
one scale on every revenue ceiling, and the launch productivity the future pipeline earns.

The fade and the ceiling are there because a price far above the book is usually a bet on
growth lasting longer than five years or running past the peak anyone has published, and
neither shows as a growth rate. A launch product's rate was solved to reach its published
peak, so its ceiling moves with the rate (forecast_view.apply_lever).

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
import risk_groups

TOP_ASSETS = 6          # products and lines by value, beyond which a lever cannot matter
TOP_LINES = 3
ITERATIONS = 48
# Where a lever is searched. Wide enough that "not reachable" means the price cannot be
# got to by that lever alone, not that the bracket was timid.
BOUNDS = {"wacc": (0.02, 0.30), "revenue_growth_pct": (-0.95, 3.0),
          "terminal_growth_pct": (-0.30, None), "erosion_year1_pct": (0.0, 1.0),
          "pos": (0.0001, 1.0), "discontinuation_pct": (0.01, 1.0)}
SCALE = (0.01, 20.0)    # net price, peak uptake and a ceiling, as a multiple of the model's
YEARS = (-15, 30)       # an LOE year, relative to the model's
FADE = (1, 40)          # a growth fade, in years
FADE_SHIFT = (-4, 30)   # one shift on every fade, in years
CAPM_KEYS = ("wacc", "risk_free", "erp", "beta", "cost_of_debt", "debt_weight")
PRICE_KEYS = ("net_price_per_patient", "list_price_per_patient", "gross_to_net_pct")


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


def _part_key(part: dict):
    """A part's identity, so a trial's parts can be matched to the base book's by what
    they are rather than by where they sit. A lever that drops a product hands back a
    shorter list, so position is not an identity."""
    return ("asset", part["asset_id"]) if "asset_id" in part else ("line",
                                                                   part.get("line"))


def _part_value(part: dict) -> float:
    return (part.get("rnpv_share") if "asset_id" in part else part.get("rnpv")) or 0.0


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
    if kind in ("year", "years"):
        return abs(value - model) / 2.0
    if kind in ("scale", "level"):
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
    if key == "growth_fade_years":
        grades = _row_grades(rows, (key,))
        if grades:
            return evidence.weakest(grades), "the growth fade row"
        return "convention", "the engine's five years, where no fade is stated"
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


class Book:
    """One company's valued book, ready to be revalued with any assumption changed.

    Shared by the break-points and the fair value lenses (fair_value.py), so every
    question asked of the book runs the same engine the same way: a product rebuilt with
    its trial inputs and put back, the future pipeline recomputed from the book's new
    R&D, and the year-end value carried to the price date at the cost of equity. ``ok``
    is False, with ``reason``, where the value or the price is not on file."""

    def __init__(self, db_path, ticker: str):
        self.db_path = db_path
        verdict = V.company_verdict(db_path, ticker)
        self.verdict = verdict
        self.ok = False
        self.reason = None
        if verdict is None:
            return
        sotp = verdict.get("sotp") or {}
        self.sotp = sotp
        self.ticker = verdict["ticker"]
        self.name = verdict["name"]
        self.close, self.shares = sotp.get("close"), verdict.get("diluted_shares")
        self.equity, ev = sotp.get("equity_per_share"), sotp.get("enterprise")
        if None in (self.close, self.shares, self.equity, ev, sotp.get("net_cash")) or not ev:
            self.reason = ("no value against a price: equity, shares or the close is not "
                           "on file")
            return
        self.ok = True
        self.carry = sotp["enterprise_today"] / ev
        self.net_cash = sotp["net_cash"]
        # Filed claims outside cash and debt, already in the equity above. A trial that
        # rebuilds equity has to carry them too or every break-point moves by their size.
        self.other_claims = sotp.get("other_claims_total") or 0.0
        self.counted = [l for l in verdict["modelled"] if l.get("counted", True)]
        self.streams = list(verdict.get("streams") or [])
        self.parts = self.counted + self.streams
        conn = db.get_connection(db_path)
        try:
            self.anchor = V._valuation_anchor(conn)
            company_id = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                                      (self.ticker,)).fetchone()["id"]
            self.company_id = company_id
            self.inputs_by_asset = {l["asset_id"]: assumptions_module.load(conn, l["asset_id"])
                                    for l in self.counted}
            self.rows_by_asset = {l["asset_id"]: assumptions_module.rows(conn, l["asset_id"])
                                  for l in self.counted}
            self.line_entries = {e["line"]: e for e in company_lines.load(conn, company_id)}
            self.line_rows = company_lines.rows(conn, company_id)
            # What a dollar of revenue added costs this filer in plant and working
            # capital, and the revenue the book starts from. Both are constants of the
            # company rather than of a trial, so they are read once here and not on
            # each of the several hundred trials a break-point search runs.
            self.growth_share = V.growth_share(conn, self.ticker)
        finally:
            conn.close()
        self.growth_opening = (sotp.get("growth_investment") or {}).get("opening")
        self.base_future = sotp["future"].get("value") or 0.0
        self.book = ev - self.base_future
        # The stub between the valuation year end and the close, and the rate it is
        # carried at. Held here so a trial that moves the book's discount rate can
        # move the carry with it rather than rolling forward at the base rate.
        self.base_ke = sotp.get("cost_of_equity")
        self.years_to_price = sotp.get("years_to_price") or 0.0
        self.base_rate = {_part_key(p): p.get("wacc") for p in self.parts}
        self.base_weight = {_part_key(p): abs(_part_value(p)) for p in self.parts}

    def per_share(self, mm: float) -> float:
        return mm * 1e6 / self.shares

    def price_gap(self, new_book: float, new_parts: list, rate=None) -> float:
        """Equity per share less the close, for a book and parts.

        The growth charge is subtracted here because ``company_verdict`` subtracts it
        from enterprise value and ``new_book`` is rebuilt from part rNPVs alone, which
        never carried it. Left out, every revalued book came back high by the charge:
        Lilly by 57.65 a share, Regeneron by 28.24, Vertex by 23.92, which on Lilly
        turned a point of discount rate either way into a band reading minus 5 and
        plus 138 rather than about minus 63 and plus 80.

        It is recomputed on the trial's own revenue path rather than held at the base
        book's. The charge is capital the book's growth needs, so a trial that halves
        a product must not keep paying for the plant that product no longer sells.
        """
        future = V._future_pipeline(self.db_path, new_parts, self.anchor, self.ticker,
                                    rate_override=rate)
        f_value = future.get("value") or 0.0
        g_value = V.growth_charge(new_parts, self.anchor, future.get("wacc"),
                                  self.growth_share,
                                  opening=self.growth_opening).get("value") or 0.0
        equity_ps = ((new_book + f_value - g_value) * self.carry_for(new_parts)
                     + self.net_cash + self.other_claims) * 1e6 / self.shares
        return equity_ps - self.close

    def rate_shift(self, new_parts: list) -> float:
        """How far the trial moved the book's discount rate, value weighted.

        Weighted on the base book's values, not the trial's, and measured as the
        average of each part's own change rather than the change in the average. Both
        choices exist so that composition cannot move this: a lever that drops a
        product, or one that only moves revenue, returns exactly nil and leaves the
        carry where it was.
        """
        weighted, total = 0.0, 0.0
        for part in new_parts:
            key = _part_key(part)
            weight = self.base_weight.get(key)
            base = self.base_rate.get(key)
            if not weight or base is None or part.get("wacc") is None:
                continue
            weighted += weight * (part["wacc"] - base)
            total += weight
        return (weighted / total) if total else 0.0

    def carry_for(self, new_parts: list) -> float:
        """The roll-forward from the valuation year end to the close, at the trial's
        own cost of equity.

        The carry was frozen at the base rate, so a trial shifting every product's
        discount rate by a point discounted the book harder and still rolled the stub
        forward at the old rate. That is the one stretch of time the shift did not
        reach, and it runs the wrong way: a higher required return compounds the
        year-end value faster, so holding it fixed overstated what a rate rise costs,
        by about 0.17% of equity per 25bp and 3.32 a share on Lilly at a full point.

        A shift in the weighted average cost of capital is taken as the same shift in
        the cost of equity. That is what the lever already assumes about every product
        it moves, and the alternative needs a debt weight and a tax rate this stub
        does not carry.
        """
        if self.base_ke is None or not self.years_to_price:
            return self.carry
        shift = self.rate_shift(new_parts)
        if not shift:
            return self.carry
        return (1.0 + self.base_ke + shift) ** self.years_to_price

    @staticmethod
    def rebuilt(part: dict, result: dict, share: float, scalars: dict) -> dict:
        return {**part, "rnpv_share": result["rnpv"] * share,
                "pnl_share": [{k: (v * share if isinstance(v, (int, float)) else v)
                               for k, v in row.items()} for row in result.get("pnl") or []],
                "dcf_years": result.get("dcf_years") or [], "wacc": result.get("wacc"),
                "long_run_growth": scalars.get("terminal_growth_pct")}

    def gap_with(self, asset_trial, line_trial) -> float:
        """The price gap with every product's inputs and every line's scalars passed
        through a trial; a trial returning None leaves that part as it is."""
        new_parts, new_book = [], 0.0
        for part in self.parts:
            if "asset_id" in part and part["asset_id"] in self.inputs_by_asset:
                trial = asset_trial(part, self.inputs_by_asset[part["asset_id"]])
                if trial is None:
                    new_parts.append(part)
                    new_book += part.get("rnpv_share") or 0.0
                    continue
                try:
                    result = forecast.build(trial)
                except forecast.ForecastError:
                    return math.nan
                share = part.get("share") if part.get("share") is not None else 1.0
                new = self.rebuilt(part, result, share, trial["scalars"])
                new_book += new["rnpv_share"]
            else:
                entry = self.line_entries.get(part.get("line"))
                scalars = line_trial(part, entry["scalars"]) if entry is not None else None
                if scalars is None:
                    new_parts.append(part)
                    new_book += part.get("rnpv") or 0.0
                    continue
                got = company_lines.build({**entry, "scalars": scalars})
                if not got["ok"]:
                    return math.nan
                result = got["result"]
                new = {**part, "rnpv": result["rnpv"], "wacc": result.get("wacc"),
                       "pnl_share": result.get("pnl") or part.get("pnl_share") or [],
                       "dcf_years": result.get("dcf_years") or part.get("dcf_years") or []}
                new_book += new["rnpv"]
            new_parts.append(new)
        return self.price_gap(new_book, new_parts)

    def equity_with(self, asset_trial, line_trial) -> float:
        """Equity per share with the trials applied."""
        return self.gap_with(asset_trial, line_trial) + self.close


def company(db_path, ticker: str, top: int = TOP_ASSETS) -> dict | None:
    """Break-points for one company's value against its last close. None for an unknown
    ticker; {"ok": False, "reason"} where the value or the price is not on file."""
    b = Book(db_path, ticker)
    if b.verdict is None:
        return None
    if not b.ok:
        return {"ok": False, "ticker": b.verdict["ticker"], "reason": b.reason}
    verdict, sotp, close, shares = b.verdict, b.sotp, b.close, b.shares
    equity, net_cash = b.equity, b.net_cash
    counted, streams, parts = b.counted, b.streams, b.parts
    inputs_by_asset, rows_by_asset = b.inputs_by_asset, b.rows_by_asset
    line_entries, line_rows = b.line_entries, b.line_rows
    book = b.book
    price_gap, rebuilt, book_gap = b.price_gap, b.rebuilt, b.gap_with

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
            elif kind == "years":
                found = solve(lambda x: gap_for(V.apply_lever(inputs, key, int(x))),
                              current, *FADE, integer=True)
            elif kind == "level" or key == "net_price_per_patient":
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
                           ("long-run growth", "terminal_growth_pct"),
                           ("growth fade", "growth_fade_years")):
            current = scalars.get(key)
            if key == "growth_fade_years":
                if scalars.get("terminal_growth_pct") is None:
                    continue
                current = int(current or 5)
                found = solve(lambda x: line_gap({**scalars, key: int(x)}), current, *FADE,
                              integer=True)
                kind = "years"
            elif current is None:
                continue
            else:
                lo, hi = BOUNDS[key]
                if key == "terminal_growth_pct":
                    hi = (part.get("wacc") or 0.07) - 0.005
                found = solve(lambda x: line_gap({**scalars, key: x}), current, lo, hi)
                kind = "rate"
            grade = evidence.weakest([r.get("evidence") for r in rows if r["key"] == key]
                                     or [None])
            lever_row("line", part["line"], None, label, key, kind, current, found,
                      grade, f"the {key} row")

    def largest_grade(keys) -> str | None:
        having = [l for l in counted
                  if _row_grades(rows_by_asset[l["asset_id"]], keys)]
        if not having:
            return None
        biggest = max(having, key=lambda l: abs(l["rnpv_share"]))
        return evidence.weakest(_row_grades(rows_by_asset[biggest["asset_id"]], keys))

    # One shift on every discount rate in the book.
    def shifted(d: float) -> float:
        return book_gap(
            lambda part, inputs: V.apply_lever(inputs, "wacc", (part.get("wacc") or 0.07) + d),
            lambda part, scalars: {**scalars, "wacc": (part.get("wacc") or 0.07) + d})

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

    # One shift on every growth fade: how many more years the price needs growth to last.
    def faded(part, scalars_of) -> tuple:
        return (scalars_of.get("terminal_growth_pct") is not None,
                int(scalars_of.get("growth_fade_years") or 5))

    def fade_trial(inputs, d: int, lifted: bool):
        has, fade = faded(None, inputs.get("scalars") or {})
        if not has or not (d or lifted):
            return None
        trial = V.apply_lever(inputs, "growth_fade_years", fade + d)
        if lifted:
            trial = {**trial, "scalars": {k: v for k, v in trial["scalars"].items()
                                          if k != "revenue_ceiling_musd"}}
        return trial

    def fade_shift(d: float, lifted: bool = False) -> float:
        d = int(d)

        def asset_trial(part, inputs):
            return fade_trial(inputs, d, lifted)

        def line_trial(part, scalars):
            has, fade = faded(part, scalars)
            return {**scalars, "growth_fade_years": max(1, fade + d)} if has and d else None
        return book_gap(asset_trial, line_trial)

    weights = []
    for part in parts:
        scalars_of = ((inputs_by_asset[part["asset_id"]].get("scalars") or {})
                      if "asset_id" in part and part["asset_id"] in inputs_by_asset
                      else (line_entries.get(part.get("line")) or {}).get("scalars") or {})
        has, fade = faded(part, scalars_of)
        first = (part.get("pnl_share") or [{}])[0].get("revenue") or 0.0
        if has and first:
            weights.append((first, fade))
    if weights:
        book_fade = sum(r * f for r, f in weights) / sum(r for r, _ in weights)
        found = solve(fade_shift, 0, *FADE_SHIFT, integer=True)
        if found["value"] is not None:
            found = {**found, "value": book_fade + found["value"]}
        grade = largest_grade(("growth_fade_years",)) or "convention"
        lever_row("company", verdict["name"], None, "every growth fade", "fade_shift",
                  "years", book_fade, found, grade,
                  "one shift, in years, on how long every product's and line's near-term "
                  "growth lasts, every ceiling held; the book's revenue-weighted fade is shown")
        # The same shift with no ceiling in the way. Where the ceilings bind, a longer fade
        # alone moves little, and the question a price far above the book asks is how long
        # growth has to run if nothing caps it. What that implies for the largest products'
        # peaks is shown beside it, since that is the part a reader can argue with.
        found = solve(lambda d: fade_shift(d, lifted=True), 0, *FADE_SHIFT, integer=True)
        shown = None
        if found["value"] is not None:
            shown = []
            capped = [l for l in counted
                      if (inputs_by_asset[l["asset_id"]].get("scalars") or {})
                      .get("revenue_ceiling_musd")]
            for l in sorted(capped, key=lambda l: -abs(l["rnpv_share"]))[:3]:
                inputs = inputs_by_asset[l["asset_id"]]
                trial = fade_trial(inputs, int(found["value"]), True)
                try:
                    model_peak = max(forecast.build(inputs).get("revenue") or [0.0])
                    break_peak = (max(forecast.build(trial).get("revenue") or [0.0])
                                  if trial else model_peak)
                except forecast.ForecastError:
                    continue
                shown.append({"product": l["name"], "model": model_peak,
                              "break": break_peak})
            found = {**found, "value": book_fade + found["value"]}
        lever_row("company", verdict["name"], None, "uncapped growth fade",
                  "fade_shift_uncapped", "years", book_fade, found, grade,
                  "one shift, in years, on how long every product's and line's near-term "
                  "growth lasts, with every revenue ceiling lifted; the largest capped "
                  "products' peak revenue at the break is shown", shown=shown)

    # One scale on every revenue ceiling: the peaks the price needs, against the ones in
    # the model. A launch product's growth moves with its ceiling.
    ceilings = {aid: (inputs.get("scalars") or {}).get("revenue_ceiling_musd")
                for aid, inputs in inputs_by_asset.items()}
    if any(c for c in ceilings.values()):
        def ceiling_scale(x: float) -> float:
            return book_gap(
                lambda part, inputs: (V.apply_lever(inputs, "revenue_ceiling_musd",
                                                    ceilings[part["asset_id"]] * x)
                                      if ceilings.get(part["asset_id"]) else None),
                lambda part, scalars: None)
        found = solve(ceiling_scale, 1.0, *SCALE)
        lever_row("company", verdict["name"], None, "every revenue ceiling", "ceiling_scale",
                  "scale", 1.0, found, largest_grade(("revenue_ceiling_musd",)),
                  "one multiple on every product's revenue ceiling, with a growth rate "
                  "solved to reach its ceiling solved again")

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

    def equity_without(removed: list) -> float:
        kept = [p for p in parts if p not in removed]
        lost = sum((p.get("rnpv_share") if "asset_id" in p else p.get("rnpv")) or 0.0
                   for p in removed)
        return price_gap(book - lost, kept) + close

    def per_share(mm: float) -> float:
        return mm * 1e6 / shares

    groups = []
    for g in risk_groups.for_company(verdict["ticker"], parts):
        members = [{"name": m.get("name") or m.get("line"),
                    "per_share": per_share((m.get("rnpv_share") if "asset_id" in m
                                            else m.get("rnpv")) or 0.0),
                    "pipeline": ("asset_id" in m and not m.get("is_marketed"))}
                   for m in g["members"]]
        failing = [m for m in g["members"] if "asset_id" in m and not m.get("is_marketed")]
        groups.append({
            "group": g["group"], "kind": g["kind"], "members": members,
            "exposure_per_share": sum(m["per_share"] for m in members),
            # A mechanism group's pipeline members failed together: the stress the
            # independent probabilities never show. A payer group is exposure only.
            "if_all_fail": (equity_without(failing)
                            if g["kind"] == "mechanism" and failing else None),
            "elsewhere": g["elsewhere"], "sources": g["sources"]})
    # A franchise is one pool shared by its members, so one loss of exclusivity or one
    # price event reaches all of them: exposure, read off the engine's own franchises.
    value_by_name = {l["name"]: per_share(l["rnpv_share"]) for l in counted}
    for f in verdict.get("franchises") or []:
        names = [n if isinstance(n, str) else n.get("name") for n in f.get("members") or []]
        members = [{"name": n, "per_share": value_by_name.get(n), "pipeline": False}
                   for n in names]
        groups.append({"group": " and ".join(names) + " franchise", "kind": "franchise",
                       "members": members,
                       "exposure_per_share": sum(m["per_share"] or 0.0 for m in members),
                       "if_all_fail": None, "elsewhere": [], "sources": []})

    result = {
        "ok": True, "ticker": verdict["ticker"], "name": verdict["name"],
        "close": close, "equity_per_share": equity,
        "gap_per_share": close - equity,
        "direction": "up" if equity < close else "down",
        "levers": out,
        "groups": groups,
        "held": ["every other assumption", "the cost of equity carrying the year-end "
                 "value to the price date"],
    }
    pipeline_by_name = {l["name"]: l for l in counted if not l.get("is_marketed")}
    result["sentence"] = sentence(result, lambda name: (
        equity_without([pipeline_by_name[name]]) if name in pipeline_by_name else None))
    return result


_GRADE_WORDS = {"filed": "the filings", "measured": "measured data",
                "published": "published work", "analogue": "an analogue",
                "convention": "a convention", "judgement": "a judgement", None: "no graded source"}


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _subject(lever: dict) -> str:
    if lever["scope"] == "company":
        return lever["lever"]
    return f"{lever['name']}'s {lever['lever']}"


def _listed(items: list, last: str = "and") -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {last} " + items[-1]


def _value_words(lever: dict, value) -> str:
    kind = lever["kind"]
    if lever["key"] == "launch_rate":
        return f"{value:.3f} of revenue per R&D dollar"
    if kind == "year":
        return f"{int(value)}"
    if kind == "years":
        return (f"{int(value)} years" if float(value).is_integer()
                else f"{value:.1f} years")
    if kind == "level":
        return f"${value:,.0f}mm"
    if kind == "price":
        return f"${value * 1e6:,.0f} a patient"
    if kind == "scale":
        shown = lever.get("shown") or []
        if len(shown) == 1:
            return f"{shown[0]['model'] * value:.2%}"
        return f"{value:.2f} times the modelled peak"
    return f"{value:.2%}"


def sentence(result: dict, fails=None) -> dict:
    """The one paragraph a board needs: what the value rests on, how well each piece is
    evidenced, and what happens if the weakest fails. Written from the break-points, three
    assumptions with the least room, each on a different product or lever, rules only."""
    reachable = [l for l in result.get("levers") or [] if l.get("reachable")]
    chosen, seen = [], set()
    for lever in reachable:
        tag = (lever["name"], lever["lever"]) if lever["scope"] != "company" else lever["lever"]
        owner = lever["name"] if lever["scope"] != "company" else lever["lever"]
        if tag in seen or owner in {c[1] for c in chosen}:
            continue
        seen.add(tag)
        chosen.append((lever, owner))
        if len(chosen) == 3:
            break
    if not chosen:
        return {"body": []}
    name, close = result["name"], result["close"]
    items = []
    for lever, _ in chosen:
        model, value = lever["model"], lever["break"]
        # A multiple of the model is measured from the model, so there is nothing to add.
        had = ("" if lever["kind"] == "scale" and not lever.get("shown") and model == 1.0
               else f" (the model has {_value_words(lever, model)})")
        peaks = [p for p in lever.get("shown") or [] if p.get("product")]
        implied = (f", which takes {peaks[0]['product']} to ${peaks[0]['break']:,.0f}mm at "
                   f"peak against ${peaks[0]['model']:,.0f}mm" if peaks else "")
        if result["direction"] == "down":
            side = "above" if value < model else "below"
            items.append(f"{_subject(lever)} stays {side} {_value_words(lever, value)}{had}"
                         f"{implied}")
        else:
            items.append(f"{_subject(lever)} reaches {_value_words(lever, value)}{had}"
                         f"{implied}")
    joined = _listed(items, "and" if result["direction"] == "down" else "or")
    body = []
    reads = f"{name} reads {_money(result['equity_per_share'])} against a {_money(close)} price"
    if result["direction"] == "down":
        body.append(f"{reads}, and holds it while {joined}.")
    else:
        body.append(f"{reads}. The price is reached only if {joined}, any one of them alone.")
    classes: dict = {}
    for lever, _ in chosen:
        classes.setdefault(lever["evidence_class"], []).append(
            f"{_subject(lever)} ({_GRADE_WORDS.get(lever['evidence'])})")
    parts = []
    if classes.get("evidence"):
        parts.append("we have evidence for " + _listed(classes["evidence"]))
    if classes.get("partial evidence"):
        parts.append("partial evidence for " + _listed(classes["partial evidence"]))
    if classes.get("assumption"):
        parts.append(_listed(classes["assumption"])
                     + (" remains an assumption" if len(classes["assumption"]) == 1
                        else " remain assumptions"))
    if parts:
        text = "; ".join(parts)
        body.append(text[0].upper() + text[1:] + ".")
    weakest = max(chosen, key=lambda c: evidence.GRADES.index(c[0]["evidence"])
                  if c[0]["evidence"] in evidence.GRADES else len(evidence.GRADES))[0]
    failed = fails(weakest["name"]) if (fails and weakest["scope"] == "asset") else None
    if failed is not None:
        body.append(f"If {weakest['name']} fails outright, {name} is worth "
                    f"{_money(failed)} a share.")
    else:
        stressed = [g for g in result.get("groups") or []
                    if g["kind"] == "mechanism" and g.get("if_all_fail") is not None]
        if stressed:
            g = min(stressed, key=lambda g: g["if_all_fail"])
            body.append(f"If the {g['group']} it holds fail together, {name} is worth "
                        f"{_money(g['if_all_fail'])} a share.")
    return {"body": body}
