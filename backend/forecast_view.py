"""The forecast endpoints' builder: engine plus database, per asset and per company.

``forecast.py`` is pure and ``assumptions.py`` is the layer it computes from; this module
is the glue the API calls. A refusal from the engine is returned as data rather than
raised, because "these three keys are missing" is the empty state the tab shows, not a
server error.
"""

from __future__ import annotations

import copy

import assumptions as assumptions_module
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
        shares = conn.execute(
            """SELECT value FROM financials WHERE company_id = ?
                AND metric = 'WeightedAverageDilutedShares' AND period_type = 'FY'
                ORDER BY fiscal_year DESC LIMIT 1""", (company["id"],)).fetchone()
    finally:
        conn.close()

    lines, refused = [], []
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
        for year, value in zip(result["years"], result["revenue_after_loe"]):
            combined[year] = combined.get(year, 0.0) + value * share
        rnpv_total += result["rnpv"] * share
        lines.append({"asset_id": asset_id, "name": state["name"], "share": share,
                      "rnpv_share": result["rnpv"] * share,
                      "years": result["years"],
                      "revenue_share": [v * share
                                        for v in result["revenue_after_loe"]]})
    per_share = None
    if shares and shares["value"]:
        per_share = rnpv_total * 1e6 / shares["value"]
    return {"ticker": company["ticker"], "lines": lines, "refused": refused,
            "combined": sorted(combined.items()),
            "rnpv_total": rnpv_total, "rnpv_per_share": per_share,
            "reported_revenue": revenue_actuals}
