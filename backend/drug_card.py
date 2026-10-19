"""One drug in one indication, everything the book holds on it, for the card the
Comps > Indications view opens when a drug is clicked.

Nothing here is computed afresh. The card gathers what the landscape, the clinical
scorecard, the forecast, the catalyst stakes and the product profile already say about
the drug, and keeps each figure with the basis its source gave it. A field no source
fills stays None, and a section with nothing on file comes back empty, so the page can
say "no free data" rather than show an estimate.
"""

from __future__ import annotations

import datetime as dt

import assumptions as assumptions_module
import db
import epidemiology
import forecast
import forecast_view
import landscape as landscape_module
import pool_crowding
import product_profile as product_profile_module

# The inputs of a patient build, in the order the engine multiplies them.
PATIENT_KEYS = ("prevalence", "incidence", "eligible_pct", "penetration_peak_pct",
                "exus_multiple")
PRICE_KEYS = ("list_price_per_patient", "gross_to_net_pct", "net_price_per_patient")
# Modes valued off the product's own reported revenue rather than built from patients.
REVENUE_MODES = ("marketed", "franchise")
# The efficacy rows a card lists before it points to the Efficacy view for the rest.
MAX_EFFICACY_ROWS = 30
MAX_CATALYSTS = 6


def _candidate(land: dict, asset_id: int) -> dict | None:
    for c in land.get("candidates") or []:
        if c.get("asset_id") == asset_id or asset_id in (c.get("asset_ids") or []):
            return c
    return None


def _head(c: dict) -> dict:
    keys = ("name", "brands", "ticker", "company", "stage", "phase_here", "is_marketed",
            "on_label", "phase_elsewhere", "modality", "molecule_type", "mechanisms",
            "targets", "classes", "route", "boxed_warning", "linked_by",
            "pharmacology_source")
    return {k: c.get(k) for k in keys}


def _score(scorecard: dict | None, rep: int) -> dict | None:
    """The drug's place on the scorecard: rank among the placed, its four scores and the
    lines each rests on, or why it is not placed."""
    assets = (scorecard or {}).get("assets") or []
    a = next((x for x in assets if x.get("asset_id") == rep), None)
    if a is None:
        return None
    placed = [x for x in assets if x.get("placed")]

    def part(d):
        d = d or {}
        return {"score": d.get("score"), "parts": d.get("parts"), "lines": d.get("lines") or [],
                "notes": d.get("notes") or [], "size_basis": d.get("size_basis"),
                "read_with_care": d.get("read_with_care"),
                # Each measure's effect against its control with its 95% interval, as the
                # scorecard averaged it: what the card's forest plot draws.
                "pooled": [{k: p.get(k) for k in (
                    "measure", "control", "scale", "effect", "lo", "hi", "hazard_ratio",
                    "hazard_ratio_lo", "hazard_ratio_hi", "k", "participants", "weeks",
                    "trials")} for p in d.get("pooled") or []]}
    ev = a.get("evidence") or {}
    return {"placed": bool(a.get("placed")), "rank": a.get("rank"),
            "of": len(placed), "scored_of": len(assets),
            "rank_range": a.get("rank_range"), "overall": a.get("overall"),
            "why_not": a.get("why_not"),
            "efficacy": part(a.get("efficacy")), "safety": part(a.get("safety")),
            "evidence": {"score": ev.get("score"), "participants": ev.get("participants"),
                         "phase": ev.get("phase"), "confidence": ev.get("confidence")},
            "regimen": a.get("regimen")}


