"""The Catalysts tab's one read: what can move the share, assembled for the redesigned tab.

The redesigned tab (AstraZeneca first) draws every pipeline line at its next gate with what
passing and missing are worth a share, the company's dated events on one time axis by
therapy area, the selected gate's legs, dates, cost and launch floor, the next events, a
risk register and why the rest carry no price. Each part has a module that owns it; this
assembles them so the page makes one read rather than a dozen, as universe_command does for
the Universe tab:

- the stakes, priced and unpriced with their reasons (forecast_view.catalyst_stakes);
- every modelled line with its next gate (forecast_view.company_verdict);
- the launch floor in full for each unmarketed asset (launch_timing.for_company);
- the cost to reach each gate and what it nets (development.for_company, build 1);
- the change feed's slips and regulatory items, the signed readouts, the exclusivities,
  the programmes' studies and the trial rows behind every study named;
- the competition in the company's indications (comps_context), for the crowding card.

The forecast, the stakes and the development view are read from the API's response cache
where they are held, so a warm page costs no model run; outside the API, or cold, they are
computed. The scorecard's exclusivity losses (the share of revenue a loss carries) are
read from the cache only: the whole-universe valuation is never built for this page, and a
body built before it is warm is marked incomplete so it is not held.

Two layers, so the rules can be tested without a book:

- ``read_sources`` reads every input from the modules and the database.
- ``assemble`` is pure: sources in, payload out. Nothing in it reads a clock, a file or
  the network.

Nothing is estimated here. A field a source does not carry is null, and the page says
"no free data" rather than drawing it as zero.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re

import db

SCHEMA = 1
# The change feed's window, as GET /changes reads it by default.
FEED_DAYS = 30
# "AZN trial NCT07775404: primary completion slips 2027-06-04 -> 2028-04-06", and the
# same line without "slips" for a move earlier or by a day or two.
_MOVE_RE = re.compile(r"trial (NCT\d{8}): primary completion (?:slips )?"
                      r"(\d{4}-\d{2}-\d{2}) -> (\d{4}-\d{2}-\d{2})")
_PHASE_RE = re.compile(r"^(Phase [0-9/]+),")
# What a regulatory headline reports, first match wins. Read off the words, never
# guessed: a headline that names none of these is "regulatory".
REG_KINDS = (
    (re.compile(r"\bpriority review\b", re.I), "US Priority Review"),
    (re.compile(r"\bbreakthrough therapy\b", re.I), "Breakthrough designation"),
    (re.compile(r"\bCHMP\b"), "CHMP opinion"),
    (re.compile(r"\b(?:accepted|acceptance)\b", re.I), "filing accepted"),
    (re.compile(r"\bcomplete response\b", re.I), "complete response letter"),
)
# The fields of a trial row the page reads.
TRIAL_FIELDS = ("nct_id", "title", "phase", "overall_status", "enrollment", "conditions",
                "primary_completion_date", "primary_completion_type", "start_date",
                "asset_id")
# What the card and the dialog read of a development row (build 1): the gate's cost and
# net, the ladder after later trial costs and the studies behind the cost.
DEV_FIELDS = ("ok", "reason", "why", "currency", "paid_note", "tax_basis", "gate",
              "ladder", "stages", "outside", "sources")
# What the page reads of a priced stake row: the row as the At stake list draws it, so
# the resolve control and its two-click arm read the same fields there and here.
STAKE_FIELDS = ("id", "catalyst_type", "expected_date", "date_confidence", "title",
                "description", "source_url", "asset_id", "asset_name", "priced",
                "legs_basis", "pos_now", "pos_success", "pos_failure", "swing", "share",
                "share_swing", "per_share", "gate", "gate_label", "held", "basis",
                "gate_note", "resolvable", "resolve_note")


# --------------------------------------------------------------------------- helpers
def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def phase_of(title: str | None, trial: dict | None = None) -> str | None:
    """The phase a catalyst names: "Phase 3" from "Phase 3, Truqap", else the trial's."""
    m = _PHASE_RE.match(str(title or ""))
    if m:
        return m.group(1)
    phase = (trial or {}).get("phase")
    return phase if phase and str(phase).startswith("Phase") else None


