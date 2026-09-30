"""What stands behind one company's valuation: its dated catalysts and its competition.

The Comps tab's Valuation view says where a company trades against its peers. Its Drivers
and risks section then has to say what could move that, and two things the book holds are
not multiples at all: the events dated inside the next twelve months, and how contested
the company's most valuable indications are. This module assembles both for one company
(docs/design/comps-valuation.md, section 12.2).

- **Catalysts.** Every pending catalyst dated from today to today plus 365 days, the rule
  behind the screen's ``catalysts_12m`` count, each with its asset, phase and indication
  where the book links them. A value at stake is stated only where the stake engine
  priced the event (``forecast_view.catalyst_stakes``). Nothing is derived for the rest:
  they carry the model's risk-adjusted value of the whole asset, labelled as that, and
  the reason no stake is stated.
- **Competition.** For a company read on the pharma engine, its indications grouped by
  population and ranked by the modelled value attributed to each, then for the first
  five: the landscape's own candidate counts by stage, the shared patient pool and the
  company's share of it. The model values assets, not asset-indication pairs, so value is
  attributed by one stated rule: the indication the model sizes the asset in, else the
  book's lead indication.

Never a cold book. The verdict and the stakes come from the response cache, as the model
block of ``comps_valuation`` does; a body built before the verdict is warm says so
(``complete`` false) and the route keeps it out of the cache. The one slow step left is the
landscape's trial scan, a fraction of a second a group, and it is memoised per population
group against the stamp the response cache uses, since obesity, lung and breast are
shared by most of the pharma engine.

Every null carries a reason in the ``na`` map beside it. One entry covers the nulls that
share its reason: a null ``pool`` covers ``crowding`` and ``company_pool``.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import threading
from collections import OrderedDict

import db
import forecast_view
import indication_mapping as IM
import landscape
import pool_crowding
import response_cache

SCHEMA = 1
WINDOW_DAYS = 365
MAX_CATALYSTS = 60
MAX_INDICATIONS = 5
MAX_OWN_CANDIDATES = 5
REGULATORY_KINDS = ("PDUFA", "regulatory decision", "AdCom", "EMA decision")
VERDICT_PATH = "/companies/{t}/forecast-verdict"
STAKES_PATH = "/companies/{t}/catalysts/stakes"
# Below this share of the pool the claims are noise, above one they exceed the population.
MIN_CLAIMED_SHARE = 0.01
MEMO_MAX = 256

_NCT = re.compile(r"NCT\d{8}")
_LEADING_PHASE = re.compile(r"Phase \d(?:/\d)?")
_MONTH = re.compile(r"\d{4}-\d{2}")
_STAGES = ("marketed", "phase3", "phase2", "other")
_STAGE_ORDER = {stage: i for i, stage in enumerate(_STAGES)}

# {group_key: detail} for one stamp. The detail is everything about a population group
# that does not depend on which company is asking.
_memo_lock = threading.Lock()
_memo: dict = {"stamp": None, "groups": OrderedDict()}


# --- small helpers ---------------------------------------------------------------------
def _num(value):
    """A finite float, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean(obj):
    """Strict JSON: no NaN, no infinity, keys as strings."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if hasattr(obj, "item"):                      # a numpy scalar
        return _clean(obj.item())
    return str(obj)


def _as_date(value):
    if isinstance(value, dt.datetime):
        return value.date()
    if value is None or isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def _cached_verdict(ticker: str):
    return response_cache.cached_json(VERDICT_PATH.format(t=ticker))


def _cached_stakes(ticker: str):
    return response_cache.cached_json(STAKES_PATH.format(t=ticker))


# --- the group memo --------------------------------------------------------------------
def _stamp(db_path) -> tuple:
    """What a group's detail was computed from. The response cache's own stamp, which
    names the default database; a database handed in by path adds its own file times."""
    base = response_cache.stamp()
    if db_path is None:
        return base
    path = str(db_path)
    return base + (path, response_cache._mtime(path), response_cache._mtime(path + "-wal"))


def clear_memo() -> None:
    with _memo_lock:
        _memo["stamp"] = None
        _memo["groups"].clear()


def _memo_get(stamp: tuple, key: str):
    with _memo_lock:
        if _memo["stamp"] != stamp:
            _memo["stamp"] = stamp
            _memo["groups"].clear()
        return _memo["groups"].get(key)


def _memo_put(stamp: tuple, key: str, detail: dict) -> None:
    with _memo_lock:
        # Stored only under the stamp read before it was computed, so a write that lands
        # mid-build leaves nothing behind that passes for current.
        if _memo["stamp"] != stamp:
            return
        groups = _memo["groups"]
        groups[key] = detail
        groups.move_to_end(key)
        while len(groups) > MEMO_MAX:
            groups.popitem(last=False)


# --- the company and its model ---------------------------------------------------------
def _price(conn, company_id: int, today: dt.date):
    """The latest daily close dated on or before ``today``."""
    row = conn.execute(
        """SELECT close, substr(as_of, 1, 10) AS day FROM prices
            WHERE company_id = ? AND interval = '1d' AND close IS NOT NULL
              AND substr(as_of, 1, 10) <= ?
            ORDER BY as_of DESC LIMIT 1""", (company_id, today.isoformat())).fetchone()
    close = _num(row["close"]) if row else None
    return {"close": close, "as_of": row["day"]} if close else None


def _has_book(conn, company) -> bool:
    """Whether any asset the company owns, or is the named partner of, carries
    assumptions."""
    return bool(conn.execute(
        """SELECT EXISTS (SELECT 1 FROM assets a JOIN assumptions s ON s.asset_id = a.id
                           WHERE a.owner_company_id = ?)
               OR EXISTS (SELECT 1 FROM assumptions
                           WHERE key = 'partner_ticker'
                             AND UPPER(COALESCE(text_value, '')) = ?)""",
        (company["id"], company["ticker"].upper())).fetchone()[0])


def _model(conn, company, verdict_for) -> tuple:
    """(state, {asset_id: modelled line with a per-share value}), from a verdict already
    computed. The verdict is never built here: AstraZeneca's alone takes 2.4 seconds."""
    if not _has_book(conn, company):
        return "not_modelled", {}
    verdict = verdict_for(company["ticker"])
    if verdict is None:
        return "not_computed", {}
    if not isinstance(verdict, dict) or not verdict.get("ok"):
        return "failed", {}
    modelled = [m for m in verdict.get("modelled") or [] if isinstance(m, dict)]
    if not modelled:
        return "not_modelled", {}
    lines = {}
    for line in modelled:
        per_share = _num(line.get("per_share"))
        if line.get("asset_id") is not None and per_share is not None:
            lines[line["asset_id"]] = {"per_share": per_share, "pos": _num(line.get("pos")),
                                       "counted": bool(line.get("counted", True))}
    return "modelled", lines