def _efficacy(land: dict, rep: int) -> dict:
    """The drug's own arms on every posted endpoint, each against its trial's comparator,
    with how many drugs the endpoint compares."""
    groups, total = [], 0
    for g in land.get("endpoints") or []:
        rows = [r for r in g.get("rows") or []
                if r.get("asset_id") == rep and r.get("value") is not None]
        if not rows:
            continue
        total += len(rows)
        groups.append({
            "title": g.get("title"), "unit": g.get("unit"), "param_type": g.get("param_type"),
            "n_assets": g.get("n_assets"),
            "rows": [{k: r.get(k) for k in (
                "nct_id", "phase", "weeks", "arm", "arm_is_drug", "arm_names_drug",
                "arm_is_control", "category", "n", "value",
                "spread", "placebo", "reference_kind", "reference_arm", "delta", "estimate",
                "ci", "p_value")} for r in rows]})
    shown, out = 0, []
    for g in groups:
        room = MAX_EFFICACY_ROWS - shown
        if room <= 0:
            break
        out.append({**g, "rows": g["rows"][:room]})
        shown += len(out[-1]["rows"])
    return {"groups": out, "rows": total, "shown": shown}


def _trials(conn, c: dict) -> list:
    trials = c.get("trials") or []
    ncts = [t["nct_id"] for t in trials if t.get("nct_id")]
    have = set()
    if ncts:
        have = {r["nct_id"] for r in conn.execute(
            "SELECT nct_id FROM trial_result_fetches WHERE has_results = 1 AND nct_id IN"
            f" ({','.join('?' * len(ncts))})", ncts)}
    return [{**t, "has_results": t.get("nct_id") in have} for t in trials]


def _rows_by_key(rows: list, indication_id) -> dict:
    """{key: row} for the asset's assumption rows, the indication's own row before the
    asset-wide one."""
    out = {}
    for r in rows:
        if r.get("year") is not None or (r.get("region") or "US") != "US":
            continue
        own = r.get("indication_id") == indication_id
        if own or (r.get("indication_id") is None and r["key"] not in out):
            out[r["key"]] = r
    return out


def _patients(conn, aid: int, land: dict) -> dict:
    """The patient build behind one modelled asset in this indication: each input with
    its unit, source and evidence grade, the crowding the pool applied and the net price.
    ``indication`` is None where the asset is modelled but not for this disease."""
    ind = land.get("indication") or {}
    names = {n.lower() for n in (ind.get("members") or []) + [ind.get("name") or ""] if n}
    inputs = assumptions_module.load(conn, aid, "base")
    entry = next((e for e in inputs.get("indications") or []
                  if e.get("indication_id") == ind.get("id")
                  or (e.get("name") or "").lower() in names), None)
    out = {"asset_id": aid, "indication": None,
           "modelled_for": [e.get("name") for e in inputs.get("indications") or []
                            if e.get("name")],
           "inputs": [], "price": [], "net_price": None, "crowding": None}
    rows = assumptions_module.rows(conn, aid, "base")
    asset_rows = _rows_by_key(rows, None)
    scalars = inputs.get("scalars") or {}
    for key in PRICE_KEYS:
        if scalars.get(key) is None:
            continue
        r = asset_rows.get(key) or {}
        out["price"].append({"key": key, "value": scalars[key], "unit": r.get("unit"),
                             "source": r.get("source"), "evidence": r.get("evidence")})
    out["net_price"] = forecast.net_price(scalars)
    if entry is None:
        return out
    out["indication"] = entry.get("name")
    own = _rows_by_key(rows, entry.get("indication_id"))
    known = None
    for key in PATIENT_KEYS:
        value = (entry.get("scalars") or {}).get(key)
        if value is None:
            continue
        r = own.get(key)
        if r is None and key in ("prevalence", "incidence"):
            # Filled from the disease's own row when the asset carries none.
            known = known if known is not None else (
                epidemiology.for_indication(entry.get("name") or "") or {})
            r = {"source": known.get("source"), "evidence": None, "unit": "people"}
        r = r or {}
        out["inputs"].append({"key": key, "value": value, "unit": r.get("unit"),
                              "source": r.get("source"), "evidence": r.get("evidence")})
    crowd = next((x for x in inputs.get("crowding") or []
                  if x.get("indication") == entry.get("name")), None)
    if crowd:
        out["crowding"] = {"factor": crowd.get("factor"), "stated": crowd.get("stated"),
                           "applied": crowd.get("applied")}
    return out