def moves(changes: list) -> dict:
    """{nct: [move, ...]} newest first: every primary-completion move in the feed, a slip
    (later) or a pull (earlier), with the day it was seen."""
    out: dict = {}
    for c in changes or []:
        if c.get("change_type") not in ("date_slip", "date_change"):
            continue
        m = _MOVE_RE.search(c.get("headline") or "")
        if not m:
            continue
        old, new = _date(m.group(2)), _date(m.group(3))
        if not old or not new:
            continue
        out.setdefault(m.group(1), []).append({
            "nct": m.group(1), "old": old.isoformat(), "new": new.isoformat(),
            "days": (new - old).days, "seen": str(c.get("detected_at") or "")[:10] or None,
            "kind": c.get("change_type")})
    for rows in out.values():
        rows.sort(key=lambda r: r["seen"] or "", reverse=True)
    return out


def reg_kind(headline: str | None) -> str:
    for pattern, kind in REG_KINDS:
        if pattern.search(headline or ""):
            return kind
    return "regulatory"


def _names(assets: list) -> list:
    """(lower-case name, asset_id, display name) for every brand and generic name of the
    company's assets, longest first, so "efzimfotase alfa" wins over "alfa"."""
    out = []
    for a in assets or []:
        shown = a.get("brand_name") or a.get("generic_name")
        for name in (a.get("brand_name"), a.get("generic_name")):
            if name and len(name) >= 4:
                out.append((name.lower(), a["id"], shown))
    return sorted(out, key=lambda t: -len(t[0]))


def match_asset(text: str | None, names: list):
    """(asset_id, name) of the first asset a text names as a whole word, or (None, None)."""
    low = (text or "").lower()
    for name, aid, shown in names:
        if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", low):
            return aid, shown
    return None, None


def readout_asset(drug: str | None, names: list):
    """The asset a signed readout names: "sonesitatug vedotin (Sone-Ve)" is the asset
    whose generic name is "sonesitatug vedotin"."""
    key = str(drug or "").lower().split(" (")[0].strip()
    for name, aid, shown in names:
        if name == key:
            return aid, shown
    return match_asset(key, names)


def _trial(row: dict | None) -> dict | None:
    if not row:
        return None
    return {k: row.get(k) for k in TRIAL_FIELDS}


# ----------------------------------------------------------------------- the sources
def _held(path: str):
    """A read the API last computed, or None. Never builds anything."""
    import response_cache
    return response_cache.cached_json(path)


def _trials(conn, ncts) -> dict:
    ncts = sorted({n for n in ncts if n})
    out = {}
    for i in range(0, len(ncts), 400):
        chunk = ncts[i:i + 400]
        marks = ",".join("?" * len(chunk))
        for r in conn.execute(
                f"""SELECT nct_id, title, phase, overall_status, enrollment, conditions,
                           primary_completion_date, primary_completion_type, start_date,
                           asset_id
                      FROM trials WHERE nct_id IN ({marks})""", chunk):
            row = dict(r)
            try:
                row["conditions"] = json.loads(row["conditions"] or "[]")
            except (TypeError, ValueError):
                row["conditions"] = [row["conditions"]] if row["conditions"] else []
            out[row["nct_id"]] = row
    return out