def _outcome_legs(conn) -> set:
    """Assets carrying both outcome probabilities, read as the stake engine reads them:
    asset-level scalars of the base scenario."""
    return {r["asset_id"] for r in conn.execute(
        """SELECT asset_id FROM assumptions
            WHERE key IN ('pos_success', 'pos_failure') AND scenario = 'base'
              AND indication_id IS NULL AND year IS NULL AND value IS NOT NULL
            GROUP BY asset_id HAVING COUNT(DISTINCT key) = 2""")}


# --- catalysts -------------------------------------------------------------------------
def _precision(date: str, confidence) -> str:
    if confidence in ("quarter", "half"):
        return confidence
    return "month" if _MONTH.fullmatch(date or "") else "day"


def _stake_reason(asset, close, lines: dict, legs: set, state: str) -> str:
    if asset is None:
        return "no_asset"
    if not close:
        return "no_price"
    if state == "not_computed":
        return "model_not_computed"
    if asset["id"] not in lines:
        return "not_modelled"
    if asset["id"] not in legs:
        return "no_outcome_legs"
    # Both legs are on file and no stake came back. The stake engine reads a catalyst by
    # the asset its own row names, so an event linked only through its trial is not read.
    return "not_in_stakes"


def _catalyst_rows(conn, company_id: int, today: dt.date, end: dt.date) -> list:
    """Pending catalysts dated inside the window, compared as strings, which is how
    ``screen._catalysts_12m`` counts them: a ``YYYY-MM`` date sorts before every day of
    its month."""
    return conn.execute(
        """SELECT id, asset_id, asset_indication_id, catalyst_type, expected_date,
                  date_confidence, title, is_curated, source_url
             FROM catalysts
            WHERE company_id = ? AND status = 'pending'
              AND expected_date >= ? AND expected_date <= ?
            ORDER BY expected_date, id""",
        (company_id, today.isoformat(), end.isoformat())).fetchall()