def _path(f: dict | None, aid: int) -> dict | None:
    """One modelled asset's revenue path: the modelled years after its loss of
    exclusivity, risked by its probability of success where that is below one (the book's
    own rule for pipeline revenue, forecast_view.company_verdict), and the full years it
    reported. None where the forecast does not build."""
    if not f or not f.get("ok") or not (f.get("result") or {}).get("years"):
        return None
    r = f["result"]
    pos = r.get("pos")
    revenue = list(r.get("revenue_after_loe") or [])
    return {"asset_id": aid, "name": f.get("name"), "years": list(r["years"]),
            "revenue": revenue, "pos": pos,
            "risked": ([v * pos for v in revenue] if pos is not None and pos < 1 else None),
            "loe_year": r.get("loe_year"),
            "actuals": [a for a in f.get("actuals") or [] if a.get("value") is not None]}


def _pool_path(conn, land: dict, ids: list) -> dict | None:
    """The drug's patients started a year before and after the pool is counted once,
    beside the pool each year, from the same solve the landscape's pool figure comes
    from. None where the drug is not one of the pool's claimants."""
    try:
        members = landscape_module._members(conn, (land.get("indication") or {}).get("id"))
    except Exception:
        return None
    for m in members or []:
        claims = pool_crowding.claimants(conn, m["id"])
        if not claims:
            continue
        mine = next((c for c in claims if c["asset_id"] in ids), None)
        if mine is None:
            return None
        starts = [c["start"] for c in claims if c["start"]]
        first = int(min(starts)) if starts else 0
        last = int(max(starts)) if starts else 0
        got = pool_crowding.solve(claims, years=(last - first) + 22, first_year=first)
        a = next((x for x in got["assets"] if x["asset_id"] == mine["asset_id"]), None)
        if a is None:
            return None
        return {"years": got["years"], "before": a["uncrowded"], "after": a["crowded"],
                "pooled": bool(a["pooled"]),
                "pool": [row["pool"] for row in got.get("shared") or []],
                "per_year": bool(got.get("pool_per_year"))}
    return None


def _valuation(v: dict | None) -> dict | None:
    if not v:
        return None
    if not v.get("ok"):
        return {"ok": False, "name": v.get("name"), "missing": v.get("missing") or []}
    gate = v.get("gate") or None
    if gate:
        gate = {k: gate.get(k) for k in (
            "label", "date", "date_basis", "due", "why", "trial", "p_gate", "pos_now",
            "pos_success", "pos_failure", "per_share_now", "per_share_success",
            "per_share_failure", "basis", "held", "band", "evidence")}
    launch = v.get("launch") or {}
    return {"ok": True, "asset_id": v.get("asset_id"), "name": v.get("name"),
            "mode": v.get("mode"), "per_share": v.get("per_share"),
            "pct_of_price": v.get("pct_of_price"), "close": v.get("close"),
            "close_date": v.get("close_date"), "rnpv": v.get("rnpv"),
            "peak_revenue": v.get("peak_revenue"), "peak_year": v.get("peak_year"),
            "pos": v.get("pos"), "pos_basis": v.get("pos_basis"),
            "loe_year": v.get("loe_year"), "loe_basis": v.get("loe_basis"),
            "wacc": v.get("wacc"), "gate": gate, "next_catalyst": v.get("next_catalyst"),
            "launch_year": launch.get("seed_year"), "launch_source": launch.get("seed_source")}