def read_sources(ticker: str, today: dt.date | None = None, db_path=None) -> dict:
    """Every input the page draws, read from the modules that own it."""
    import comps_context
    import development
    import forecast_view
    import launch_timing
    import loe
    import pipeline
    import product_areas
    import trial_readouts
    import whatchanged

    today = today or dt.date.today()
    t = ticker.upper()
    src: dict = {"today": today.isoformat(), "ticker": t}
    src["stakes"] = (_held(f"/companies/{t}/catalysts/stakes")
                     or forecast_view.catalyst_stakes(db_path, t))
    src["verdict"] = (_held(f"/companies/{t}/forecast-verdict")
                      or forecast_view.company_verdict(db_path, t))
    try:
        src["development"] = (_held(f"/companies/{t}/development")
                              or development.for_company(db_path, t, today))
    except Exception as exc:  # noqa: BLE001  the cost is one row of the card, never the page
        src["development"], src["development_error"] = None, str(exc)
    valuation = _held("/comps/valuation") or {}
    src["scorecard_held"] = bool(valuation)
    src["losses"] = ((((valuation.get("scorecard") or {}).get("companies") or {})
                      .get(t) or {}).get("exclusivity_losses") or [])
    verdict, stakes = src["verdict"], src["stakes"]
    try:
        context = comps_context.build(t, db_path, today,
                                      verdict_for=lambda _t: verdict,
                                      stakes_for=lambda _t: stakes)
    except Exception:  # noqa: BLE001  the crowding card is one card, never the page
        context = None
    src["competition"] = (context or {}).get("competition") or {}
    src["changes"] = whatchanged.build_feed(db_path, days=FEED_DAYS, ticker=t)
    src["readouts"] = trial_readouts.recent(db_path, t)
    src["exclusivities"] = loe.loe_detail(db_path, t) or []
    src["programmes"] = pipeline.programmes(db_path, t) or []
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id, ticker, name FROM companies WHERE ticker = ?",
                               (t,)).fetchone()
        src["company"] = dict(company) if company else {"ticker": t}
        src["launch"] = (launch_timing.for_company(conn, company["id"], today)
                         if company else [])
        src["currency"] = (forecast_view.price_unit_rate(conn, company["id"])["currency"]
                           if company else "USD")
        src["assets"] = [dict(r) for r in conn.execute(
            """SELECT id, brand_name, generic_name, modality, is_marketed FROM assets
                WHERE owner_company_id = ?""", (company["id"],))] if company else []
        rows = (stakes or {}).get("priced", []) + (stakes or {}).get("unpriced", [])
        ncts = [r.get("description") for r in rows]
        for m in (verdict or {}).get("modelled") or []:
            g = m.get("gate") or {}
            ncts.append((g.get("trial") or {}).get("nct_id"))
            ncts += (g.get("held") or {}).get("ncts") or []
        ncts += list(moves(src["changes"]))
        for p in src["programmes"]:
            ncts += [s.get("nct_id") for s in p.get("studies") or []]
        src["trials"] = _trials(conn, [n for n in ncts if str(n or "").startswith("NCT")])
        ids = {r.get("asset_id") for r in rows}
        ids |= {m.get("asset_id") for m in (verdict or {}).get("modelled") or []}
        ids |= {a.get("asset_id") for a in src["exclusivities"]}
        ids |= {r.get("asset_id") for r in src["trials"].values()}
        src["areas"] = {aid: product_areas.area_for(conn, aid) for aid in ids if aid}
        known = {a["id"] for a in src["assets"]}
        extra = sorted(i for i in ids if i and i not in known)
        if extra:
            marks = ",".join("?" * len(extra))
            src["assets"] += [dict(r) for r in conn.execute(
                f"""SELECT id, brand_name, generic_name, modality, is_marketed FROM assets
                     WHERE id IN ({marks})""", extra)]
    finally:
        conn.close()
    return src


# --------------------------------------------------------------------------- assemble
def _dev_by_asset(dev: dict) -> dict:
    """The development view per asset, trimmed to what the card and the dialog read: the
    gate's cost and net, the ladder, the studies, or the refusal and why."""
    out = {}
    for part in ("failing", "rows", "uncosted", "refused"):
        for r in (dev or {}).get(part) or []:
            if not isinstance(r, dict) or r.get("asset_id") is None:
                continue
            out[r["asset_id"]] = {k: r.get(k) for k in DEV_FIELDS}
    return out


def _studies(ncts, trials: dict) -> list:
    return [_trial(trials[n]) for n in ncts or [] if n in trials]


def _open_studies(programme: dict | None, gate: str, trials: dict) -> list:
    """Where no gate study is matched: the asset's open studies in the gate's phase, as
    the registry lists them, so the card can still show what is running."""
    want = {"p3_to_nda": ("Phase 3", "Phase 2/3"), "p2_to_p3": ("Phase 2", "Phase 1/2")}
    phases = want.get(gate)
    if not phases or not programme:
        return []
    out = []
    for s in programme.get("studies") or []:
        if s.get("phase") in phases and s.get("status") not in (
                "Completed", "Terminated", "Withdrawn", "Suspended"):
            row = trials.get(s.get("nct_id")) or {}
            out.append({**(_trial(row) or {}), "nct_id": s.get("nct_id"),
                        "phase": s.get("phase"), "overall_status": s.get("status"),
                        "enrollment": s.get("enrollment"),
                        "primary_completion_date": (row.get("primary_completion_date")
                                                    or s.get("due"))})
    return out