def _trial_indication(conn, trial):
    """The first of the trial's own MeSH indications that the book holds."""
    for descriptor in IM.indications_for(trial["conditions"], IM.parse_browse(trial["mesh_terms"])):
        row = conn.execute("SELECT id, name FROM indications WHERE mesh_id = ?",
                           (descriptor["id"],)).fetchone()
        if row:
            return {"id": row["id"], "name": row["name"]}
    return None


def _catalyst(conn, row, lines: dict, priced: dict, legs: set, price, state: str) -> dict:
    found = _NCT.search(row["source_url"] or "")
    nct = found.group(0) if found else None
    trial = conn.execute(
        "SELECT asset_id, phase, conditions, mesh_terms FROM trials WHERE nct_id = ?",
        (nct,)).fetchone() if nct else None

    asset = None
    asset_id = row["asset_id"] or (trial["asset_id"] if trial else None)
    if asset_id:
        a = conn.execute(
            """SELECT id, COALESCE(brand_name, generic_name, internal_code) AS name,
                      is_marketed FROM assets WHERE id = ?""", (asset_id,)).fetchone()
        if a:
            asset = {"id": a["id"], "name": a["name"], "is_marketed": bool(a["is_marketed"])}

    indication = None
    if row["asset_indication_id"]:
        i = conn.execute(
            """SELECT i.id, i.name FROM asset_indications ai
                 JOIN indications i ON i.id = ai.indication_id
                WHERE ai.id = ?""", (row["asset_indication_id"],)).fetchone()
        if i:
            indication = {"id": i["id"], "name": i["name"]}
    if indication is None and trial:
        indication = _trial_indication(conn, trial)

    leading = _LEADING_PHASE.match(row["title"] or "")
    phase = (trial["phase"] if trial and trial["phase"]
             else leading.group(0) if leading else None)

    close = price["close"] if price else None
    na: dict = {}
    if asset is None:
        na["asset"] = "no_asset"
    if indication is None:
        na["indication"] = "no_indication_link"

    # A stake is only ever the stake engine's own figure for this catalyst.
    stake = None
    got = priced.get(row["id"])
    per_share = _num(got.get("per_share")) if got else None
    if per_share is not None and close:
        stake = {"per_share": per_share, "pct_of_price": abs(per_share) / close,
                 "pos_now": _num(got.get("pos_now")),
                 "pos_success": _num(got.get("pos_success")),
                 "pos_failure": _num(got.get("pos_failure")),
                 "economics_share": _num(got.get("share"))}
    else:
        na["stake"] = _stake_reason(asset, close, lines, legs, state)

    # The risk-adjusted value of the whole asset, every indication. Not a stake.
    value = None
    line = lines.get(asset["id"]) if asset else None
    if line and close:
        value = {"per_share": line["per_share"], "pct_of_price": line["per_share"] / close,
                 "pos": line["pos"], "counted": line["counted"]}
    else:
        na["asset_value"] = ("no_asset" if asset is None else "no_price" if not close
                             else "model_not_computed" if state == "not_computed"
                             else "not_modelled")

    return {"id": row["id"], "date": row["expected_date"],
            "date_precision": _precision(row["expected_date"], row["date_confidence"]),
            "date_confidence": row["date_confidence"], "kind": row["catalyst_type"],
            "regulatory": row["catalyst_type"] in REGULATORY_KINDS, "phase": phase,
            "asset": asset, "indication": indication, "title": row["title"], "nct_id": nct,
            "source_url": row["source_url"], "is_curated": bool(row["is_curated"]),
            "stake": stake, "asset_value": value, "na": na}


def _stakes(conn, db_path, company, rows, legs: set, stakes_for):
    """The stakes read already computed, else the stake engine, and that only where it
    could price something: an in-window catalyst whose own row names an asset with both
    outcome legs. For every other company the engine returns nothing but reasons."""
    stakes = stakes_for(company["ticker"])
    if stakes is None and any(r["asset_id"] in legs for r in rows if r["asset_id"]):
        try:
            stakes = forecast_view.catalyst_stakes(db_path, company["ticker"])
        except Exception:                 # no stake is stated, with its reason on the row
            stakes = None
    priced = (stakes or {}).get("priced") if isinstance(stakes, dict) else None
    return {r["id"]: r for r in priced or [] if isinstance(r, dict) and r.get("id") is not None}


