"""The forecast endpoints' builder: engine plus database, per asset and per company.

``forecast.py`` is pure and ``assumptions.py`` is the layer it computes from; this module
is the glue the API calls. A refusal from the engine is returned as data rather than
raised, because "these three keys are missing" is the empty state the tab shows, not a
server error.
"""

from __future__ import annotations

import copy
import math

import asset_revenue
import assumptions as assumptions_module
import company_lines
import db
import forecast
import loe_link


def _company(conn, ticker: str):
    return conn.execute("SELECT id, ticker, name FROM companies WHERE ticker = ?",
                        (ticker.upper(),)).fetchone()


def _accessible(conn, company_id: int, asset_id: int, ticker: str):
    """The asset row if this company may see its forecast: the owner always, and a
    partner named in the economics rows (CRISPR sees Casgevy through its 40%)."""
    row = conn.execute(
        "SELECT id, owner_company_id, brand_name, generic_name, modality FROM assets"
        " WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        return None
    if row["owner_company_id"] == company_id:
        return row
    partner = conn.execute(
        "SELECT 1 FROM assumptions WHERE asset_id = ? AND key = 'partner_ticker'"
        "   AND UPPER(COALESCE(text_value, '')) = ?", (asset_id, ticker.upper())
    ).fetchone()
    return row if partner else None


def assets_for(db_path, ticker: str):
    """The picker's list: this company's assets with assumptions first, then marketed
    assets a forecast could be started on, then partnered assets."""
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        rows = [dict(r) for r in conn.execute(
            """SELECT a.id AS asset_id, COALESCE(a.brand_name, a.generic_name) AS name,
                      a.modality, a.is_marketed,
                      (SELECT COUNT(*) FROM assumptions s
                        WHERE s.asset_id = a.id) AS assumption_rows
                 FROM assets a
                WHERE a.owner_company_id = ?
                  AND (a.is_marketed = 1 OR EXISTS
                       (SELECT 1 FROM assumptions s WHERE s.asset_id = a.id))
                ORDER BY assumption_rows > 0 DESC, a.is_marketed DESC, name""",
            (company["id"],))]
        partnered = [dict(r) for r in conn.execute(
            """SELECT a.id AS asset_id, COALESCE(a.brand_name, a.generic_name) AS name,
                      a.modality, a.is_marketed, c.ticker AS owner,
                      (SELECT COUNT(*) FROM assumptions s
                        WHERE s.asset_id = a.id) AS assumption_rows
                 FROM assumptions p
                 JOIN assets a ON a.id = p.asset_id
                 JOIN companies c ON c.id = a.owner_company_id
                WHERE p.key = 'partner_ticker'
                  AND UPPER(COALESCE(p.text_value, '')) = ?""", (ticker.upper(),))]
        return {"ticker": company["ticker"], "assets": rows, "partnered": partnered}
    finally:
        conn.close()


def asset_forecast(db_path, ticker: str, asset_id: int, scenario: str = "base"):
    """One asset's forecast, or the named gaps that stop it. None = not this company's."""
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        asset = _accessible(conn, company["id"], asset_id, ticker)
        if asset is None:
            return None
        inputs = assumptions_module.load(conn, asset_id, scenario)
        rows = assumptions_module.rows(conn, asset_id, scenario)
        base = {
            "ticker": company["ticker"], "asset_id": asset_id,
            "name": asset["brand_name"] or asset["generic_name"],
            "modality": asset["modality"], "scenario": scenario,
            "assumptions": rows,
            "unsourced": [r["key"] for r in rows if not (r["source"] or "").strip()],
        }
        if not rows and scenario == "base":
            return {**base, "ok": False, "missing": ["no assumptions on file"],
                    "template": _template()}
        try:
            result = forecast.build(inputs)
        except forecast.ForecastError as err:
            return {**base, "ok": False, "missing": err.missing,
                    "template": _template()}
        # The full years the product actually reported, in the engine's millions, so
        # the path can be drawn from where it came rather than from where it starts.
        actuals = [{"fiscal_year": a["fiscal_year"], "value": a["value"]}
                   for a in inputs.get("actuals") or []
                   if a.get("period") == "FY" and a.get("value") is not None]
        # The scalars the engine actually ran on, base and scenario merged, so a control
        # that moves one starts from the value in force rather than from a scenario's
        # partial restatement of it.
        return {**base, "ok": True, "result": result, "actuals": actuals,
                "scalars": inputs.get("scalars") or {}}
    finally:
        conn.close()


# The two numbers the data cannot settle. Steepness falls out of a launch's early growth
# and incidence out of a cohort study, but a ceiling cannot be read off a curve that has
# not reached one, and the midpoint is coupled to the ceiling. They are the analyst's, and
# this is how the analyst is given something to point at while choosing them.
CURVE_KEYS = ("penetration_peak_pct", "ramp_midpoint_year")


def shape_curve(db_path, ticker: str, asset_id: int, scenario: str = "base",
                peak=None, midpoint=None, plateau=None):
    """Run the engine with a proposed ceiling and midpoint, without saving either.

    An asset blocked on these two shows nothing at all, which makes the hardest judgement
    in the model the one made with the least feedback. This lets the curve be moved and
    watched before it is committed: same engine, same inputs, two values injected into
    every indication that has a pool but no ramp.

    Returns None when the asset is not this company's, and the usual missing-key shape
    when something other than the ramp is absent, so a caller cannot mistake a blocked
    forecast for a shaped one.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None or _accessible(conn, company["id"], asset_id,
                                          ticker) is None:
            return None
        inputs = assumptions_module.load(conn, asset_id, scenario)
        # The indications that have a pool, by id, so a caller that likes what it sees
        # can write the two values back against the right rows.
        pooled = [dict(r) for r in conn.execute(
            """SELECT DISTINCT s.indication_id AS id, i.name
                 FROM assumptions s JOIN indications i ON i.id = s.indication_id
                WHERE s.asset_id = ? AND s.key = 'prevalence'
                  AND s.indication_id IS NOT NULL""", (asset_id,))]
    finally:
        conn.close()

    # A franchise member has one judgement in it and it is not a curve: the share the
    # product settles at. Everything else is read off a filing, so this is the handle
    # that matters, and moving it moves the other member the opposite way.
    scalars = inputs.get("scalars") or {}
    is_franchise = (scalars.get("therapy_mode") or "").strip() == "franchise"
    if is_franchise and plateau is not None:
        now, ramp = scalars.get("share_now"), scalars.get("share_ramp_pct")
        # The first forecast year is not a judgement: it is guided and half reported, and
        # the seeded ramp is the rate that reaches it. So moving the plateau must leave
        # that year where it is and re-solve the ramp around it, or the slider would
        # walk the model off the one number in it that is already known.
        first = (plateau if now is None or ramp is None
                 else scalars["share_plateau"]
                 + (now - scalars["share_plateau"]) * math.exp(-ramp))
        gap_now, gap_first = now - plateau, first - plateau
        if gap_now * gap_first > 0:      # the plateau is still on the far side of year one
            scalars["share_ramp_pct"] = -math.log(gap_first / gap_now)
            scalars["share_plateau"] = plateau
        else:
            # A plateau at or inside the first year cannot be approached from where the
            # product already is. Refused rather than clamped: a slider that silently
            # stops meaning what it says is worse than one that says it cannot go there.
            return {"ok": False, "shaped_indications": 0, "pooled": pooled,
                    "missing": [f"share_plateau of {plateau:.0%} is not reachable: the "
                                f"product already holds {first:.1%} in the first "
                                f"forecast year, which guidance sets"]}

    shaped = 0
    for ind in inputs.get("indications") or []:
        scalars = ind.setdefault("scalars", {})
        if scalars.get("prevalence") is None:
            continue                    # no pool here, so no ramp to give it
        if peak is not None and scalars.get("penetration_peak_pct") is None:
            scalars["penetration_peak_pct"] = peak
        if midpoint is not None and scalars.get("ramp_midpoint_year") is None:
            scalars["ramp_midpoint_year"] = midpoint
        shaped += 1
    try:
        result = forecast.build(inputs)
    except forecast.ForecastError as err:
        return {"ok": False, "missing": err.missing, "shaped_indications": shaped,
                "pooled": pooled}
    return {"ok": True, "shaped_indications": shaped, "pooled": pooled,
            "peak": peak, "midpoint": midpoint,
            "franchise": result.get("franchise"), "is_franchise": is_franchise,
            "plateau": scalars.get("share_plateau") if is_franchise else None,
            "years": result["years"], "patients": result["patients"],
            "revenue": result["revenue_after_loe"],
            "rnpv": result["rnpv"], "npv": result["npv"],
            "wacc": result["wacc"], "pos": result["pos"],
            "loe_year": result.get("loe_year")}


def _template():
    return [{"key": key, "hint": hint, "kind": kind}
            for key, hint, kind in assumptions_module.TEMPLATE["one_time"]]


def save_assumptions(db_path, ticker: str, asset_id: int, rows: list[dict],
                     scenario: str = "base"):
    """Write the editor's rows, snapshot the resulting forecast, return the new state.

    Scoped to the ticker first, the save_product_notes idiom: a row cannot be written
    against another company's asset by id alone.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        if _accessible(conn, company["id"], asset_id, ticker) is None:
            return None
        written = assumptions_module.save(conn, asset_id, rows)
        conn.commit()
    finally:
        conn.close()
    state = asset_forecast(db_path, ticker, asset_id, scenario)
    if state and state.get("ok"):
        conn = db.get_connection(db_path)
        try:
            assumptions_module.snapshot(conn, asset_id, scenario, state["result"])
            conn.commit()
        finally:
            conn.close()
    return {"written": written, "state": state}


def sensitivity(db_path, ticker: str, asset_id: int, scenario: str = "base",
                preset: str = "price"):
    """The two grids the roadmap names, over the asset's live assumptions.

    "price" is the workbook's WACC x net price. "loe" is LOE year x year-one erosion,
    the axis pair that cannot be pinned from owned data, which is why it is a grid.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None or _accessible(conn, company["id"], asset_id,
                                          ticker) is None:
            return None
        inputs = assumptions_module.load(conn, asset_id, scenario)
    finally:
        conn.close()
    try:
        built = forecast.build(inputs)
    except forecast.ForecastError as err:
        return {"ok": False, "missing": err.missing}
    if preset == "loe":
        loe_year = built["loe_year"] or (built["dcf_years"][-1])
        xs = [loe_year - offset for offset in (6, 4, 2, 0)]
        grid = forecast.sensitivity(inputs, "loe_year", xs,
                                    "erosion_year1_pct", [0.25, 0.40, 0.60, 0.80])
        bases = {"x": built["loe_basis"] or "assumed",
                 "y": built["erosion_basis"] or "assumed"}
    else:
        rate = built["wacc"]
        price = forecast.net_price(inputs["scalars"])
        # The centre of each axis is the live value itself, unrounded, so the middle
        # cell is the model's own figure and can be marked as such.
        xs = [rate if step == 0 else round(rate + step, 4)
              for step in (-0.02, -0.01, 0.0, 0.01, 0.02)]
        if price is not None:
            ys = [price if f == 1.0 else round(price * f, 3)
                  for f in (0.78, 0.89, 1.0, 1.11, 1.22)]
            grid = forecast.sensitivity(inputs, "wacc", xs,
                                        "net_price_per_patient", ys)
            bases = {"x": built["wacc_basis"], "y": "net price per patient"}
            labels = {"x": "WACC", "y": "net price, mm"}
        else:
            # A product anchored on reported revenue has no price to cross with the
            # rate. What it has is a growth rate, and the workbook's price axis is
            # standing in for the same question: how much revenue there is to discount.
            growth = inputs["scalars"].get("revenue_growth_pct") or 0.0
            ys = [growth if step == 0 else round(growth + step, 4)
                  for step in (-0.06, -0.03, 0.0, 0.03, 0.06)]
            grid = forecast.sensitivity(inputs, "wacc", xs,
                                        "revenue_growth_pct", ys)
            bases = {"x": built["wacc_basis"],
                     "y": "near-term revenue growth, before erosion"}
            labels = {"x": "WACC", "y": "growth"}
    if preset == "loe":
        labels = {"x": "LOE year", "y": "year-one erosion"}
    return {"ok": True, "preset": preset, "bases": bases, "labels": labels, **grid}


def whatif(db_path, ticker: str, asset_id: int, scenario: str = "base",
           volume=None, price=None, wacc=None, pos=None, growth=None,
           terminal_growth=None, loe_year=None, erosion=None):
    """The slider endpoint: the engine run twice, base beside the variation.

    Each lever is a real driver rather than a scaler of the answer, and which ones
    apply depends on how the product is built. A patient-built forecast has four:
    volume multiplies the patient curve, which is the acceptance lever the CASGEVY
    audit surfaced and the one the workbook's own scenario block varies; price sets the
    net price per patient; WACC and PoS replace the derived values outright, PoS
    stripping the composite factors first because factors beat a stated value in the
    engine.

    A product anchored on reported revenue has no patient curve and no price, so
    volume and price move nothing on it, and 297 of the 323 forecasts on file are
    built that way. Its levers are the ones its mode reads: the near-term growth rate,
    the long-run rate it fades to, the year exclusivity ends and how much goes in the
    year after. Those four are here for exactly that reason.

    Everything is recomputed by the same engine as the base, so a slider cannot say
    anything the model itself would not.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None or _accessible(conn, company["id"], asset_id,
                                          ticker) is None:
            return None
        inputs = assumptions_module.load(conn, asset_id, scenario)
    finally:
        conn.close()

    def slim(result):
        return {"years": result["years"], "revenue": result["revenue_after_loe"],
                "revenue_pre_loe": result["revenue"],
                "patients": result["patients"]["total"],
                "rnpv": result["rnpv"], "npv": result["npv"],
                "owner_rnpv": result["owner_rnpv"],
                "partner_rnpv": result["partner_rnpv"],
                "pv_fcff": result["pv_fcff"], "terminal_pv": result["terminal_pv"],
                "wacc": result["wacc"], "pos": result["pos"],
                "loe_year": result.get("loe_year"), "pnl": result.get("pnl")}

    try:
        base = forecast.build(inputs)
    except forecast.ForecastError as err:
        return {"ok": False, "missing": err.missing}

    varied_inputs = copy.deepcopy(inputs)
    scalars = varied_inputs["scalars"]
    if volume is not None:
        for ind in varied_inputs.get("indications") or []:
            series = (ind.get("series") or {}).get("new_patients")
            if series:
                for year in series:
                    series[year] = series[year] * volume
            if (ind.get("scalars") or {}).get("penetration_peak_pct") is not None:
                ind["scalars"]["penetration_peak_pct"] *= volume
    if price is not None:
        scalars["net_price_per_patient"] = price
    if wacc is not None:
        scalars["wacc"] = wacc
    if pos is not None:
        for key in ("pos_regulatory", "pos_launch", "pos_reimbursement",
                    "pos_durability"):
            scalars.pop(key, None)
        scalars["pos"] = pos
    if growth is not None:
        scalars["revenue_growth_pct"] = growth
    if terminal_growth is not None:
        scalars["terminal_growth_pct"] = terminal_growth
    if loe_year is not None:
        # A scalar loe_year outranks the LOE map in the engine, which is the point: the
        # slider asks what the product is worth if the cliff comes earlier or later.
        scalars["loe_year"] = int(loe_year)
    if erosion is not None:
        scalars["erosion_year1_pct"] = erosion
        if scalars.get("erosion_decay_pct") is None:
            # The default pair travels together. Overriding only the first year would
            # leave the decay at nothing, and a cliff with no slope after it is not
            # what any erosion evidence describes.
            default = forecast.erosion_default(inputs)[0]
            if default:
                scalars["erosion_decay_pct"] = default["decay_pct"]
    try:
        varied = forecast.build(varied_inputs)
    except forecast.ForecastError as err:
        return {"ok": False, "missing": err.missing}
    return {"ok": True, "base": slim(base), "varied": slim(varied),
            "overrides": {"volume": volume, "price": price, "wacc": wacc,
                          "pos": pos, "growth": growth,
                          "terminal_growth": terminal_growth,
                          "loe_year": loe_year, "erosion": erosion}}


def _to_price_units(conn, company_id: int, ordinary: float):
    """A count of ordinary shares, turned into the divisor described above.

    Two steps. The depositary ratio, because a share and a share are not the same thing:
    AstraZeneca's ADS is half an ordinary share and GSK's is two, so dividing an rNPV by
    ordinary shares puts one at twice the price it should be compared with and the other
    at half. Then the exchange rate, folded into the divisor rather than applied to the
    rNPV, so that every caller dividing by this gets dollars without knowing it needs to.
    A dollar filer has neither a ratio nor a rate and comes back unchanged.
    """
    company = conn.execute(
        "SELECT ticker, reporting_currency FROM companies WHERE id = ?",
        (company_id,)).fetchone()
    ratio = conn.execute(
        "SELECT ordinary_per_adr FROM adr_ratios WHERE ticker = ?",
        (company["ticker"],)).fetchone() if company else None
    per_adr = ratio["ordinary_per_adr"] if ratio and ratio["ordinary_per_adr"] else 1.0
    shares = ordinary / per_adr
    currency = (company["reporting_currency"] or "USD") if company else "USD"
    if currency == "USD":
        return shares
    rate = conn.execute(
        """SELECT rate FROM fx_rates WHERE base = ? AND quote = 'USD'
            ORDER BY as_of DESC LIMIT 1""", (currency,)).fetchone()
    if not (rate and rate["rate"]):
        return None            # an rNPV in kroner divided by shares is not a dollar figure
    return shares / rate["rate"]


def _diluted_shares(conn, company_id: int):
    """The divisor that turns an rNPV into a figure per share the price can be read against.

    Not simply a share count, and the difference matters for a filer that does not report
    in dollars. An rNPV is in the currency of the accounts it was built from, Sanofi's in
    euro and Novo's in kroner, while the price on file is what the American depositary
    share trades at in dollars. Two conversions stand between them, and both are folded
    in here so every caller gets a figure that can be compared with the price rather than
    one that is out by an exchange rate, a depositary ratio, or both.

    A foreign private issuer tags neither a diluted share count nor a shares outstanding:
    AstraZeneca and Novartis file neither, so their rNPV had nowhere to go and the company
    call showed nothing at all for two of the largest names in the universe. Every filer
    states earnings per share though, and net income over it is the share count that
    produced it.

    Then the unit. The price on file is what the ADR trades at, and the count derived from
    a foreign filer's accounts is of ordinary shares, which are not the same thing:
    AstraZeneca's ADS is half an ordinary share, so dividing by ordinary shares would put
    its per-share figure at twice the number the price can be compared with. The curated
    ADR ratio converts one to the other.
    """
    ordinary = None
    for metric in ("WeightedAverageDilutedShares", "SharesOutstanding"):
        row = conn.execute(
            """SELECT value FROM financials WHERE company_id = ? AND metric = ?
                AND period_type IN ('FY', 'instant') ORDER BY fiscal_year DESC,
                period_end DESC LIMIT 1""", (company_id, metric)).fetchone()
        if row and row["value"]:
            ordinary = row["value"]
            break
    if ordinary:
        return _to_price_units(conn, company_id, ordinary)
    income = conn.execute(
        """SELECT value, fiscal_year FROM financials WHERE company_id = ?
            AND metric = 'NetIncomeLoss' AND period_type = 'FY'
            ORDER BY fiscal_year DESC LIMIT 1""", (company_id,)).fetchone()
    if not (income and income["value"]):
        return None
    eps = conn.execute(
        """SELECT value FROM financials WHERE company_id = ? AND metric =
            'EarningsPerShareDiluted' AND period_type = 'FY' AND fiscal_year = ?""",
        (company_id, income["fiscal_year"])).fetchone()
    if not (eps and eps["value"]):
        return None
    ordinary = income["value"] / eps["value"]
    return _to_price_units(conn, company_id, ordinary) if ordinary > 0 else None


def catalyst_stakes(db_path, ticker: str):
    """The catalyst calendar ranked by dollars at stake rather than by date.

    A catalyst is priced only where its asset carries ``pos_success`` and
    ``pos_failure`` assumption rows: the stake is the rNPV under one minus the rNPV
    under the other, taken at this company's share of the economics, and per share
    where diluted shares are on file. Nothing is derived for the unpriced rest; they
    rank below the priced, by date, each naming the two keys that would price it. The
    engine behind both legs is the same whatif the sliders use, so a stake cannot say
    anything the model itself would not.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        rows = [dict(r) for r in conn.execute(
            """SELECT cat.id, cat.catalyst_type, cat.expected_date,
                      cat.date_confidence, cat.title, cat.description, cat.source_url,
                      cat.is_curated, cat.asset_id,
                      COALESCE(a.brand_name, a.generic_name) AS asset_name,
                      a.owner_company_id
                 FROM catalysts cat JOIN assets a ON a.id = cat.asset_id
                WHERE cat.status = 'pending' AND cat.expected_date >= date('now')
                  AND (a.owner_company_id = ? OR cat.asset_id IN
                       (SELECT asset_id FROM assumptions WHERE key = 'partner_ticker'
                          AND UPPER(COALESCE(text_value, '')) = ?))
                ORDER BY cat.expected_date""",
            (company["id"], ticker.upper()))]
        shares = _diluted_shares(conn, company["id"])
        pairs = {}
        for row in rows:
            asset_id = row["asset_id"]
            if asset_id not in pairs:
                scalars = assumptions_module.load(conn, asset_id)["scalars"]
                pairs[asset_id] = (scalars.get("pos_success"),
                                  scalars.get("pos_failure"),
                                  scalars.get("economics_share"),
                                  scalars.get("pos"))
    finally:
        conn.close()

    priced, unpriced = [], []
    for row in rows:
        success, failure, share, _stated = pairs[row["asset_id"]]
        owned = row.pop("owner_company_id") == company["id"]
        if owned:
            portion = share if share is not None else 1.0
        else:
            portion = 1.0 - (share if share is not None else 1.0)
        if success is None or failure is None:
            missing = [k for k, v in (("pos_success", success),
                                      ("pos_failure", failure)) if v is None]
            unpriced.append({**row, "priced": False, "missing": missing})
            continue
        up = whatif(db_path, ticker, row["asset_id"], pos=success)
        down = whatif(db_path, ticker, row["asset_id"], pos=failure)
        if not (up and up.get("ok") and down and down.get("ok")):
            unpriced.append({**row, "priced": False,
                             "missing": (up or {}).get("missing")
                             or (down or {}).get("missing") or ["a forecast"]})
            continue
        swing = up["varied"]["rnpv"] - down["varied"]["rnpv"]
        share_swing = swing * portion
        priced.append({
            **row, "priced": True,
            "pos_now": up["base"]["pos"], "pos_success": success,
            "pos_failure": failure,
            "rnpv_success": up["varied"]["rnpv"],
            "rnpv_failure": down["varied"]["rnpv"],
            "swing": swing, "share": portion, "share_swing": share_swing,
            "per_share": (share_swing * 1e6 / shares) if shares else None,
        })
    priced.sort(key=lambda r: (-abs(r["share_swing"]), r["expected_date"]))
    return {"ticker": company["ticker"], "priced": priced, "unpriced": unpriced,
            "diluted_shares": shares}


OUTCOMES = {"met": "pos_success", "missed": "pos_failure"}


def resolve_catalyst(db_path, ticker: str, catalyst_id: int, outcome: str):
    """One click after the readout: the PoS steps to the leg that happened.

    The order is the roadmap's discipline. The pre-event forecast is snapshotted
    first, then the stated pos is written through save_assumptions, which snapshots
    the post-event state itself, and only then does the catalyst leave the calendar
    with the outcome and the applied pos noted on its row. History is never
    overwritten: both sides of the event stay on file.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be met or missed, got '{outcome}'")
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        catalyst = conn.execute(
            "SELECT id, asset_id, status FROM catalysts WHERE id = ?",
            (catalyst_id,)).fetchone()
        if catalyst is None or catalyst["asset_id"] is None:
            return None
        if _accessible(conn, company["id"], catalyst["asset_id"], ticker) is None:
            return None
        if catalyst["status"] != "pending":
            raise ValueError(f"catalyst {catalyst_id} is already {catalyst['status']}")
        asset_id = catalyst["asset_id"]
        scalars = assumptions_module.load(conn, asset_id)["scalars"]
        applied = scalars.get(OUTCOMES[outcome])
        if applied is None:
            raise ValueError(f"{OUTCOMES[outcome]} is not on file for this asset, "
                             "so the outcome has no priced leg to step to")
    finally:
        conn.close()

    # The pre-event record first, then the write (which snapshots post-event itself).
    before = asset_forecast(db_path, ticker, asset_id)
    if before and before.get("ok"):
        conn = db.get_connection(db_path)
        try:
            assumptions_module.snapshot(conn, asset_id, "base", before["result"])
            conn.commit()
        finally:
            conn.close()
    saved = save_assumptions(db_path, ticker, asset_id, [{
        "key": "pos", "value": applied,
        "source": f"catalyst {catalyst_id} resolved {outcome}",
        "note": f"stepped to {OUTCOMES[outcome]} on resolution",
    }])
    import catalysts as catalysts_module
    catalysts_module.set_status(db_path, catalyst_id, outcome)
    conn = db.get_connection(db_path)
    try:
        conn.execute(
            "UPDATE catalysts SET description = COALESCE(description, '') ||"
            " ' | resolved ' || ? || ', pos -> ' || ? WHERE id = ?",
            (outcome, f"{applied:g}", catalyst_id))
        conn.commit()
    finally:
        conn.close()
    return {"catalyst_id": catalyst_id, "outcome": outcome, "pos_applied": applied,
            "state": saved["state"] if saved else None}


def _is_marketed(db_path, asset_id: int) -> bool:
    conn = db.get_connection(db_path)
    try:
        row = conn.execute("SELECT is_marketed FROM assets WHERE id = ?",
                           (asset_id,)).fetchone()
        return bool(row and row["is_marketed"])
    finally:
        conn.close()


def company_rollup(db_path, ticker: str):
    """Every forecast this company has economics in, summed against reported revenue.

    The owner takes economics_share (or all of it); a partner named in the rows takes
    the remainder. Reported company revenue sits beside the sum for scale, and diluted
    shares turn the rNPV into a per-share figure.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        owned = [r["id"] for r in conn.execute(
            """SELECT DISTINCT a.id FROM assets a JOIN assumptions s
                 ON s.asset_id = a.id WHERE a.owner_company_id = ?""",
            (company["id"],))]
        partnered = [r["asset_id"] for r in conn.execute(
            """SELECT DISTINCT asset_id FROM assumptions
                WHERE key = 'partner_ticker'
                  AND UPPER(COALESCE(text_value, '')) = ?""", (ticker.upper(),))]
        revenue_actuals = [dict(r) for r in conn.execute(
            """SELECT fiscal_year, value / 1e6 AS value FROM financials
                WHERE company_id = ? AND metric = 'Revenues' AND period_type = 'FY'
                ORDER BY fiscal_year""", (company["id"],))]
        # The same helper the company call uses, so a filer that tags no share count is
        # not silently left without a per-share figure here while the call finds one.
        shares = _diluted_shares(conn, company["id"])
        stream_inputs = company_lines.load(conn, company["id"])
        # One reported line modelled under two assets is counted twice below. Named
        # rather than dropped, since which of the two is the copy is the analyst's call.
        shared = asset_revenue.shared_lines(conn, company["id"])
    finally:
        conn.close()

    lines, refused, placeholders = [], [], []
    combined: dict[int, float] = {}
    rnpv_total = 0.0
    for asset_id in dict.fromkeys(owned + partnered):
        state = asset_forecast(db_path, ticker, asset_id)
        if not state or not state.get("ok"):
            if state:
                refused.append({"asset_id": asset_id, "name": state.get("name"),
                                "missing": state.get("missing")})
            continue
        result = state["result"]
        share = result.get("economics_share")
        if asset_id in owned:
            share = share if share is not None else 1.0
        else:
            share = 1.0 - (share if share is not None else 1.0)
        # An asset drawn on a placeholder curve is shown and not counted. Its revenue
        # goes into the build, hatched, so the analyst can see the shape they are being
        # asked to replace; its rNPV stays out of the per-share number, because a figure
        # built on a value chosen to be visibly wrong is not a view of anything.
        counted = not (result.get("curve_basis") or "").startswith("placeholder")
        for year, value in zip(result["years"], result["revenue_after_loe"]):
            combined[year] = combined.get(year, 0.0) + value * share
        if counted:
            rnpv_total += result["rnpv"] * share
        else:
            placeholders.append({"asset_id": asset_id, "name": state["name"],
                                 "rnpv_share": result["rnpv"] * share})
        revenue = result["revenue_after_loe"]
        peak = max(revenue) if revenue else None
        lines.append({"asset_id": asset_id, "name": state["name"], "share": share,
                      "rnpv_share": result["rnpv"] * share,
                      "npv_share": result["npv"] * share, "counted": counted,
                      "mode": result.get("mode"), "pos": result.get("pos"),
                      "is_marketed": _is_marketed(db_path, asset_id),
                      "loe_year": result.get("loe_year"),
                      "loe_in_base": result.get("loe_in_base"),
                      # Each region's own date and share, without its revenue series.
                      "regions": [{key: region.get(key) for key in
                                   ("region", "label", "share", "loe_year", "in_base")}
                                  for region in result.get("regions") or []],
                      "long_run_growth": (state.get("scalars") or {}).get(
                          "terminal_growth_pct"),
                      # A device a drug company sells (Abiomed at Johnson & Johnson) is
                      # flagged the way a device line is, so its R&D buys no drug launches.
                      "buys_launches": (state.get("scalars") or {}).get(
                          "buys_launches", 1) != 0,
                      "peak_revenue": peak,
                      "peak_year": (result["years"][revenue.index(peak)]
                                    if peak is not None else None),
                      "years": result["years"],
                      # The P&L at this company's share, for the lines the book's own
                      # R&D and cost ratios are read off.
                      "dcf_years": result.get("dcf_years") or [],
                      "pnl_share": [{k: (v * share if isinstance(v, (int, float)) else v)
                                     for k, v in row.items()}
                                    for row in result.get("pnl") or []],
                      "wacc": result.get("wacc"),
                      "revenue_share": [v * share for v in revenue]})
    # Streams: lines the company reports that no asset carries, run through the same
    # engine as a marketed product. They count in full; a stream is the company's own.
    streams, stream_refused = [], []
    for entry in stream_inputs:
        built = company_lines.build(entry)
        if not built["ok"]:
            stream_refused.append({"line": built["line"], "missing": built["missing"]})
            continue
        result = built["result"]
        for year, value in zip(result["years"], result["revenue_after_loe"]):
            combined[year] = combined.get(year, 0.0) + value
        rnpv_total += result["rnpv"]
        streams.append({"line": built["line"], "rnpv": result["rnpv"],
                        "base_revenue": entry["scalars"].get("base_revenue"),
                        "buys_launches": entry["scalars"].get("buys_launches", 1) != 0,
                        "years": result["years"], "revenue": result["revenue_after_loe"],
                        "dcf_years": result.get("dcf_years") or [],
                      "pnl_share": [{k: (v * 1.0 if isinstance(v, (int, float)) else v)
                                     for k, v in row.items()}
                                    for row in result.get("pnl") or []],
                      "wacc": result.get("wacc"),
                        "unsourced": built.get("unsourced") or [],
                        "notes": result.get("notes") or []})
    per_share = (rnpv_total * 1e6 / shares) if shares else None
    return {"ticker": company["ticker"], "lines": lines, "refused": refused,
            "placeholders": placeholders, "streams": streams,
            "stream_refused": stream_refused,
            "combined": sorted(combined.items()),
            "rnpv_total": rnpv_total, "rnpv_per_share": per_share,
            "reported_revenue": revenue_actuals, "shared_lines": shared}


# --- the call ---------------------------------------------------------------
# What the tab is for. Everything above computes a number in millions; this is where the
# number meets a share price, which is the only form in which a forecast is a view.

# How far each lever is pushed to rank what the answer actually rests on. A fifth is
# large enough to separate the drivers and small enough that the engine stays in the
# region the assumptions describe.
_LEVER_STEP = 0.20


def _last_close(conn, company_id: int):
    row = conn.execute(
        """SELECT close, as_of FROM prices WHERE company_id = ? AND interval = '1d'
            AND close IS NOT NULL ORDER BY as_of DESC LIMIT 1""",
        (company_id,)).fetchone()
    return (row["close"], row["as_of"]) if row else (None, None)


def _next_catalyst(conn, asset_id: int):
    row = conn.execute(
        """SELECT catalyst_type, expected_date, title FROM catalysts
            WHERE asset_id = ? AND status = 'pending' AND expected_date >= date('now')
            ORDER BY expected_date LIMIT 1""", (asset_id,)).fetchone()
    return dict(row) if row else None


def _levers(inputs, built):
    """What the answer rests on, ranked by how far each moves it.

    A tornado rather than a grid. The grid crosses two axes; this asks the narrower and
    more useful question an analyst is actually asked, which is what would have to be
    wrong for the number to be wrong.

    Which levers exist depends on how the product is built. A patient-built forecast
    rests on its net price, its persistence, its PoS and the discount rate. A product
    anchored on reported revenue has none of the first two and an approved product's
    PoS is one, so on 297 of the 323 forecasts on file the old list came back with the
    discount rate and a PoS that could only fall. What such a product rests on is its
    growth rate, the long-run rate it fades to, the year exclusivity ends and the drop
    in the year after, so those are its levers.

    Each lever is pushed by overriding the computed value, not the raw input, because
    WACC arrives from CAPM components and PoS from composite factors, and perturbing a
    scalar that is not there moves nothing. PoS strips its factors first, since factors
    beat a stated value in the engine. A fifth either way for a rate or a price; two
    years either way for a date, because a fifth of a year number is nonsense. Each row
    says which, so the sentence written from it can too.
    """
    base_rnpv = built["rnpv"]
    out = []
    for label, key, current, kind, step in lever_specs(inputs, built):
        swings = []
        if kind == "year":
            trials = (current - 2, current + 2)
        elif kind == "years":
            trials = (max(1, current - 2), current + 2)
        else:
            trials = (current * (1 - _LEVER_STEP), current * (1 + _LEVER_STEP))
        for pushed in trials:
            try:
                moved = forecast.build(apply_lever(inputs, key, pushed))["rnpv"]
            except forecast.ForecastError:
                continue
            swings.append(moved - base_rnpv)
        if len(swings) == 2:
            out.append({"lever": label, "key": key, "value": current, "step": step,
                        "down": min(swings), "up": max(swings),
                        "span": max(swings) - min(swings)})
    out.sort(key=lambda r: -abs(r["span"]))
    return out


def lever_specs(inputs, built) -> list:
    """(label, key, current, kind, step) for every lever this product's value rests on.

    Shared by the tornado and the break-points, so the two always ask about the same
    assumptions. A lever with no current value, or a rate at nil, is left out: there is
    nothing to push.
    """
    scalars = inputs.get("scalars") or {}
    mode = built.get("mode")
    fifth = "a fifth either way"
    levers = [("discount rate", "wacc", built["wacc"], "rate", fifth)]
    if mode in ("marketed", "franchise"):
        # A loss already in the base does not erode again, so neither lever can move it.
        loe_year = None if built.get("loe_in_base") else built.get("loe_year")
        default = forecast.erosion_default(inputs)[0]
        year1 = scalars.get("erosion_year1_pct")
        if year1 is None and default:
            year1 = default["year1_pct"]
        # How long near-term growth lasts, and the level it stops at: the two a price
        # that reads above the book is usually a bet on. A fade only exists where the
        # product fades to a long-run rate; the engine reads a missing one as five years.
        fades = scalars.get("terminal_growth_pct") is not None
        levers += [
            ("near-term growth", "revenue_growth_pct",
             scalars.get("revenue_growth_pct"), "rate", fifth),
            ("long-run growth", "terminal_growth_pct",
             scalars.get("terminal_growth_pct"), "rate", fifth),
            ("growth fade", "growth_fade_years",
             int(scalars.get("growth_fade_years") or 5) if fades else None, "years",
             "two years either way"),
            ("LOE year", "loe_year", loe_year, "year", "two years either way"),
            ("year-one erosion", "erosion_year1_pct", year1 if loe_year else None,
             "rate", fifth),
        ]
        if mode == "marketed":
            levers.append(("revenue ceiling", "revenue_ceiling_musd",
                           scalars.get("revenue_ceiling_musd"), "level", fifth))
        if built["pos"] is not None and built["pos"] < 1.0:
            levers.append(("probability of success", "pos", built["pos"], "rate", fifth))
    else:
        levers += [
            ("net price", "net_price_per_patient", forecast.net_price(scalars), "rate",
             fifth),
            ("probability of success", "pos", built["pos"], "rate", fifth),
            ("persistence", "discontinuation_pct", scalars.get("discontinuation_pct"),
             "rate", fifth),
        ]
    return [lever for lever in levers
            if lever[2] is not None and not (lever[3] == "rate" and lever[2] == 0)]


def apply_lever(inputs, key: str, value):
    """The inputs with one lever set, overriding the computed value rather than the raw
    input: WACC arrives from CAPM components and PoS from composite factors, and
    perturbing a scalar that is not there moves nothing. PoS strips its factors first,
    since factors beat a stated value in the engine; erosion takes the default decay with
    its year-one drop where the product states neither."""
    scalars = dict(inputs.get("scalars") or {})
    scalars[key] = value
    if key == "pos":
        scalars[key] = min(scalars[key], 1.0)
        for factor in ("pos_regulatory", "pos_launch", "pos_reimbursement",
                       "pos_durability"):
            scalars.pop(factor, None)
    if key == "erosion_year1_pct":
        scalars[key] = min(scalars[key], 1.0)
        default = forecast.erosion_default(inputs)[0]
        if scalars.get("erosion_decay_pct") is None and default:
            scalars["erosion_decay_pct"] = default["decay_pct"]
    if key == "growth_fade_years":
        scalars[key] = max(1, int(round(scalars[key])))
    if key == "revenue_ceiling_musd":
        solved = _resolved_growth(inputs.get("scalars") or {}, value)
        if solved is not None:
            scalars["revenue_growth_pct"] = solved
    return {**inputs, "scalars": scalars}


def _resolved_growth(scalars: dict, ceiling: float):
    """The growth rate that reaches ``ceiling`` by the end of the fade, where the product's
    own rate was solved to reach its stated ceiling that way; None where it was not.

    A launch product's growth is not observed. It is the rate that carries its run rate
    to a published peak by a year, fading to nought as it arrives (Kisunla, Foundayo). A
    higher ceiling alone moves nothing there, since the path stops growing exactly at the
    old one, so asking what peak the price needs has to move the rate with it. A product
    whose growth is read off its filings (Mounjaro) keeps its rate, and the ceiling binds
    or does not."""
    base, growth = scalars.get("base_revenue"), scalars.get("revenue_growth_pct")
    old, fade_to = scalars.get("revenue_ceiling_musd"), scalars.get("terminal_growth_pct")
    fade = int(scalars.get("growth_fade_years") or 5)
    if None in (base, growth, old, fade_to) or not base or old <= base or ceiling <= 0:
        return None
    reach = forecast.grown_revenue(base, growth, fade, fade_to=fade_to, fade_years=fade)[-1]
    if abs(reach / old - 1.0) > 0.005:
        return None
    lo, hi = -0.99, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        got = forecast.grown_revenue(base, mid, fade, fade_to=fade_to, fade_years=fade)[-1]
        lo, hi = (mid, hi) if got < ceiling else (lo, mid)
    return (lo + hi) / 2.0


def verdict(db_path, ticker: str, asset_id: int, scenario: str = "base"):
    """One asset's forecast expressed as a view: per share, against the market, ranked.

    The rNPV is the model's answer and nobody trades a number in millions. This turns it
    into the three things a note has to carry: what the asset is worth per share, how that
    sits against what the share costs today, and which assumption the answer depends on
    most. The scenario spread comes from the same engine run three times, so the range is
    the model's own and not a decoration on it.

    A single asset is not a company, and the share of the price it explains is reported as
    exactly that rather than as a target.
    """
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        if company is None:
            return None
        asset = _accessible(conn, company["id"], asset_id, ticker)
        if asset is None:
            return None
        shares = _diluted_shares(conn, company["id"])
        close, close_date = _last_close(conn, company["id"])
        catalyst = _next_catalyst(conn, asset_id)
        name = asset["brand_name"] or asset["generic_name"]
        inputs = assumptions_module.load(conn, asset_id, scenario)
        rows = assumptions_module.rows(conn, asset_id, scenario)
        # A scenario inherits base and restates only what it changes, so one with no
        # rows of its own is base wearing another name. Counting them is how the range
        # can decline to draw itself rather than showing a spread of nothing.
        by_scenario, defined = {}, {}
        for other in ("bear", "base", "bull"):
            defined[other] = len(assumptions_module.rows(conn, asset_id, other)) > 0
            try:
                by_scenario[other] = forecast.build(
                    assumptions_module.load(conn, asset_id, other))["rnpv"]
            except forecast.ForecastError:
                continue
    finally:
        conn.close()

    try:
        built = forecast.build(inputs)
    except forecast.ForecastError as err:
        return {"ok": False, "missing": err.missing, "name": name}

    share = built.get("economics_share")
    owner = built["owner_rnpv"] if share is not None else built["rnpv"]
    per_share = (owner * 1e6 / shares) if shares else None
    revenue = built["revenue_after_loe"]
    peak = max(revenue) if revenue else None
    peak_year = built["years"][revenue.index(peak)] if peak is not None else None

    spread = {}
    for label, rnpv in by_scenario.items():
        owned = rnpv * (share if share is not None else 1.0)
        spread[label] = {"rnpv": rnpv, "defined": defined.get(label, False),
                         "per_share": (owned * 1e6 / shares) if shares else None}
    # Only a real spread counts. Bear and bull that merely inherit base produce the same
    # number three times, and a range drawn across it would claim work nobody did.
    has_range = bool(defined.get("bear") or defined.get("bull"))

    return {
        "ok": True, "ticker": company["ticker"], "asset_id": asset_id, "name": name,
        "scenario": scenario, "mode": built.get("mode"),
        "horizon_end": (built.get("dcf_years") or [None])[-1],
        "price_basis": (inputs.get("scalars") or {}).get("price_basis"),
        # A product valued off revenue never uses its price, so dividing one by the
        # other turns the price into a check: the patient count it implies is a number
        # an analyst can hold against a registry.
        "implied_patients": (
            (built["revenue"][0] / forecast.net_price(inputs["scalars"]))
            if built.get("mode") in ("marketed", "franchise") and built.get("revenue")
            and forecast.net_price(inputs["scalars"]) else None),
        "rnpv": built["rnpv"], "npv": built["npv"], "owner_rnpv": owner,
        "economics_share": share,
        "diluted_shares": shares, "per_share": per_share,
        "close": close, "close_date": close_date,
        "pct_of_price": (per_share / close) if (per_share and close) else None,
        "peak_revenue": peak, "peak_year": peak_year,
        "terminal_share": (built["terminal_pv"] / built["npv"]
                           if built.get("npv") else None),
        "wacc": built["wacc"], "wacc_basis": built.get("wacc_basis"),
        "pos": built["pos"], "pos_basis": built.get("pos_basis"),
        "loe_year": built.get("loe_year"), "loe_basis": built.get("loe_basis"),
        "loe_in_base": built.get("loe_in_base"),
        "spread": spread, "has_range": has_range,
        "levers": _levers(inputs, built),
        "next_catalyst": catalyst,
        "unsourced": [r["key"] for r in rows if not (r["source"] or "").strip()],
        "notes": built.get("notes") or [],
    }


def _read_twice(conn, company_id: int, rows: list) -> set:
    """Assets whose full-year figure is another asset's, read from a second filing.

    Pfizer's Inflectra arrives twice: the 10-K product axis files it as "Inflectra /
    Remsima" and the results exhibit as "Inflectra", the name the FDA holds the BLA under.
    Both rows said $646mm for FY2025, so the tagged total counted it twice and the untagged
    remainder read $646mm short. ``data/loe_link.csv`` already says the application is the
    revenue line's, so another asset of the company holding that application and reporting
    the same figure is the same revenue. A different figure is left alone: that is two
    products sharing an application, not one product read twice.
    """
    by_asset = {r["id"]: r["value"] for r in rows}
    out = set()
    for line_id, link in loe_link.load(conn).items():
        if line_id not in by_asset:
            continue
        for holder in loe_link.holders(conn, link["code"], exclude=(line_id,)):
            if (holder in by_asset and holder not in out
                    and abs(by_asset[holder] - by_asset[line_id]) < 0.5e6):
                out.add(holder)
    return out


def _revenue_coverage(conn, company_id: int, modelled_ids: list, streams=None):
    """What share of last year's reported revenue the model accounts for.

    The number that keeps a company call honest, and it was measured against the wrong
    denominator: the product rows on file rather than what the company reported. Those
    rows are only what the data sets tag. For Vertex that is 94.4% of revenue, for
    Johnson & Johnson 64.4%, so a fully modelled J&J would have read 100% with a third
    of the company invisible. The denominator is now ``financials.Revenues`` for the
    same year, and the gap between it and the rows is named rather than dropped.

    Three kinds of revenue count as covered: assets that compute, and streams, which are
    lines the company reports that no asset carries (company_lines). What remains is
    ``untagged``: revenue with neither a product row nor a stream, which is the work
    queue nobody had a name for.
    """
    year = conn.execute(
        """SELECT MAX(ar.fiscal_year) FROM asset_revenue ar JOIN assets a
             ON a.id = ar.asset_id
            WHERE a.owner_company_id = ? AND ar.period = 'FY'""",
        (company_id,)).fetchone()[0]
    if not year:
        return None
    rows = [dict(r) for r in conn.execute(
        """SELECT a.id, a.brand_name, ar.value FROM asset_revenue ar
             JOIN assets a ON a.id = ar.asset_id
            WHERE a.owner_company_id = ? AND ar.period = 'FY'
              AND ar.fiscal_year = ? AND ar.value IS NOT NULL
            ORDER BY ar.value DESC""", (company_id, year))]
    twice = _read_twice(conn, company_id, rows)
    rows = [r for r in rows if r["id"] not in twice]
    tagged = sum(r["value"] for r in rows)
    reported = conn.execute(
        """SELECT value FROM financials WHERE company_id = ? AND metric = 'Revenues'
            AND period_type = 'FY' AND fiscal_year = ?""",
        (company_id, year)).fetchone()
    reported = reported["value"] if reported and reported["value"] else None
    covered = sum(r["value"] for r in rows if r["id"] in set(modelled_ids))
    # Streams run in millions, everything in asset_revenue and financials in dollars.
    stream_rows = [{"name": s["line"], "revenue": s["base_revenue"] * 1e6}
                   for s in (streams or []) if s.get("base_revenue") is not None]
    from_streams = sum(s["revenue"] for s in stream_rows)
    denominator = reported if reported else tagged
    if not denominator:
        return None
    untagged = (reported - tagged - from_streams) if reported else None
    return {
        "fiscal_year": year, "basis": "reported total" if reported else "tagged rows",
        "reported_revenue": reported, "tagged_revenue": tagged,
        "modelled_revenue": covered, "stream_revenue": from_streams,
        # Can go slightly negative where a stream overlaps a tagged row; that is a
        # seeding error and is left visible rather than clamped away.
        "untagged_revenue": untagged,
        "share": (covered + from_streams) / denominator,
        "streams": stream_rows,
        "unmodelled": [{"name": r["brand_name"], "revenue": r["value"],
                        "share": r["value"] / denominator}
                       for r in rows if r["id"] not in set(modelled_ids)][:6],
    }


def _franchises(conn, asset_ids: list) -> list:
    """Every franchise among the modelled assets, and whether its members agree.

    The split is an identity only while the members hold to it: one pool, one ramp, and
    shares that sum to one. Each asset carries its own copy of those numbers because the
    engine values one asset at a time, so nothing stops two members disagreeing. This is
    what notices when they do.
    """
    groups = {}
    for asset_id in asset_ids:
        scalars = (assumptions_module.load(conn, asset_id) or {}).get("scalars") or {}
        if (scalars.get("therapy_mode") or "").strip() != "franchise":
            continue
        pool = scalars.get("franchise_revenue")
        row = conn.execute(
            "SELECT COALESCE(brand_name, generic_name) AS nm FROM assets WHERE id = ?",
            (asset_id,)).fetchone()
        groups.setdefault(pool, []).append({
            "asset_id": asset_id, "name": row["nm"] if row else str(asset_id),
            "growth": scalars.get("franchise_growth_pct"),
            "ramp": scalars.get("share_ramp_pct"),
            "share_now": scalars.get("share_now"),
            "share_plateau": scalars.get("share_plateau")})
    out = []
    for pool, members in groups.items():
        def total(key):
            got = [m[key] for m in members if m[key] is not None]
            return sum(got) if got else None

        def one(key):
            got = {round(m[key], 9) for m in members if m[key] is not None}
            return got.pop() if len(got) == 1 else None

        now, plateau = total("share_now"), total("share_plateau")
        # A share that sums to one at the base year and at the plateau sums to one in
        # every year between, but only while every member decays at the same rate.
        problems = []
        if one("ramp") is None:
            problems.append("members disagree on share_ramp_pct")
        if one("growth") is None:
            problems.append("members disagree on franchise_growth_pct")
        for label, got in (("share_now", now), ("share_plateau", plateau)):
            if got is not None and abs(got - 1.0) > 0.005:
                problems.append(f"{label} sums to {got:.1%}, not 100%")
        out.append({"pool": pool, "members": [m["name"] for m in members],
                    "share_now": now, "share_plateau": plateau,
                    "ramp": one("ramp"), "problems": problems,
                    # Complete only when the shares account for the whole pool. A
                    # franchise missing a member is not wrong, it is partial, and the
                    # products in it are worth less than the pool they sit in.
                    "complete": now is not None and abs(now - 1.0) <= 0.005})
    return out


# --- the sum of the parts ------------------------------------------------------------
# The company as a whole: what the marketed book is worth, what the pipeline adds once
# its probability is taken off, what the lines no asset carries add, and then the
# balance sheet, because an rNPV is an enterprise figure and a share price is an equity
# one. Every part is on file or it is named as missing; nothing is filled in.

ANCHORED = ("marketed", "franchise")


def _cost_of_equity(conn, asset_ids):
    """(ke, basis) from the CAPM components the modelled assets carry, which are the
    company's: risk_free + beta x erp. Falls back to the first WACC on file, and says
    so, where the components are not stated."""
    for asset_id in asset_ids:
        scalars = (assumptions_module.load(conn, asset_id) or {}).get("scalars") or {}
        needed = ("risk_free", "beta", "erp")
        if all(scalars.get(k) is not None for k in needed):
            return (scalars["risk_free"] + scalars["beta"] * scalars["erp"],
                    "CAPM: risk-free plus beta times the equity risk premium")
        rate, basis = forecast.wacc(scalars)
        if rate is not None:
            return rate, f"WACC ({basis}), no equity components on file"
    return None, None


def _balance_sheet(conn, db_path, ticker: str, company_id: int):
    """Net cash in the reporting currency's millions, dated, from the cash-flow view
    the Financials tab already shows, so the two never disagree. Positive is cash."""
    try:
        import cashflow
        built = cashflow.build_cashflow(db_path, ticker)
    except Exception:
        built = None
    if not built:
        return None
    inputs = built.get("inputs") or {}
    if inputs.get("cash") is None:
        return None
    net_debt = built.get("net_debt")
    return {"net_cash": (-net_debt / 1e6) if net_debt is not None else None,
            "cash": inputs["cash"] / 1e6, "currency": built.get("currency"),
            "as_of": inputs.get("balance_sheet_as_of") or built.get("fiscal_year"),
            "debt_basis": inputs.get("debt_basis")}


def _dividends(conn, company_id: int):
    """The last full year's dividends paid, in millions, and the year. Filers sign the
    outflow both ways, so the magnitude is taken."""
    # Only a dividend from the last completed year or the one before counts. GSK's only
    # row is FY2017, paid by a group that still held Haleon, and taking it off a 2026
    # value made the twelve-month figure fall.
    latest = conn.execute(
        """SELECT MAX(fiscal_year) FROM financials WHERE company_id = ?
            AND metric = 'Revenues' AND period_type = 'FY'""", (company_id,)).fetchone()[0]
    if not latest:
        return None, None
    row = conn.execute(
        """SELECT value, fiscal_year FROM financials WHERE company_id = ?
            AND metric = 'DividendsPaid' AND period_type = 'FY' AND value IS NOT NULL
            AND fiscal_year >= ? ORDER BY fiscal_year DESC LIMIT 1""",
        (company_id, latest - 1)).fetchone()
    if not row or not row["value"]:
        return None, None
    return abs(row["value"]) / 1e6, row["fiscal_year"]


def _valuation_anchor(conn):
    """The date every rNPV stands at: the end of the last completed fiscal year, the
    same year assumptions.load hands the engine as its valuation base. Cash flows are
    discounted to it, so a figure read against today's price has to be carried forward
    from it first."""
    import datetime as dt
    row = conn.execute(
        "SELECT MAX(fiscal_year) y FROM financials WHERE metric = 'Revenues'"
        "  AND period_type = 'FY' AND fiscal_year < ?", (dt.date.today().year,)).fetchone()
    return f"{row['y']}-12-31" if row and row["y"] else None


def _years_between(start: str | None, end: str | None) -> float:
    import datetime as dt
    if not (start and end):
        return 0.0
    try:
        days = (dt.date.fromisoformat(end[:10]) - dt.date.fromisoformat(start[:10])).days
    except ValueError:
        return 0.0
    return max(days, 0) / 365.25


_LAUNCH_RECORD: dict = {}


def _launch_record(db_path, ticker: str, anchor: str, lag: int) -> dict:
    """{history_rd, launched}: the R&D the company spent in the ``lag`` years to the
    valuation year, and the ids of its products already selling or approved by then.
    Cached for an hour, since a break-point revalues the book many times."""
    import time
    import approval_dates
    import future_pipeline as FP
    key = (str(db_path), ticker.upper(), anchor, lag)
    hit = _LAUNCH_RECORD.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    base_year = int(anchor[:4])
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (ticker.upper(),)).fetchone()
        out = {"history_rd": {}, "launched": set()}
        if company is not None:
            out["history_rd"] = FP.rd_history(conn, company["id"], base_year - lag + 1,
                                              base_year)
            for row in conn.execute(
                    """SELECT a.id, COALESCE(a.brand_name, a.generic_name) AS name,
                              EXISTS (SELECT 1 FROM asset_revenue r WHERE r.asset_id = a.id
                                        AND r.fiscal_year <= ? AND r.value > 0) AS sold
                         FROM assets a WHERE a.owner_company_id = ?""",
                    (base_year, company["id"])):
                if row["sold"]:
                    out["launched"].add(row["id"])
                    continue
                approved, _route = approval_dates.first_approval(conn, row["id"], row["name"])
                if approved and approved[:10] <= anchor[:10]:
                    out["launched"].add(row["id"])
    finally:
        conn.close()
    _LAUNCH_RECORD[key] = (time.time(), out)
    return out


def _future_pipeline(db_path, parts: list, anchor: str | None, ticker: str = "",
                     rate_override: float | None = None) -> dict:
    """The launches the book's R&D buys, valued. {value, reason, ...}; value is None
    with a reason wherever an input is not on file. ``rate_override`` replaces the blended
    launch productivity, for a break-point asking what rate the price assumes."""
    import future_pipeline as FP
    if not anchor:
        return {"value": None, "reason": "no valuation year on file"}
    base_year = int(anchor[:4])
    book_rd: dict = {}
    totals = {"revenue": 0.0, "cogs": 0.0, "sga": 0.0, "rd": 0.0, "other": 0.0,
              "ebit": 0.0, "tax": 0.0}
    waccs, growths, book_parts, named_parts = [], [], [], []
    for part in parts:
        # A line whose R&D develops something other than medicines buys no launches, and
        # its margins are not the ones a future drug would earn.
        if part.get("buys_launches") is False:
            continue
        rows = part.get("pnl_share") or []
        # Expected revenue: a pipeline product's P&L is unrisked, and a book that counted
        # it in full would leave its launches too little room.
        odds = part.get("pos") if part.get("pos") is not None else 1.0
        book_parts.append({"revenue": {year: (row.get("revenue") or 0.0) * odds
                                       for year, row
                                       in zip(part.get("dcf_years") or [], rows)},
                           "loe_year": part.get("loe_year"),
                           "loe_in_base": part.get("loe_in_base"),
                           "growth": part.get("long_run_growth")})
        if part.get("asset_id") is not None:
            named_parts.append((part["asset_id"], book_parts[-1]))
        for year, row in zip(part.get("dcf_years") or [], rows):
            book_rd[year] = book_rd.get(year, 0.0) + (row.get("rd") or 0.0)
        if rows:
            first = rows[0]
            for k in totals:
                totals[k] += first.get(k) or 0.0
            if part.get("wacc") is not None and first.get("revenue"):
                waccs.append((first["revenue"], part["wacc"]))
            if part.get("long_run_growth") is not None and first.get("revenue"):
                growths.append((first["revenue"], part["long_run_growth"]))
    if not book_rd or not totals["revenue"]:
        return {"value": None, "reason": "no R&D in the modelled book's P&L"}
    pool = FP.pooled(db_path)
    if pool.get("rate") is None:
        return {"value": None, "reason": "no pooled launch productivity on file"}
    bounds = FP.defaults()
    loe_default = (assumptions_module.loe_defaults().get("unknown") or {})
    erosion = (assumptions_module.erosion_defaults().get("unknown") or {})
    if not (loe_default.get("years_from_launch") and erosion.get("year1_pct") is not None):
        return {"value": None, "reason": "no exclusivity or erosion default on file"}
    revenue = totals["revenue"]
    ratios = {"cogs": totals["cogs"] / revenue, "sga": totals["sga"] / revenue,
              "rd": totals["rd"] / revenue, "other": totals["other"] / revenue,
              "tax": (totals["tax"] / totals["ebit"]) if totals["ebit"] > 0 else 0.0}
    wacc = sum(r * w for r, w in waccs) / sum(r for r, _ in waccs) if waccs else None
    if wacc is None:
        return {"value": None, "reason": "no discount rate in the modelled book"}
    lag = int(bounds["lag_years"]["value"])
    own = next((f for f in pool.get("filers") or [] if f["ticker"] == ticker.upper()), None)
    # The filer's own record at its credibility, the pool for the rest. A filer with no
    # launch record on file takes the pool outright.
    rate_used = own["blended"] if own and own.get("blended") is not None else pool["rate"]
    if rate_override is not None:
        rate_used = rate_override
    # The franchise grows no faster than the book says its own products do in the long
    # run. Where no long-run rate is on file it replaces the book and does not grow.
    long_run = (sum(r * g for r, g in growths) / sum(r for r, _ in growths)
                if growths else 0.0)
    long_run_basis = ("the book's revenue-weighted long-run growth" if growths
                      else "no long-run growth on file, so replacement only")
    horizon = int(bounds["horizon_years"]["value"])
    book = FP.book_revenue(book_parts, list(range(base_year + 1, base_year + 1 + horizon)),
                           erosion["year1_pct"], erosion.get("decay_pct") or 0.0)
    space, peak, peak_year = FP.room(book, long_run)
    # Launches the R&D already spent will buy, less the ones the book names: a product
    # neither selling nor approved by the valuation date is one of those launches.
    record = (_launch_record(db_path, ticker, anchor, lag) if ticker
              else {"history_rd": {}, "launched": set()})
    named: dict = {}
    for asset_id, entry in named_parts:
        if asset_id in record["launched"]:
            continue
        for year, value in entry["revenue"].items():
            named[year] = named.get(year, 0.0) + value
    got = FP.simulate(book_rd, rate_used, lag, int(loe_default["years_from_launch"]),
                      erosion["year1_pct"], erosion.get("decay_pct") or 0.0, ratios,
                      wacc, base_year, horizon, long_run_growth=long_run, room=space,
                      history_rd=record["history_rd"], named=named)
    return {"value": got["value"], "reason": None, "rate": pool["rate"],
            "rate_used": rate_used,
            "own_rate": own["rate"] if own else None,
            "own_launches": own["launch_count"] if own else 0,
            "credibility": own["credibility"] if own else 0.0,
            "credibility_k": (pool.get("credibility") or {}).get("k"),
            "own_counted": bool(own and own["counted"]),
            "pooled_filers": pool["n"], "lag_years": lag,
            "lag_source": bounds["lag_years"]["source"],
            "life_years": int(loe_default["years_from_launch"]),
            "first_launch_year": got["first_launch_year"], "cohorts": got["cohorts"],
            "replacement": got["replacement"], "wacc": wacc, "ratios": ratios,
            "renewal": got["renewal"], "credited_share": got["credited_share"],
            "long_run_growth": long_run, "long_run_basis": long_run_basis,
            "book_rd_first": book_rd.get(base_year + 1),
            "book_peak": peak, "book_peak_year": peak_year,
            "history_rd": record["history_rd"], "history_cohorts": got.get("history_cohorts"),
            "named_launch_revenue": sum(named.values()),
            "named_overlap": got.get("named_overlap"),
            "capped_from": got.get("capped_from"), "capped_share": got.get("capped_share"),
            "flows": [f for f in got["flows"] if f["revenue"]][:40]}


def _sotp(conn, db_path, ticker: str, company_id: int, lines: list, streams: list,
          shares, close, reported_revenue: list, coverage, close_date=None):
    """The sum of the parts, and the twelve-month value it rolls to.

    Marketed products count at their rNPV, which for an approved product is its NPV.
    Pipeline assets count at their rNPV, the NPV cut by the probability of success,
    and the unrisked figure is kept beside it so the haircut is visible. Lines no
    asset carries count in full. That sum is the modelled enterprise value; net cash
    turns it into equity; diluted shares turn equity into a figure per share.

    The twelve-month value is the standard roll-forward: a DCF's value grows at the
    cost of equity over the year, and the dividend paid out during it is subtracted,
    since it has left the company by then. It is a mechanical consequence of the
    model, not a target, and it is only as good as the parts above it. Whatever the
    model does not reach is named beside the figure rather than filled in.
    """
    def per_share(mm):
        return (mm * 1e6 / shares) if (shares and mm is not None) else None

    counted = [l for l in lines if l.get("counted", True)]
    # Approved against not yet approved, not how revenue is built: Casgevy is on sale
    # and patient-built, and its 81% is durability and reimbursement, not approval.
    marketed = [l for l in counted if l.get("is_marketed")]
    pipeline = [l for l in counted if not l.get("is_marketed")]
    m_rnpv = sum(l["rnpv_share"] for l in marketed)
    p_rnpv = sum(l["rnpv_share"] for l in pipeline)
    p_npv = sum(l.get("npv_share") or 0.0 for l in pipeline)
    s_rnpv = sum(s["rnpv"] for s in streams)
    # The research the book is charged buys launches beyond the modelled pipeline, and
    # this is what that has historically been worth. Built over the counted assets and
    # the lines, which are what pays the R&D.
    future = _future_pipeline(db_path, counted + list(streams), _valuation_anchor(conn),
                              ticker)
    f_value = future.get("value") or 0.0
    ev = m_rnpv + p_rnpv + s_rnpv + f_value
    balance = _balance_sheet(conn, db_path, ticker, company_id)
    net_cash = balance["net_cash"] if balance else None
    cash = balance["cash"] if balance else None
    ke, ke_basis = _cost_of_equity(conn, [l["asset_id"] for l in counted])
    # The rNPV stands at the last fiscal year end and the price at the last close. The
    # enterprise value is carried across that gap at the cost of equity before it is
    # read against the price: Amgen's gap is eight months, about 5.6% of the value, and
    # labelling the year-end figure "today" left it uncredited. Net cash is added after
    # the carry, since the balance sheet is already the latest one filed.
    anchor = _valuation_anchor(conn)
    years_to_price = _years_between(anchor, close_date) if ke is not None else 0.0
    carry = ev * ((1.0 + ke) ** years_to_price - 1.0) if ke is not None else 0.0
    enterprise_today = ev + carry
    equity = (enterprise_today + net_cash) if net_cash is not None else None
    dividends, div_year = _dividends(conn, company_id)
    equity_ps = per_share(equity)
    dps = per_share(dividends)
    forward = None
    if equity_ps is not None and ke is not None:
        forward = equity_ps * (1.0 + ke) - (dps or 0.0)

    # Revenue by year, split the same way, for the next three years beside the last
    # reported one. Pipeline revenue is shown before and after its probability.
    by_year: dict = {}
    for group, items in (("marketed", marketed), ("pipeline", pipeline)):
        for l in items:
            pos = l.get("pos") if l.get("pos") is not None else 1.0
            for year, value in zip(l.get("years") or [], l.get("revenue_share") or []):
                entry = by_year.setdefault(year, {"marketed": 0.0, "pipeline": 0.0,
                                                  "pipeline_risked": 0.0, "lines": 0.0})
                entry[group] += value
                if group == "pipeline":
                    entry["pipeline_risked"] += value * pos
    for s in streams:
        for year, value in zip(s.get("years") or [], s.get("revenue") or []):
            by_year.setdefault(year, {"marketed": 0.0, "pipeline": 0.0,
                                      "pipeline_risked": 0.0, "lines": 0.0})["lines"] += value
    last = next((r for r in sorted(reported_revenue, key=lambda r: -r["fiscal_year"])
                 if r.get("value") is not None), None)
    first_year = (last["fiscal_year"] + 1) if last else min(by_year, default=None)
    path = []
    if first_year is not None:
        for year in range(first_year, first_year + 3):
            entry = by_year.get(year)
            if not entry:
                continue
            path.append({"year": year, **entry,
                         "total": entry["marketed"] + entry["pipeline"] + entry["lines"],
                         "total_risked": (entry["marketed"] + entry["pipeline_risked"]
                                          + entry["lines"])})
    not_valued = [{"name": u["name"], "revenue": u["revenue"] / 1e6}
                  for u in ((coverage or {}).get("unmodelled") or [])]
    return {
        "marketed": {"n": len(marketed), "rnpv": m_rnpv, "per_share": per_share(m_rnpv)},
        "pipeline": {"n": len(pipeline), "rnpv": p_rnpv, "npv": p_npv,
                     "per_share": per_share(p_rnpv),
                     "per_share_unrisked": per_share(p_npv)},
        "lines": {"n": len(streams), "rnpv": s_rnpv, "per_share": per_share(s_rnpv)},
        "future": {**{k: v for k, v in future.items() if k != "flows"},
                   "per_share": per_share(future.get("value")),
                   "flows": future.get("flows") or []},
        # The sum without the future pipeline, so the run-off value stays readable.
        "enterprise_book_only": ev - f_value,
        "enterprise": ev, "enterprise_per_share": per_share(ev),
        "valuation_anchor": anchor, "price_date": close_date,
        "years_to_price": years_to_price, "carry": carry,
        "carry_per_share": per_share(carry),
        "enterprise_today": enterprise_today,
        "enterprise_today_per_share": per_share(enterprise_today),
        "net_cash": net_cash, "net_cash_per_share": per_share(net_cash),
        "cash": cash, "cash_per_share": per_share(cash),
        "balance_sheet_as_of": balance["as_of"] if balance else None,
        "debt_basis": balance.get("debt_basis") if balance else None,
        "equity": equity, "equity_per_share": equity_ps,
        "cost_of_equity": ke, "cost_of_equity_basis": ke_basis,
        "dividends": dividends, "dividends_year": div_year, "dps": dps,
        "forward_12m": forward, "close": close,
        "upside": (forward / close - 1.0) if (forward is not None and close) else None,
        "upside_today": (equity_ps / close - 1.0)
        if (equity_ps is not None and close) else None,
        "revenue_path": path,
        "last_reported": ({"fiscal_year": last["fiscal_year"], "value": last["value"]}
                          if last else None),
        # The modelled book's own revenue in the reported year, the like-for-like base
        # for a growth rate. Dividing the modelled forecast by the whole company's total
        # showed Sanofi falling 21.5% when the book it models grows 15%.
        "last_modelled": ((((coverage or {}).get("modelled_revenue") or 0.0)
                           + ((coverage or {}).get("stream_revenue") or 0.0)) / 1e6
                          if (coverage or {}).get("fiscal_year") else None),
        "not_valued": not_valued,
        "missing": [what for what, ok in (
            ("net cash: no balance sheet on file" if cash is None else
             "net cash: no debt line filed near the balance sheet, so the sum stops "
             "at enterprise value", net_cash is not None),
            ("diluted shares: no share count on file", bool(shares)),
            ("cost of equity: no CAPM components on file", ke is not None),
            ("dividend: no recent dividends-paid line on file, so nothing is taken off "
             "the roll-forward", dividends is not None),
            (f"future pipeline: {future.get('reason')}", future.get("value") is not None),
            ("share price: none on file", bool(close))) if not ok],
    }


def company_verdict(db_path, ticker: str):
    """Every modelled asset in one name, per share, against what the share costs.

    An analyst covers a company, not a compound, so this is where the per-asset calls add
    up. It reports three things together and refuses to report the first without the
    other two: what the modelled pipeline is worth per share, what fraction of today's
    price that explains, and how much of the business it actually covers.

    The last one is the guard. A model over one product of six will always look small
    against a market capitalisation, and reading that as "the market is wrong" rather
    than "the model is thin" is the easiest mistake this page could invite.
    """
    rollup = company_rollup(db_path, ticker)
    if rollup is None:
        return None
    conn = db.get_connection(db_path)
    try:
        company = _company(conn, ticker)
        shares = _diluted_shares(conn, company["id"])
        close, close_date = _last_close(conn, company["id"])
        modelled_ids = [line["asset_id"] for line in rollup["lines"]]
        coverage = _revenue_coverage(conn, company["id"],
                                     [l["asset_id"] for l in rollup["lines"]
                                      if l.get("counted", True)],
                                     streams=rollup.get("streams"))
        franchises = _franchises(conn, modelled_ids)
        catalyst = None
        for asset_id in modelled_ids:
            found = _next_catalyst(conn, asset_id)
            if found and (catalyst is None
                          or found["expected_date"] < catalyst["expected_date"]):
                catalyst = found
    finally:
        conn.close()

    per_share = rollup.get("rnpv_per_share")
    lines = []
    for line in rollup["lines"]:
        lines.append({**line,
                      "per_share": (line["rnpv_share"] * 1e6 / shares)
                      if shares else None})
    lines.sort(key=lambda r: -(r["rnpv_share"] or 0))
    streams = [{**s, "per_share": (s["rnpv"] * 1e6 / shares) if shares else None}
               for s in rollup.get("streams") or []]
    conn = db.get_connection(db_path)
    try:
        sotp = _sotp(conn, db_path, rollup["ticker"], company["id"], lines, streams,
                     shares, close, rollup["reported_revenue"], coverage,
                     close_date=close_date)
    finally:
        conn.close()
    return {
        "ok": True, "ticker": rollup["ticker"], "name": company["name"],
        "sotp": sotp,
        "modelled": lines, "refused": rollup.get("refused") or [],
        "rnpv_total": rollup["rnpv_total"], "per_share": per_share,
        "diluted_shares": shares, "close": close, "close_date": close_date,
        "pct_of_price": (per_share / close) if (per_share and close) else None,
        "market_cap": (shares * close) if (shares and close) else None,
        "coverage": coverage, "next_catalyst": catalyst, "franchises": franchises,
        "streams": streams, "stream_refused": rollup.get("stream_refused") or [],
        "placeholders": rollup.get("placeholders") or [],
        "shared_lines": rollup.get("shared_lines") or [],
        "combined": rollup["combined"], "reported_revenue": rollup["reported_revenue"],
    }