def _gate_rows(src: dict, priced_by_asset: dict, by_nct: dict, areas: dict,
               trials: dict) -> list:
    """Every modelled line with a priced next gate: the legs a share, the gate study and
    its move, the launch floor, the cost to reach it and the stake row on the calendar."""
    verdict = src.get("verdict") or {}
    launch = {a.get("asset_id"): a for a in src.get("launch") or []}
    dev = _dev_by_asset(src.get("development") or {})
    programmes = {p.get("asset_id"): p for p in src.get("programmes") or []}
    rows = []
    for m in verdict.get("modelled") or []:
        g = m.get("gate")
        if not isinstance(g, dict) or _num(g.get("per_share_now")) is None:
            continue
        aid = m["asset_id"]
        lt = launch.get(aid) or m.get("launch") or {}
        trial = g.get("trial") or {}
        nct = trial.get("nct_id")
        held = g.get("held") if isinstance(g.get("held"), dict) else None
        success, failure = _num(g.get("per_share_success")), _num(g.get("per_share_failure"))
        # An FDA decision with no date on file sits at the earliest approval the launch
        # floor allows, drawn as "no earlier than", never as a date.
        floor = (lt.get("decision_date")
                 if g.get("gate") == "nda_to_approval" and not g.get("date") else None)
        move = (by_nct.get(nct) or [None])[0] if nct else None
        stake = priced_by_asset.get(aid)
        detail = _trial(trials.get(nct)) if nct else None
        rows.append({
            "asset_id": aid, "name": m.get("name"), "area": areas.get(aid),
            "gate": g.get("gate"), "label": g.get("label"), "date": g.get("date"),
            "date_basis": g.get("date_basis"), "due": bool(g.get("due")), "why": g.get("why"),
            "floor": floor,
            "trial": ({**trial, **{k: v for k, v in (detail or {}).items()
                                    if k != "phase" and v is not None}} if nct else None),
            "now": _num(g.get("per_share_now")), "success": success, "failure": failure,
            "swing": (success - failure) if None not in (success, failure) else None,
            "held": held, "held_studies": _studies((held or {}).get("ncts"), trials),
            "open_studies": ([] if nct else _open_studies(programmes.get(aid), g.get("gate"),
                                                          trials)),
            "p_gate": _num(g.get("p_gate")), "p_gate_published": _num(g.get("p_gate_published")),
            "pos_now": _num(g.get("pos_now")), "pos_success": _num(g.get("pos_success")),
            "pos_failure": _num(g.get("pos_failure")), "evidence": g.get("evidence") or {},
            "basis": g.get("basis") or "", "band": g.get("band"),
            "legs_basis": g.get("legs_basis"), "stated_pos": g.get("stated_pos"),
            "rnpv_now": _num(g.get("rnpv_now")), "rnpv_success": _num(g.get("rnpv_success")),
            "rnpv_failure": _num(g.get("rnpv_failure")),
            # The verdict's gate as served and the launch floor in full: what the Next gate
            # block's builders (_gate_summary and its rows) read on the Forecast tab.
            "verdict_gate": g,
            "launch": lt,
            "stake": ({k: stake.get(k) for k in STAKE_FIELDS} if stake else None),
            "move": move,
            "model": {"per_share": _num(m.get("per_share")),
                      "peak_revenue": _num(m.get("peak_revenue")),
                      "peak_year": m.get("peak_year"), "loe_year": m.get("loe_year"),
                      "is_marketed": bool(m.get("is_marketed")), "pos": _num(m.get("pos"))},
            "development": dev.get(aid),
        })
    return rows


def _events(src: dict, lines: dict, gated: set, by_nct: dict, areas: dict, trials: dict,
            asset_rows: dict) -> list:
    """Every dated catalyst on the calendar, priced or not, with its trial and its move."""
    stakes = src.get("stakes") or {}
    priced_ids = {r.get("id") for r in stakes.get("priced") or []}
    out = []
    for r in (stakes.get("priced") or []) + (stakes.get("unpriced") or []):
        aid = r.get("asset_id")
        nct = r.get("description") if str(r.get("description") or "").startswith("NCT") else None
        trial = _trial(trials.get(nct)) if nct else None
        line = lines.get(aid) or {}
        priced = r.get("id") in priced_ids and r.get("priced") is not False
        slip = next((mv for mv in by_nct.get(nct) or [] if mv["days"] > 0), None) if nct else None
        marketed = line.get("is_marketed")
        if marketed is None and aid in asset_rows:
            marketed = bool(asset_rows[aid].get("is_marketed"))
        out.append({
            "id": r.get("id"), "date": r.get("expected_date"),
            "confidence": r.get("date_confidence"), "curated": bool(r.get("is_curated")),
            "kind": r.get("catalyst_type"), "asset_id": aid, "asset": r.get("asset_name"),
            "area": areas.get(aid), "phase": phase_of(r.get("title"), trial),
            "title": r.get("title"), "nct": nct, "url": r.get("source_url"),
            "priced": bool(priced), "per_share": _num(r.get("per_share")) if priced else None,
            "gate_asset": aid if aid in gated else None,
            "reason": None if priced else r.get("reason"),
            "why": None if priced else r.get("why"),
            "line_value": _num(line.get("per_share")), "marketed": marketed,
            "trial": trial, "slip": slip})
    out.sort(key=lambda e: (e["date"] or "9999", e["id"] or 0))
    return out