def _catalysts(conn, db_path, company, lines, legs, today, end, price, state, stakes_for) -> dict:
    rows = _catalyst_rows(conn, company["id"], today, end)
    priced = _stakes(conn, db_path, company, rows, legs, stakes_for) if rows else {}
    items = [_catalyst(conn, r, lines, priced, legs, price, state) for r in rows]
    return {
        "total": len(items), "sent": min(len(items), MAX_CATALYSTS),
        "counts": {"with_asset": sum(1 for x in items if x["asset"]),
                   "with_indication": sum(1 for x in items if x["indication"]),
                   "with_stake": sum(1 for x in items if x["stake"]),
                   "with_asset_value": sum(1 for x in items if x["asset_value"]),
                   "curated": sum(1 for x in items if x["is_curated"])},
        "items": items[:MAX_CATALYSTS]}


# --- competition -----------------------------------------------------------------------
def _not_covered(reason: str) -> dict:
    return {"covered": False, "reason": reason, "ranked_by": None, "total": 0, "valued": 0,
            "indications": []}


def _stage(is_marketed: bool, phase_here, on_label: bool) -> str:
    """The landscape's stage text as a bucket. A drug sold for something else and
    trialled here counts at the phase it reached here, as the landscape words it."""
    if is_marketed and (on_label or not phase_here):
        return "marketed"
    if phase_here in ("Phase 3", "Phase 2/3"):
        return "phase3"
    if phase_here == "Phase 2":
        return "phase2"
    return "other"


def _by_stage(compounds: list) -> dict:
    out = {stage: 0 for stage in _STAGES}
    for compound in compounds:
        out[compound["stage"]] += 1
    return out


def _compounds(conn, members: list) -> list:
    """One row a compound, as the landscape counts them: a company's brands of one
    molecule are one candidate, two companies' versions stay apart."""
    cands = landscape.candidates(conn, members)
    pharm = landscape._pharmacology(conn, list(cands))
    labelled = landscape.on_label(conn, [a for a, c in cands.items() if c.get("is_marketed")],
                                  [m["name"] for m in members])
    out = []
    for ids in landscape.compound_groups(cands, pharm):
        mine = [cands[a] for a in ids]
        rep = min(ids, key=lambda a: (not cands[a].get("is_marketed"), a))
        phase_here = max((c["phase_here"] for c in mine if c["phase_here"]),
                         key=lambda p: landscape._PHASE_RANK.get(p, -1), default=None)
        merged: dict = {}
        for a in ids:
            for kind, items in (pharm.get(a) or {}).items():
                have = {x["value"] for x in merged.get(kind, [])}
                merged.setdefault(kind, []).extend(x for x in items if x["value"] not in have)
        marketed = any(c.get("is_marketed") for c in mine)
        out.append({"asset_ids": sorted(ids), "ticker": cands[rep]["ticker"],
                    "is_marketed": marketed, "phase_here": phase_here,
                    "name": landscape.compound_name(dict(cands[rep]), merged),
                    "stage": _stage(marketed, phase_here, any(a in labelled for a in ids))})
    return out


def _pool(conn, members: list) -> dict:
    """The shared patient pool of a group: its size, who claims it, what the claims come
    to before and after the population is counted once, and each company's part."""
    pool = landscape._pool(conn, members)
    if not pool:
        return {"pool": None, "crowding": None, "na": {"pool": "no_pool"}, "companies": {},
                "order": [], "total": 0.0}
    tickers: dict = {}
    for member in members:
        claims = pool_crowding.claimants(conn, member["id"])
        if claims:
            tickers = {c["asset_id"]: c["ticker"] for c in claims}
            break
    # Pooled claimants only, each at its own peak year. An asset that draws on a
    # different population than the shared one is modelled alone and rations nobody.
    pooled = {a: v for a, v in (pool.get("assets") or {}).items() if v.get("pooled")}
    companies: dict = {}
    for asset_id, peaks in pooled.items():
        held = companies.setdefault(tickers.get(asset_id),
                                    {"uncrowded": 0.0, "crowded": 0.0, "claimants": 0})
        held["uncrowded"] += peaks["peak_uncrowded"]
        held["crowded"] += peaks["peak_crowded"]
        held["claimants"] += 1
    order = sorted(companies, key=lambda t: (-companies[t]["crowded"], t or ""))
    patients = _num(pool.get("pool"))
    uncrowded, crowded = _num(pool.get("uncrowded_share")), _num(pool.get("crowded_share"))
    na: dict = {}
    crowding = None
    if len(pooled) < 2 or uncrowded is None or crowded is None:
        na["crowding"] = "single_claimant"
    elif not patients:
        na["crowding"] = "flow_pool"
    elif uncrowded > 1.0:
        na["crowding"] = "claims_exceed_pool"
    elif uncrowded < MIN_CLAIMED_SHARE:
        na["crowding"] = "share_under_1pct"
    else:
        crowding = {"uncrowded_share": uncrowded, "crowded_share": crowded,
                    "kept": crowded / uncrowded, "peak_year": pool.get("peak_year")}
    return {"pool": {"patients": patients, "claimants": pool.get("claimants"),
                     "pooled_claimants": len(pooled), "companies": len(companies)},
            "crowding": crowding, "na": na, "companies": companies, "order": order,
            "total": sum(c["crowded"] for c in companies.values())}