def _catalysts(stakes: dict | None, ids: list, today: str) -> list:
    rows = [r for k in ("priced", "unpriced") for r in (stakes or {}).get(k) or []
            if r.get("asset_id") in ids and (r.get("expected_date") or "") >= today]
    rows.sort(key=lambda r: r.get("expected_date") or "")
    return [{k: r.get(k) for k in (
        "expected_date", "date_confidence", "catalyst_type", "title", "description",
        "source_url", "priced", "gate_label", "per_share", "p_gate", "pos_success",
        "pos_failure", "why")} for r in rows[:MAX_CATALYSTS]]


def _commercial(profile: dict | None) -> dict | None:
    if not profile:
        return None
    return {k: profile.get(k) for k in (
        "brand", "generic", "first_approval", "revenue", "quarterly_revenue", "loe",
        "demand", "access", "supplement_count")}


def card(db_path, land: dict, asset_id: int, *, scorecard: dict | None = None,
         verdict_for=None, verdict_of=None, stakes_for=None, forecast_of=None,
         today: str | None = None):
    """The card for ``asset_id`` in the landscape ``land``; None when the drug is not a
    candidate here.

    ``verdict_for(ticker)`` hands the landscape the company verdict it reads the modelled
    lines from, ``verdict_of(ticker, asset_id)`` one asset's verdict and
    ``stakes_for(ticker)`` the company's catalyst stakes and ``forecast_of(ticker,
    asset_id)`` one asset's forecast (its revenue path); each falls back to computing
    the read here, so the API passes its response cache and a test passes fixtures."""
    c = _candidate(land, asset_id)
    if c is None:
        return None
    rep = c["asset_id"]
    ids = list(c.get("asset_ids") or [rep])
    ticker = c.get("ticker")
    today = today or dt.date.today().isoformat()

    lines = landscape_module._model_lines(db_path, {ticker}, verdict_for)
    modelled = [a for a in ids if lines.get(a)]
    verdict_of = verdict_of or (lambda t, a: forecast_view.verdict(db_path, t, a))
    values = []
    for aid in modelled:
        try:
            values.append(_valuation(verdict_of(ticker, aid)))
        except Exception as exc:  # one asset's read failing leaves the rest of the card
            values.append({"ok": False, "asset_id": aid, "missing": [str(exc)]})
    forecast_of = forecast_of or (
        lambda t, a: forecast_view.asset_forecast(db_path, t, a))
    paths = []
    for aid in modelled:
        try:
            got = _path(forecast_of(ticker, aid), aid)
        except Exception:
            got = None
        if got:
            paths.append(got)
    try:
        stakes = (stakes_for(ticker) if stakes_for else None) or \
            forecast_view.catalyst_stakes(db_path, ticker)
    except Exception:
        stakes = None

    conn = db.get_connection(db_path)
    try:
        trials = _trials(conn, c)
        try:
            pool_path = _pool_path(conn, land, ids)
        except Exception:
            pool_path = None
        patients = []
        for aid in modelled:
            try:
                patients.append(_patients(conn, aid, land))
            except Exception:
                continue
    finally:
        conn.close()

    commercial = None
    if c.get("is_marketed"):
        commercial = _commercial(product_profile_module.product_profile(db_path, ticker, rep))

    pool = land.get("pool") or None
    safety = next((s for s in land.get("safety") or [] if s.get("asset_id") == rep), None)
    return {
        "ok": True, "as_of": today,
        "indication": {k: (land.get("indication") or {}).get(k) for k in ("id", "name")},
        "asset_id": rep, "asset_ids": ids,
        "head": _head(c),
        "score": _score(scorecard, rep),
        "efficacy": _efficacy(land, rep),
        "safety": safety,
        "trials": trials,
        "with_results": c.get("with_results"),
        "readouts": c.get("readouts") or [],
        "pool": {"indication": pool, "own": c.get("pool")} if (pool or c.get("pool")) else None,
        "pool_path": pool_path,
        "patients": patients,
        "model": c.get("model"),
        "valuation": values,
        "paths": paths,
        "catalysts": _catalysts(stakes, ids, today),
        "commercial": commercial,
    }