def _cliffs(src: dict, lines_by_id: dict, today: dt.date, asset_rows: dict) -> tuple:
    """The exclusivity losses on file with the model's value on the line, and the model's
    value a share by the year its LOE falls, for the marketed lines it counts."""
    losses = {}
    for x in src.get("losses") or []:
        if isinstance(x, dict):
            losses[x.get("asset_id")] = x
            losses[(x.get("asset") or "").lower()] = x
    cliffs = []
    for a in src.get("exclusivities") or []:
        name = a.get("brand_name") or a.get("generic_name")
        line = lines_by_id.get(a.get("asset_id")) or {}
        loss = losses.get(a.get("asset_id")) or losses.get((name or "").lower()) or {}
        day = _date(a.get("loe"))
        cliffs.append({
            "asset_id": a.get("asset_id"), "asset": name, "loe": a.get("loe"),
            "loe_basis": a.get("loe_basis"),
            "modality": (asset_rows.get(a.get("asset_id")) or {}).get("modality")
            or a.get("modality"),
            "share_of_revenue": _num(loss.get("share_of_revenue")), "fy": loss.get("fy"),
            "model_per_share": _num(line.get("per_share")),
            "model_loe_year": line.get("loe_year"),
            "passed": bool(day and day < today)})
    cliffs.sort(key=lambda c: c["loe"] or "9999")
    by_year: dict = {}
    no_loe = []
    for line in lines_by_id.values():
        if not line.get("is_marketed") or not line.get("counted", True):
            continue
        value = _num(line.get("per_share"))
        if value is None:
            continue
        year = line.get("loe_year")
        if not year:
            no_loe.append([line.get("name"), value])
            continue
        b = by_year.setdefault(str(year), {"per_share": 0.0, "products": []})
        b["per_share"] += value
        modality = (asset_rows.get(line["asset_id"]) or {}).get("modality")
        b["products"].append([line.get("name"), value, modality])
    for b in by_year.values():
        b["products"].sort(key=lambda p: -p[1])
    no_loe.sort(key=lambda p: -p[1])
    return cliffs, dict(sorted(by_year.items())), no_loe


def _slips(by_nct: dict, trials: dict, names_by_id: dict, gate_by_nct: dict) -> list:
    """Every primary-completion slip in the feed, the one on a priced gate first."""
    out = []
    for nct, rows in by_nct.items():
        for mv in rows:
            if mv["kind"] != "date_slip" or mv["days"] <= 0:
                continue
            t = trials.get(nct) or {}
            gate = gate_by_nct.get(nct)
            out.append({**mv, "asset_id": t.get("asset_id"),
                        "asset": (gate or {}).get("name") or names_by_id.get(t.get("asset_id")),
                        "phase": t.get("phase"), "enrollment": t.get("enrollment"),
                        "gate_asset": (gate or {}).get("asset_id"),
                        "gate_swing": (gate or {}).get("swing")})
    out.sort(key=lambda s: (-(s["gate_swing"] or 0), -s["days"]))
    return out


def _crowding(competition: dict) -> dict | None:
    """The indication where the company's model value is largest among those whose pool
    the model calls crowded, with the company's place in it."""
    best = None
    for ind in (competition or {}).get("indications") or []:
        cp = ind.get("company_pool")
        value = _num((ind.get("value") or {}).get("per_share"))
        if not cp or value is None:
            continue
        if best is None or value > best["value_per_share"]:
            ids = sorted({a for c in (ind.get("own") or {}).get("candidates") or []
                          for a in c.get("asset_ids") or []})
            best = {"indication": (ind.get("indication") or {}).get("name"),
                    "value_per_share": value,
                    "pct_of_price": _num((ind.get("value") or {}).get("pct_of_price")),
                    "pool": {k: (ind.get("pool") or {}).get(k)
                             for k in ("patients", "claimants", "companies")},
                    "company_pool": cp, "asset_ids": ids}
    return best