def _group(conn, stamp: tuple, key: str, indication_id: int) -> dict:
    """Candidates and pool of one population group, whichever company asks. The trial
    scan inside ``landscape.candidates`` is the cost of this module, so it runs once a
    group for as long as the stamp holds."""
    hit = _memo_get(stamp, key)
    if hit is not None:
        return hit
    members = landscape._members(conn, indication_id)
    detail = {"members": [m["name"] for m in members], "compounds": _compounds(conn, members),
              "pool": _pool(conn, members)}
    _memo_put(stamp, key, detail)
    return detail


def _attribution(conn, counted: list) -> dict:
    """{indication_id: {asset_id}}: where each modelled asset's value counts.

    The model values an asset, not an asset-indication pair. An asset counts in every
    indication the model sizes it in. One the model sizes nowhere (a marketed product
    valued off reported revenue) counts in its lead indication, its own and then its
    molecule's. One with neither counts nowhere. Counting an asset in every indication
    it touches instead ranked Lilly's fatty liver trial at $146 a share."""
    out: dict = {}
    if not counted:
        return out
    marks = ",".join("?" * len(counted))
    sized: dict = {}
    for r in conn.execute(
            f"""SELECT DISTINCT asset_id, indication_id FROM assumptions
                 WHERE indication_id IS NOT NULL AND asset_id IN ({marks})""", counted):
        sized.setdefault(r["asset_id"], set()).add(r["indication_id"])
    for asset_id in counted:
        if asset_id in sized:
            for indication_id in sized[asset_id]:
                out.setdefault(indication_id, set()).add(asset_id)
            continue
        lead = conn.execute(
            """SELECT ai.indication_id FROM asset_indications ai
                WHERE ai.is_lead = 1
                  AND ai.asset_id IN (?, (SELECT molecule_id FROM assets WHERE id = ?))
                ORDER BY (ai.asset_id = ?) DESC, ai.id LIMIT 1""",
            (asset_id, asset_id, asset_id)).fetchone()
        if lead:
            out.setdefault(lead["indication_id"], set()).add(asset_id)
    return out


def _company_pool(pool: dict, ticker: str):
    """The company's part of a shared pool, or None where it has no pooled claimant."""
    mine = pool["companies"].get(ticker)
    total = pool["total"]
    patients = (pool["pool"] or {}).get("patients")
    if not mine or mine["uncrowded"] <= 0 or total <= 0 or not patients:
        return None
    order, companies = pool["order"], pool["companies"]
    return {"claimants": mine["claimants"], "keeps": mine["crowded"] / mine["uncrowded"],
            "share_of_claims": mine["crowded"] / total,
            "share_of_pool": mine["crowded"] / patients,
            "rank": order.index(ticker) + 1, "of_companies": len(order),
            "leader": {"ticker": order[0],
                       "share_of_claims": companies[order[0]]["crowded"] / total}}


def _own_candidates(own: list, attributed: set, lines: dict) -> list:
    out = []
    for compound in own:
        values = [lines[a]["per_share"] for a in compound["asset_ids"] if a in attributed]
        out.append({"name": compound["name"], "stage": compound["stage"],
                    "phase_here": compound["phase_here"],
                    "is_marketed": compound["is_marketed"], "asset_ids": compound["asset_ids"],
                    "per_share": sum(values) if values else None, "attributed": bool(values)})
    out.sort(key=lambda c: (-(c["per_share"] or 0.0), _STAGE_ORDER[c["stage"]], c["name"] or ""))
    return out


