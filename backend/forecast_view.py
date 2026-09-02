"""The forecast endpoints' builder: engine plus database, per asset and per company.

``forecast.py`` is pure and ``assumptions.py`` is the layer it computes from; this module
is the glue the API calls. A refusal from the engine is returned as data rather than
raised, because "these three keys are missing" is the empty state the tab shows, not a
server error.
"""

from __future__ import annotations

import copy
import math

import assumptions as assumptions_module
import company_lines
import db
import forecast


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
        return {**base, "ok": True, "result": result}
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
        xs = [round(rate + step, 4) for step in (-0.02, -0.01, 0.0, 0.01, 0.02)]
        ys = [round(price * f, 3) for f in (0.78, 0.89, 1.0, 1.11, 1.22)]
        grid = forecast.sensitivity(inputs, "wacc", xs,
                                    "net_price_per_patient", ys)
        bases = {"x": built["wacc_basis"], "y": "net price per patient"}
    return {"ok": True, "preset": preset, "bases": bases, **grid}


def whatif(db_path, ticker: str, asset_id: int, scenario: str = "base",
           volume=None, price=None, wacc=None, pos=None):
    """The slider endpoint: the engine run twice, base beside the variation.

    Four levers, each a real driver rather than a scaler of the answer. Volume
    multiplies the patient curve, which is the acceptance lever the CASGEVY audit
    surfaced: the workbook's own scenario block varies exactly this. Price sets the net
    price per patient. WACC and PoS replace the derived values outright, and PoS strips
    the composite factors first because factors beat a stated value in the engine.

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
                "patients": result["patients"]["total"],
                "rnpv": result["rnpv"], "npv": result["npv"],
                "owner_rnpv": result["owner_rnpv"],
                "partner_rnpv": result["partner_rnpv"],
                "terminal_pv": result["terminal_pv"],
                "wacc": result["wacc"], "pos": result["pos"]}

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
    try:
        varied = forecast.build(varied_inputs)
    except forecast.ForecastError as err:
        return {"ok": False, "missing": err.missing}
    return {"ok": True, "base": slim(base), "varied": slim(varied),
            "overrides": {"volume": volume, "price": price, "wacc": wacc,
                          "pos": pos}}


def _diluted_shares(conn, company_id: int):
    """The share count a per-share figure divides by, in the unit the price is quoted in.

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
    for metric in ("WeightedAverageDilutedShares", "SharesOutstanding"):
        row = conn.execute(
            """SELECT value FROM financials WHERE company_id = ? AND metric = ?
                AND period_type IN ('FY', 'instant') ORDER BY fiscal_year DESC,
                period_end DESC LIMIT 1""", (company_id, metric)).fetchone()
        if row and row["value"]:
            return row["value"]
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
    ratio = conn.execute(
        """SELECT r.ordinary_per_adr FROM adr_ratios r JOIN companies c ON c.ticker = r.ticker
            WHERE c.id = ?""", (company_id,)).fetchone()
    per_adr = ratio["ordinary_per_adr"] if ratio and ratio["ordinary_per_adr"] else 1.0
    return ordinary / per_adr if ordinary > 0 else None


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
        lines.append({"asset_id": asset_id, "name": state["name"], "share": share,
                      "rnpv_share": result["rnpv"] * share, "counted": counted,
                      "years": result["years"],
                      "revenue_share": [v * share
                                        for v in result["revenue_after_loe"]]})
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
                        "years": result["years"], "revenue": result["revenue_after_loe"],
                        "unsourced": built.get("unsourced") or [],
                        "notes": result.get("notes") or []})
    per_share = (rnpv_total * 1e6 / shares) if shares else None
    return {"ticker": company["ticker"], "lines": lines, "refused": refused,
            "placeholders": placeholders, "streams": streams,
            "stream_refused": stream_refused,
            "combined": sorted(combined.items()),
            "rnpv_total": rnpv_total, "rnpv_per_share": per_share,
            "reported_revenue": revenue_actuals}


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

    Each lever is pushed by overriding the computed value, not the raw input, because
    WACC arrives from CAPM components and PoS from composite factors, and perturbing a
    scalar that is not there moves nothing. PoS strips its factors first, since factors
    beat a stated value in the engine.
    """
    scalars = inputs.get("scalars") or {}
    base_rnpv = built["rnpv"]
    levers = [("net price", "net_price_per_patient", scalars.get("net_price_per_patient")),
              ("discount rate", "wacc", built["wacc"]),
              ("probability of success", "pos", built["pos"]),
              ("persistence", "discontinuation_pct",
               scalars.get("discontinuation_pct"))]
    out = []
    for label, key, current in levers:
        if current is None:
            continue
        swings = []
        for direction in (1 - _LEVER_STEP, 1 + _LEVER_STEP):
            trial = dict(scalars)
            trial[key] = current * direction
            if key == "pos":
                trial[key] = min(trial[key], 1.0)
                for factor in ("pos_regulatory", "pos_launch", "pos_reimbursement",
                               "pos_competition"):
                    trial.pop(factor, None)
            try:
                moved = forecast.build({**inputs, "scalars": trial})["rnpv"]
            except forecast.ForecastError:
                continue
            swings.append(moved - base_rnpv)
        if len(swings) == 2:
            out.append({"lever": label, "key": key, "value": current,
                        "down": min(swings), "up": max(swings),
                        "span": max(swings) - min(swings)})
    out.sort(key=lambda r: -abs(r["span"]))
    return out


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
        "spread": spread, "has_range": has_range,
        "levers": _levers(inputs, built),
        "next_catalyst": catalyst,
        "unsourced": [r["key"] for r in rows if not (r["source"] or "").strip()],
        "notes": built.get("notes") or [],
    }


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
    return {
        "ok": True, "ticker": rollup["ticker"], "name": company["name"],
        "modelled": lines, "refused": rollup.get("refused") or [],
        "rnpv_total": rollup["rnpv_total"], "per_share": per_share,
        "diluted_shares": shares, "close": close, "close_date": close_date,
        "pct_of_price": (per_share / close) if (per_share and close) else None,
        "market_cap": (shares * close) if (shares and close) else None,
        "coverage": coverage, "next_catalyst": catalyst, "franchises": franchises,
        "streams": streams, "stream_refused": rollup.get("stream_refused") or [],
        "placeholders": rollup.get("placeholders") or [],
        "combined": rollup["combined"], "reported_revenue": rollup["reported_revenue"],
    }