def assemble(src: dict) -> dict:
    """The payload, from the sources alone."""
    today = _date(src.get("today")) or dt.date(1970, 1, 1)
    ticker = src.get("ticker")
    verdict = src.get("verdict") or {}
    stakes = src.get("stakes") or {}
    trials = src.get("trials") or {}
    areas = {}
    for k, v in (src.get("areas") or {}).items():
        try:
            areas[int(k)] = v
        except (TypeError, ValueError):
            continue
    asset_rows = {a["id"]: a for a in src.get("assets") or [] if a.get("id") is not None}
    names = _names(list(asset_rows.values()))
    names_by_id = {aid: (a.get("brand_name") or a.get("generic_name"))
                   for aid, a in asset_rows.items()}
    lines = {m["asset_id"]: m for m in verdict.get("modelled") or []
             if isinstance(m, dict) and m.get("asset_id") is not None}
    by_nct = moves(src.get("changes"))
    priced_by_asset = {}
    for p in stakes.get("priced") or []:
        aid = p.get("asset_id")
        if aid is not None and (aid not in priced_by_asset
                                or abs(p.get("per_share") or 0)
                                > abs(priced_by_asset[aid].get("per_share") or 0)):
            priced_by_asset[aid] = p
    gates = _gate_rows(src, priced_by_asset, by_nct, areas, trials)
    gated = {g["asset_id"] for g in gates}
    gate_by_nct = {(g.get("trial") or {}).get("nct_id"): g for g in gates
                   if (g.get("trial") or {}).get("nct_id")}
    events = _events(src, lines, gated, by_nct, areas, trials, asset_rows)
    cliffs, loe_by_year, no_loe = _cliffs(src, lines, today, asset_rows)
    readouts = []
    for r in src.get("readouts") or []:
        aid, shown = readout_asset(r.get("drug"), names)
        readouts.append({**{k: r.get(k) for k in ("drug", "phase", "outcome", "event_date",
                                                  "quote")},
                         "asset_id": aid, "asset": shown, "area": areas.get(aid)})
    regulatory = []
    for c in src.get("changes") or []:
        if c.get("change_type") != "press_regulatory":
            continue
        head = re.sub(rf"^{re.escape(ticker or '')}\s+", "", c.get("headline") or "")
        aid, shown = match_asset(head, names)
        regulatory.append({"date": str(c.get("detected_at") or "")[:10] or None,
                           "kind": reg_kind(head), "asset_id": aid, "asset": shown,
                           "headline": head, "url": c.get("url")})
    reasons: dict = {}
    for u in stakes.get("unpriced") or []:
        key = u.get("reason") or "unknown"
        reasons[key] = reasons.get(key, 0) + 1
    ok = bool(verdict.get("ok")) and bool(stakes)
    complete = ok and bool(src.get("scorecard_held"))
    return {
        "schema": SCHEMA, "ticker": ticker,
        "name": (src.get("company") or {}).get("name"),
        "today": today.isoformat(),
        "complete": complete,
        "incomplete_reason": (None if complete else
                              "model_not_read" if not ok else "scorecard_not_warm"),
        "currency": src.get("currency") or "USD",
        "close": _num(verdict.get("close")), "close_date": verdict.get("close_date"),
        "model_ok": ok,
        "development_error": src.get("development_error"),
        "gates": gates, "events": events, "cliffs": cliffs, "loe_by_year": loe_by_year,
        "no_loe": no_loe, "slips": _slips(by_nct, trials, names_by_id, gate_by_nct),
        "readouts": readouts, "regulatory": regulatory,
        "crowding": _crowding(src.get("competition") or {}),
        "unpriced_reasons": reasons,
    }


def build(ticker: str, today: dt.date | None = None, db_path=None) -> dict | None:
    """The payload for one company, or None for a ticker the book does not hold."""
    ticker = (ticker or "").upper()
    conn = db.get_connection(db_path)
    try:
        known = conn.execute("SELECT 1 FROM companies WHERE ticker = ?", (ticker,)).fetchone()
    finally:
        conn.close()
    if not known:
        return None
    src = read_sources(ticker, today=today, db_path=db_path)
    return json.loads(json.dumps(assemble(src), default=str),
                      parse_constant=lambda _c: None)