def _competition(conn, db_path, company, lines: dict, state: str, price, stamp: tuple) -> dict:
    ticker = company["ticker"]
    # The landscape and the pool model reach the pharma engine only.
    if company["id"] not in landscape._big_pharma_ids(conn):
        return _not_covered("not_big_pharma")
    groups: dict = {}
    for entry in landscape.indications(db_path):
        if ticker in entry["tickers"]:
            groups.setdefault(pool_crowding.group_of(conn, entry["id"]), []).append(entry)
    if not groups:
        return _not_covered("no_indications")

    attribution = _attribution(conn, sorted(a for a, line in lines.items() if line["counted"]))
    ranked = []
    for key, entries in groups.items():
        # One population written under several names is one row, under its most
        # contested name.
        rep = max(entries, key=lambda e: (e["companies"], e["assets"], -e["id"]))
        attributed: set = set()
        for member in landscape._members(conn, rep["id"]):
            attributed |= attribution.get(member["id"], set())
        ranked.append({"key": key, "rep": rep, "attributed": attributed,
                       "value": (sum(lines[a]["per_share"] for a in attributed)
                                 if attributed else None)})
    ranked.sort(key=lambda r: (r["value"] is None, -(r["value"] or 0.0),
                               -r["rep"]["companies"], -r["rep"]["assets"], r["rep"]["name"]))
    valued = [r for r in ranked if r["value"] is not None]
    close = price["close"] if price else None

    rows = []
    for r in (valued or ranked)[:MAX_INDICATIONS]:
        detail = _group(conn, stamp, r["key"], r["rep"]["id"])
        own = [c for c in detail["compounds"] if c["ticker"] == ticker]
        rivals = [c for c in detail["compounds"] if c["ticker"] != ticker]
        pool = detail["pool"]
        na = dict(pool["na"])
        company_pool = None
        if pool["crowding"]:
            company_pool = _company_pool(pool, ticker)
            if company_pool is None:
                na["company_pool"] = "no_claimant"
        if r["value"] is None:
            na["value"] = ("model_not_computed" if state == "not_computed"
                           else "no_attributed_asset" if state == "modelled"
                           else "not_modelled")
        elif not close:
            na["value_pct"] = "no_price"
        candidates = _own_candidates(own, r["attributed"], lines)
        rows.append({
            "indication": {"id": r["rep"]["id"], "name": r["rep"]["name"],
                           "members": list(detail["members"])},
            "value": {"per_share": r["value"],
                      "pct_of_price": (r["value"] / close
                                       if r["value"] is not None and close else None),
                      "assets": len(r["attributed"])},
            "own": {"n": len(own), "by_stage": _by_stage(own),
                    "candidates": candidates[:MAX_OWN_CANDIDATES],
                    "more": max(0, len(candidates) - MAX_OWN_CANDIDATES)},
            "rivals": {"n": len(rivals), "companies": len({c["ticker"] for c in rivals}),
                       "by_stage": _by_stage(rivals)},
            "pool": dict(pool["pool"]) if pool["pool"] else None,
            "crowding": dict(pool["crowding"]) if pool["crowding"] else None,
            "company_pool": company_pool, "na": na})
    return {"covered": True, "reason": None,
            "ranked_by": "model_value" if valued else "contest",
            "total": len(ranked), "valued": len(valued), "indications": rows}


# --- the payload -----------------------------------------------------------------------
def build(ticker, db_path=None, today=None, verdict_for=None, stakes_for=None):
    """One company's catalysts of the next twelve months and the competition in its most
    valuable indications, or None for an unknown ticker.

    ``verdict_for(ticker)`` and ``stakes_for(ticker)`` hand back the forecast verdict and
    the catalyst stakes already computed; they default to the response cache. ``today``
    defaults to the calendar date; tests pass a fixed one.
    """
    today = _as_date(today) or dt.date.today()
    end = today + dt.timedelta(days=WINDOW_DAYS)
    verdict_for = verdict_for or _cached_verdict
    stakes_for = stakes_for or _cached_stakes
    stamp = _stamp(db_path)               # read before anything is computed from it
    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id, ticker, name FROM companies WHERE UPPER(ticker) = ?",
            (str(ticker or "").strip().upper(),)).fetchone()
        if company is None:
            return None
        company = dict(company)
        state, lines = _model(conn, company, verdict_for)
        price = _price(conn, company["id"], today)
        payload = {
            "schema": SCHEMA, "ticker": company["ticker"], "generated_at": generated_at,
            "today": today.isoformat(),
            "window": {"from": today.isoformat(), "to": end.isoformat()},
            "complete": state != "not_computed",
            "incomplete_reason": "model_not_computed" if state == "not_computed" else None,
            "price": price,
            "model": {"state": state, "assets": len(lines)},
            "catalysts": _catalysts(conn, db_path, company, lines, _outcome_legs(conn), today,
                                    end, price, state, stakes_for),
            "competition": _competition(conn, db_path, company, lines, state, price, stamp),
        }
    finally:
        conn.close()
    return _clean(payload)
