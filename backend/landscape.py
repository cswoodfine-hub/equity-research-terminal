"""Every candidate for one indication, compared whatever its modality or mechanism.

The asset-indication pair is the unit of analysis (CLAUDE.md), and every other view in
the terminal reads it one company at a time. An analyst asking who wins in obesity or in
first-line lung cancer needs the other axis: every drug aimed at the disease, from every
company, side by side on what it is, what its trials showed and what the model says it
is worth.

Three layers, each only what a free source states:

- **Commercial.** Where the book models the drug: success probability, peak revenue and
  year, value per share, and, where several claim one patient pool, each one's share of
  it before and after the pool is counted once (``pool_crowding``).
- **Scientific.** Modality, mechanism, target, class, route and boxed warning
  (``asset_pharmacology``, from ChEMBL and the openFDA label).
- **Clinical.** The results the sponsors posted to ClinicalTrials.gov: every arm of every
  primary endpoint against its placebo arm, grouped where two trials measured the same
  thing in the same unit, and the safety record per drug against placebo in the same
  trials (serious adverse events, withdrawals for adverse events, deaths, the commonest
  events).

A drug joins the landscape three ways, and each row says which: the pipeline records it
in the indication, the model sizes a pool for it there, or one of its trials names the
indication. The last is how an incumbent enters: most marketed products have no running
trial and so no pipeline row, but their completed trials name the disease.

Nothing is computed across trials beyond placing numbers side by side. Two trials of one
endpoint differ in population, duration and background therapy, and the rows carry the
trial, its size and its time point so a reader can see how far the comparison stretches.

Big pharma owners only for now, the same rule as the engine split.
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict

import db
import forecast_view
import indication_mapping as IM
import pool_crowding

LATE = ("Phase 2", "Phase 2/3", "Phase 3")
_PHASE_RANK = {"Early Phase 1": 0, "Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3,
               "Phase 2/3": 4, "Phase 3": 5, "Phase 4": 6}

# A condition a completed trial names reaches an indication when this share of the
# indication's own words is in it. Stricter than the pipeline's half, because a completed
# trial carries no MeSH descriptor to anchor on: three quarters keeps "Arthritis,
# Psoriatic" out of rheumatoid arthritis while "Type 2 Diabetes" still meets "Diabetes
# Mellitus, Type 2".
CONDITION_MATCH = 0.75
# One word for a malignancy however the sponsor spells it, so "Breast Cancer" meets
# "Breast Neoplasms" and "Non-Small Cell Lung Cancer" meets "Carcinoma, Non-Small-Cell Lung".
_SYNONYMS = {"cancer": "neoplasm", "cancers": "neoplasm", "carcinoma": "neoplasm",
             "carcinomas": "neoplasm", "neoplasms": "neoplasm", "tumor": "neoplasm",
             "tumors": "neoplasm", "tumour": "neoplasm", "tumours": "neoplasm",
             "mellitus": None}
_PLACEBO = re.compile(r"\b(placebo|vehicle|sham|dummy)\b", re.I)
_VERDICT_TTL_S = 15 * 60
_verdicts: dict = {}
_big: dict = {}


# --- words and matching -------------------------------------------------------------
def _words(text: str) -> set:
    out = set()
    for w in IM.tokens(text):
        w = _SYNONYMS.get(w, w)
        if w:
            out.add(w)
    return out


def condition_matches(condition: str, indication: str) -> bool:
    """Whether a sponsor's free-text condition names this indication."""
    if not IM.is_indication(condition):
        return False
    ind, cond = _words(indication), _words(condition)
    if not ind or not cond:
        return False
    nums_i, nums_c = IM._numbers(ind), IM._numbers(cond)
    if nums_i and nums_c and not (nums_i & nums_c):
        return False            # Type 1 is not Type 2
    return len(ind & cond) / len(ind) >= CONDITION_MATCH


def is_placebo(title: str | None, names=()) -> bool:
    """A placebo, vehicle or sham arm. One that also names the drug is the drug given
    with a matching dummy (a double-dummy design), so it is the drug's arm, not placebo;
    "Placebo + Metformin" is still placebo, on background therapy."""
    text = (title or "").lower()
    return bool(_PLACEBO.search(text)) and not any(
        n.lower() in text for n in names if len(n) >= 4)


def weeks_of(*texts) -> float | None:
    """The time point of an endpoint in weeks, from its title or time frame. The last one
    named, since "baseline to week 52" is measured at week 52."""
    found = []
    for text in texts:
        for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*[- ]?\s*(weeks?|months?|days?|years?)",
                                  text or "", re.I):
            found.append(float(n) * {"w": 1, "m": 4.345, "d": 1 / 7, "y": 52.18}[unit[0].lower()])
        for unit, n in re.findall(r"\b(week|month|day|year)\s*(\d+(?:\.\d+)?)", text or "", re.I):
            found.append(float(n) * {"w": 1, "m": 4.345, "d": 1 / 7, "y": 52.18}[unit[0].lower()])
    return round(max(found), 1) if found else None


_TIME_WORDS = re.compile(r"\b(at|by|through|to|from|over|up)?\s*(week|month|day|year)s?\s*\d+"
                         r"|\b\d+\s*(week|month|day|year)s?\b", re.I)
_STEMS = {"percentage": "percent", "%": "percent", "participants": "participant",
          "patients": "participant", "subjects": "participant", "change": "change",
          "changes": "change"}


def endpoint_key(title: str, unit: str | None) -> str:
    """Two trials' endpoints are the same measure when their titles, with the time point
    and word order taken out, share every word, and their unit agrees."""
    core = _TIME_WORDS.sub(" ", (title or "").lower())
    words = sorted({_STEMS.get(w, w) for w in re.split(r"[^a-z0-9%]+", core)
                    if w and w not in IM._STOPWORDS and not w.isdigit()})
    unit_words = sorted({_STEMS.get(w, w) for w in re.split(r"[^a-z0-9%]+", (unit or "").lower())
                         if w})
    return " ".join(words) + " | " + " ".join(unit_words)


# --- the universe it reads ----------------------------------------------------------
def _big_pharma_ids(conn) -> set:
    now = time.time()
    if _big.get("at", 0) > now - _VERDICT_TTL_S:
        return _big["ids"]
    import pos_granular
    ids = {r["id"] for r in conn.execute("SELECT id FROM companies")
           if pos_granular.big_pharma(conn, r["id"])}
    _big.update(at=now, ids=ids)
    return ids


def _members(conn, indication_id: int) -> list[dict]:
    """The indication and every name its population is grouped under."""
    group = pool_crowding.group_of(conn, indication_id)
    rows = conn.execute(
        """SELECT i.id, i.name FROM indication_groups g
             JOIN indications i ON i.name = g.indication_name WHERE g.group_key = ?""",
        (group,)).fetchall()
    own = conn.execute("SELECT id, name FROM indications WHERE id = ?",
                       (indication_id,)).fetchone()
    out = {r["id"]: r["name"] for r in rows}
    if own:
        out[own["id"]] = own["name"]
    return [{"id": k, "name": v} for k, v in out.items()]


def indications(db_path=None, limit: int = 250) -> list[dict]:
    """The indications a landscape can be drawn for: at least one big pharma candidate
    that is marketed or in Phase 2 and later, most contested first."""
    conn = db.get_connection(db_path)
    try:
        big = _big_pharma_ids(conn)
        if not big:
            return []
        marks = ",".join("?" * len(big))
        rows = conn.execute(
            f"""SELECT i.id, i.name, i.therapeutic_area,
                       COUNT(DISTINCT a.id) AS assets,
                       COUNT(DISTINCT a.owner_company_id) AS companies,
                       MAX(CASE ai.phase WHEN 'Phase 3' THEN 3 WHEN 'Phase 2/3' THEN 2
                                         WHEN 'Phase 2' THEN 1 ELSE 0 END) AS top
                  FROM asset_indications ai
                  JOIN assets a ON a.id = ai.asset_id
                  JOIN indications i ON i.id = ai.indication_id
                 WHERE a.owner_company_id IN ({marks})
                   AND a.id NOT IN (SELECT asset_id FROM retired_programmes)
                   AND (a.is_marketed = 1 OR ai.phase IN ('Phase 2','Phase 2/3','Phase 3'))
                 GROUP BY i.id
                 ORDER BY companies DESC, assets DESC, i.name
                 LIMIT ?""", (*big, limit)).fetchall()
        return [dict(r) for r in rows if IM.is_indication(r["name"])]
    finally:
        conn.close()


# --- candidates ---------------------------------------------------------------------
def _names(asset: dict) -> list[str]:
    names = [asset.get("brand_name"), asset.get("generic_name"), asset.get("internal_code")]
    try:
        names += json.loads(asset.get("active_ingredients") or "[]")
    except (TypeError, ValueError):
        pass
    return [n for n in dict.fromkeys(n.strip() for n in names if n and n.strip())
            if not re.fullmatch(r"(NDA|BLA|ANDA)\s*\d+", n, re.I)]


def candidates(conn, members: list[dict]) -> dict:
    """{asset_id: candidate} for every big pharma asset linked to these indications, with
    how it was linked and the trials that link it."""
    big = _big_pharma_ids(conn)
    ids = [m["id"] for m in members]
    names = [m["name"] for m in members]
    if not big or not ids:
        return {}
    bm, im = ",".join("?" * len(big)), ",".join("?" * len(ids))
    found: dict = {}

    def add(asset_id, how, phase=None):
        c = found.setdefault(asset_id, {"asset_id": asset_id, "linked_by": [],
                                        "phase_here": None, "trials": {}})
        if how not in c["linked_by"]:
            c["linked_by"].append(how)
        if phase and _PHASE_RANK.get(phase, -1) > _PHASE_RANK.get(c["phase_here"] or "", -1):
            c["phase_here"] = phase

    retired = f"AND a.id NOT IN (SELECT asset_id FROM retired_programmes)"
    for r in conn.execute(
            f"""SELECT ai.asset_id, ai.phase FROM asset_indications ai
                  JOIN assets a ON a.id = ai.asset_id
                 WHERE ai.indication_id IN ({im}) AND a.owner_company_id IN ({bm}) {retired}""",
            (*ids, *big)):
        add(r["asset_id"], "pipeline", r["phase"])
    for r in conn.execute(
            f"""SELECT DISTINCT s.asset_id FROM assumptions s JOIN assets a ON a.id = s.asset_id
                 WHERE s.indication_id IN ({im}) AND a.owner_company_id IN ({bm}) {retired}""",
            (*ids, *big)):
        add(r["asset_id"], "model")

    # Trials, running and completed, whose conditions name the indication. Running ones
    # carry MeSH and so already sit in asset_indications; this is how a marketed product
    # with only completed studies arrives, and how every study is attached to its drug.
    for table, done in (("trials", "primary_completion_date"),
                        ("completed_trials", "completion_date")):
        status = "overall_status" if table == "trials" else "'COMPLETED'"
        for r in conn.execute(
                f"""SELECT t.nct_id, t.asset_id, t.phase, t.title, t.conditions, t.enrollment,
                           {status} AS status, t.{done} AS done
                      FROM {table} t JOIN assets a ON a.id = t.asset_id
                     WHERE a.owner_company_id IN ({bm}) {retired}""", tuple(big)):
            try:
                conds = json.loads(r["conditions"] or "[]")
            except (TypeError, ValueError):
                conds = []
            # The disease the trial is about, not one it lists in passing: Invokana's
            # and Exforge's studies list obesity among their conditions without being
            # obesity trials. The first condition a sponsor names, or the title.
            lead = conds[:1]
            if not (any(condition_matches(c, n) for c in lead for n in names)
                    or any(condition_matches(r["title"] or "", n) for n in names)):
                continue
            if r["phase"] not in LATE and r["asset_id"] not in found:
                continue            # an early study alone does not make a candidate
            add(r["asset_id"], "trial", r["phase"] if r["phase"] in _PHASE_RANK else None)
            found[r["asset_id"]]["trials"][r["nct_id"]] = {
                "nct_id": r["nct_id"], "phase": r["phase"], "title": r["title"],
                "status": r["status"], "enrollment": r["enrollment"], "completion": r["done"]}

    if not found:
        return {}
    am = ",".join("?" * len(found))
    for r in conn.execute(
            f"""SELECT a.id, a.generic_name, a.brand_name, a.internal_code, a.active_ingredients,
                       a.modality, a.is_marketed, c.ticker, c.name AS company
                  FROM assets a JOIN companies c ON c.id = a.owner_company_id
                 WHERE a.id IN ({am})""", tuple(found)):
        c = found[r["id"]]
        c.update({"name": r["brand_name"] or r["generic_name"] or r["internal_code"],
                  "generic": r["generic_name"], "ticker": r["ticker"],
                  "company": r["company"], "is_marketed": bool(r["is_marketed"]),
                  "modality": r["modality"], "_names": _names(dict(r))})
    # Where nothing on this indication stages the asset (a seed alone links it), its
    # furthest phase anywhere, marked as such.
    for aid, c in found.items():
        if c["phase_here"] is None and not c.get("is_marketed"):
            top = conn.execute(
                "SELECT phase FROM asset_indications WHERE asset_id = ?", (aid,)).fetchall()
            best = max((r["phase"] for r in top), key=lambda p: _PHASE_RANK.get(p, -1),
                       default=None)
            if best:
                c["phase_here"] = best
                c["phase_elsewhere"] = True
    # An asset kept only by early studies and no late phase anywhere is not a candidate.
    return {k: v for k, v in found.items()
            if v.get("is_marketed") or v["phase_here"] in LATE or "model" in v["linked_by"]}


def _pharmacology(conn, ids: list[int]) -> dict:
    out: dict = defaultdict(lambda: defaultdict(list))
    if not ids:
        return out
    for r in conn.execute(
            f"SELECT asset_id, kind, value, detail, source, source_url FROM asset_pharmacology"
            f" WHERE asset_id IN ({','.join('?' * len(ids))}) ORDER BY kind, value", ids):
        out[r["asset_id"]][r["kind"]].append(
            {"value": r["value"], "detail": r["detail"], "source": r["source"],
             "url": r["source_url"]})
    return out


def _model_lines(db_path, tickers: set) -> dict:
    """{asset_id: the book's modelled line}, from each company's verdict, cached."""
    out = {}
    now = time.time()
    for t in tickers:
        hit = _verdicts.get(t)
        if not hit or hit[0] < now - _VERDICT_TTL_S:
            try:
                v = forecast_view.company_verdict(db_path, t) or {}
            except Exception:
                v = {}
            hit = (now, {m["asset_id"]: m for m in v.get("modelled") or []},
                   ((v.get("sotp") or {}).get("fx") or {}).get("currency") or "USD")
            _verdicts[t] = hit
        for aid, line in hit[1].items():
            out[aid] = {**line, "currency": hit[2]}
    return out


def _pool(conn, members: list[dict]) -> dict:
    """The patient pool the modelled claimants share, and each one's peak share of the
    patients it starts, before and after the pool is counted once."""
    for m in members:
        claims = pool_crowding.claimants(conn, m["id"])
        if not claims:
            continue
        starts = [c["start"] for c in claims if c["start"]]
        first = int(min(starts)) if starts else 0
        last = int(max(starts)) if starts else 0
        got = pool_crowding.solve(claims, years=(last - first) + 22, first_year=first)
        if not got.get("assets"):
            continue
        summary = pool_crowding.summary(got) if len(claims) > 1 else {}
        return {"pool": got.get("pool"), "indication": m["name"],
                "claimants": len(claims),
                "assets": {a["asset_id"]: {"peak_uncrowded": max(a["uncrowded"] or [0]),
                                           "peak_crowded": max(a["crowded"] or [0]),
                                           "ratio": a["ratio"], "pooled": a["pooled"]}
                           for a in got["assets"]},
                "peak_year": summary.get("peak_year"),
                "uncrowded_share": summary.get("uncrowded_share"),
                "crowded_share": summary.get("crowded_share")}
    return {}


# --- clinical ------------------------------------------------------------------------
def _arm_is_drug(arm_title: str, arm_desc: str, names: list[str]) -> bool:
    text = f"{arm_title or ''} {arm_desc or ''}".lower()
    return any(n.lower() in text for n in names if len(n) >= 4)


def _results(conn, ncts: list[str]) -> tuple[dict, dict, dict, dict]:
    if not ncts:
        return {}, {}, {}, {}
    marks = ",".join("?" * len(ncts))
    outcomes = defaultdict(list)
    for r in conn.execute(
            f"SELECT * FROM trial_result_outcomes WHERE nct_id IN ({marks})"
            f" AND outcome_type = 'PRIMARY' ORDER BY nct_id, outcome_index, id", ncts):
        outcomes[(r["nct_id"], r["outcome_index"])].append(dict(r))
    analyses = defaultdict(list)
    for r in conn.execute(f"SELECT * FROM trial_result_analyses WHERE nct_id IN ({marks})", ncts):
        analyses[(r["nct_id"], r["outcome_index"])].append(dict(r))
    safety = defaultdict(list)
    for r in conn.execute(f"SELECT * FROM trial_result_safety WHERE nct_id IN ({marks})", ncts):
        safety[r["nct_id"]].append(dict(r))
    events = defaultdict(list)
    for r in conn.execute(f"SELECT * FROM trial_result_events WHERE nct_id IN ({marks})", ncts):
        events[r["nct_id"]].append(dict(r))
    return outcomes, analyses, safety, events


def _analysis_for(analyses: list, arm: str, placebo: str | None) -> dict | None:
    for a in analyses:
        try:
            groups = set(json.loads(a["group_ids"] or "[]"))
        except (TypeError, ValueError):
            continue
        if arm in groups and (placebo is None or placebo in groups) and len(groups) == 2:
            return a
    return None


def endpoints(cands: dict, outcomes: dict, analyses: dict) -> list[dict]:
    """Every primary endpoint of every candidate's trials, per arm, against placebo,
    grouped by measure. Groups more than one drug shares come first."""
    trial_owner = {nct: aid for aid, c in cands.items() for nct in c["trials"]}
    groups: dict = {}
    for (nct, index), rows in outcomes.items():
        aid = trial_owner.get(nct)
        if aid is None:
            continue
        c = cands[aid]
        first = rows[0]
        key = endpoint_key(first["title"], first["unit"])
        g = groups.setdefault(key, {"key": key, "title": first["title"], "unit": first["unit"],
                                    "param_type": first["param_type"], "rows": [],
                                    "assets": set()})
        by_cat = defaultdict(list)
        for r in rows:
            by_cat[r["category"]].append(r)
        for cat, arms in by_cat.items():
            placebo = next((a for a in arms if is_placebo(a["group_title"], c["_names"])), None)
            for arm in arms:
                if placebo is not None and arm is placebo:
                    continue
                mine = _arm_is_drug(arm["group_title"], arm["group_description"], c["_names"])
                delta = (arm["value"] - placebo["value"]
                         if placebo and arm["value"] is not None and placebo["value"] is not None
                         else None)
                stat = _analysis_for(analyses.get((nct, index), []), arm["group_id"],
                                     placebo["group_id"] if placebo else None)
                g["rows"].append({
                    "asset_id": aid, "name": c["name"], "ticker": c["ticker"],
                    "nct_id": nct, "phase": c["trials"][nct]["phase"],
                    "weeks": weeks_of(first["title"], first["time_frame"]),
                    "time_frame": first["time_frame"], "category": cat,
                    "arm": arm["group_title"], "arm_is_drug": mine,
                    "n": arm["n_analysed"], "value": arm["value"],
                    "value_text": arm["value_text"], "spread": arm["spread"],
                    "dispersion": first["dispersion_type"],
                    "placebo": placebo["value"] if placebo else None,
                    "placebo_n": placebo["n_analysed"] if placebo else None,
                    "delta": delta,
                    "p_value": stat["p_value"] if stat else None,
                    "estimate": stat["param_value"] if stat else None,
                    "ci": ([stat["ci_lower"], stat["ci_upper"]]
                           if stat and stat["ci_lower"] is not None else None)})
                g["assets"].add(aid)
    out = []
    for g in groups.values():
        g["n_assets"] = len(g["assets"])
        g["assets"] = sorted(g["assets"])
        g["rows"].sort(key=lambda r: (r["name"] or "", r["nct_id"], r["arm"] or ""))
        out.append(g)
    out.sort(key=lambda g: (-g["n_assets"], -len(g["rows"]), g["title"] or ""))
    return out


def _rate(affected, at_risk):
    return (affected / at_risk) if (affected is not None and at_risk) else None


def safety(cands: dict, safety_rows: dict, events: dict, pharm: dict) -> list[dict]:
    """Per candidate, its arms and the placebo arms of the same trials pooled: serious
    adverse events, withdrawals for adverse events and deaths over the number at risk, and
    the commonest events with the placebo rate beside each."""
    out = []
    for aid, c in cands.items():
        drug = {"serious": [0, 0], "withdrawn": [0, 0], "deaths": [0, 0], "any": [0, 0]}
        placebo = {k: [0, 0] for k in drug}
        drug_groups, placebo_groups = defaultdict(set), defaultdict(set)
        trials = 0
        for nct in c["trials"]:
            rows = safety_rows.get(nct) or []
            if not rows:
                continue
            trials += 1
            named = [r for r in rows if _arm_is_drug(r["group_title"], "", c["_names"])]
            for r in rows:
                if r["group_title"] and r["group_title"].strip().lower() == "total":
                    continue
                if is_placebo(r["group_title"], c["_names"]):
                    bucket, gset = placebo, placebo_groups
                elif (named and r in named) or (not named):
                    bucket, gset = drug, drug_groups
                else:
                    continue            # an active comparator's arm is not this drug
                gset[nct].add(r["group_id"])
                at_risk = r["serious_at_risk"] or r["other_at_risk"]
                for key, aff, risk in (("serious", r["serious_affected"], r["serious_at_risk"]),
                                       ("deaths", r["deaths_affected"], r["deaths_at_risk"]),
                                       ("withdrawn", r["withdrawn_ae"], at_risk),
                                       ("any", r["other_affected"], r["other_at_risk"])):
                    if aff is not None and risk:
                        bucket[key][0] += aff
                        bucket[key][1] += risk
        if not trials:
            p = pharm.get(aid) or {}
            if p.get("boxed_warning"):
                out.append({"asset_id": aid, "name": c["name"], "ticker": c["ticker"],
                            "trials": 0, "boxed_warning": p["boxed_warning"][0]["value"]})
            continue
        terms: dict = {}
        for nct in c["trials"]:
            for e in events.get(nct) or []:
                side = ("drug" if e["group_id"] in drug_groups.get(nct, set()) else
                        "placebo" if e["group_id"] in placebo_groups.get(nct, set()) else None)
                if side is None or e["at_risk"] is None:
                    continue
                t = terms.setdefault(e["term"], {"term": e["term"], "serious": e["serious"],
                                                 "organ_system": e["organ_system"],
                                                 "drug": [0, 0], "placebo": [0, 0]})
                t[side][0] += e["affected"] or 0
                t[side][1] += e["at_risk"]
        top = sorted((t for t in terms.values() if t["drug"][1]),
                     key=lambda t: -(t["drug"][0] / t["drug"][1]))[:6]
        p = pharm.get(aid) or {}
        out.append({
            "asset_id": aid, "name": c["name"], "ticker": c["ticker"], "trials": trials,
            "participants": drug["serious"][1] or drug["any"][1],
            "placebo_participants": placebo["serious"][1] or placebo["any"][1],
            **{f"{k}_rate": _rate(*drug[k]) for k in drug},
            **{f"placebo_{k}_rate": _rate(*placebo[k]) for k in placebo},
            "top_events": [{"term": t["term"], "serious": bool(t["serious"]),
                            "organ_system": t["organ_system"],
                            "rate": _rate(*t["drug"]), "placebo_rate": _rate(*t["placebo"])}
                           for t in top],
            "boxed_warning": (p.get("boxed_warning") or [{}])[0].get("value")})
    out.sort(key=lambda s: (-(s.get("trials") or 0), s["name"] or ""))
    return out


def _readout_quotes(conn, cands: dict) -> dict:
    """Press-release readouts that name the drug, newest first, three per drug."""
    out: dict = defaultdict(list)
    rows = conn.execute(
        "SELECT r.company_id, r.drug, r.phase, r.outcome, r.event_date, r.quote, r.source_url,"
        " c.ticker FROM trial_readouts r JOIN companies c ON c.id = r.company_id"
        " WHERE r.quote IS NOT NULL ORDER BY r.event_date DESC").fetchall()
    for aid, cand in cands.items():
        names = [n.lower() for n in cand["_names"] if len(n) >= 4]
        for r in rows:
            if r["ticker"] != cand["ticker"]:
                continue
            text = f"{r['drug'] or ''} {r['quote'] or ''}".lower()
            if any(n in text for n in names):
                out[aid].append({"date": r["event_date"], "outcome": r["outcome"],
                                 "phase": r["phase"], "quote": r["quote"],
                                 "url": r["source_url"]})
                if len(out[aid]) >= 3:
                    break
    return out


# --- the view ------------------------------------------------------------------------
def landscape(db_path, indication_id: int) -> dict | None:
    conn = db.get_connection(db_path)
    try:
        members = _members(conn, indication_id)
        if not members:
            return None
        own = next(m for m in members if m["id"] == indication_id)
        cands = candidates(conn, members)
        ids = list(cands)
        pharm = _pharmacology(conn, ids)
        pool = _pool(conn, members)
        ncts = sorted({n for c in cands.values() for n in c["trials"]})
        have = {r["nct_id"] for r in conn.execute(
            f"SELECT nct_id FROM trial_result_fetches WHERE has_results = 1 AND nct_id IN"
            f" ({','.join('?' * len(ncts)) or 'NULL'})", ncts)} if ncts else set()
        outcomes, analyses, safety_rows, events = _results(conn, sorted(have))
        quotes = _readout_quotes(conn, cands)
    finally:
        conn.close()
    lines = _model_lines(db_path, {c["ticker"] for c in cands.values()})

    rows = []
    for aid, c in cands.items():
        p = pharm.get(aid) or {}
        line = lines.get(aid) or {}
        years = [y for y, v in zip(line.get("years") or [], line.get("revenue_share") or [])
                 if v and v > 0]
        pooled = (pool.get("assets") or {}).get(aid)
        rows.append({
            "asset_id": aid, "name": c["name"], "generic": c.get("generic"),
            "ticker": c["ticker"], "company": c["company"],
            "stage": "Marketed" if c["is_marketed"] else (c["phase_here"] or "not staged"),
            "phase_here": c["phase_here"], "is_marketed": c["is_marketed"],
            "phase_elsewhere": bool(c.get("phase_elsewhere")),
            "linked_by": c["linked_by"], "modality": c.get("modality"),
            "molecule_type": [x["value"] for x in p.get("molecule_type", [])],
            "mechanisms": [{"value": x["value"], "action": x["detail"]}
                           for x in p.get("mechanism", [])],
            "targets": sorted({x["value"] for x in p.get("target", [])}),
            "classes": [x["value"] for x in p.get("epc_class", [])],
            "route": [x["value"] for x in p.get("route", [])],
            "boxed_warning": (p.get("boxed_warning") or [{}])[0].get("value"),
            "pharmacology_source": sorted({x["source"] for k in p for x in p[k]}),
            "trials": sorted(c["trials"].values(), key=lambda t: t["completion"] or "",
                             reverse=True),
            "with_results": sum(1 for n in c["trials"] if n in have),
            "model": ({"per_share": line.get("per_share"), "pos": line.get("pos"),
                       "peak_revenue": line.get("peak_revenue"),
                       "peak_year": line.get("peak_year"),
                       "first_year": years[0] if years else None,
                       "counted": line.get("counted", True),
                       "currency": line.get("currency")} if line else None),
            "pool": pooled,
            "readouts": quotes.get(aid, []),
        })
    rank = {"Marketed": 9}
    rows.sort(key=lambda r: (-(rank.get(r["stage"]) or _PHASE_RANK.get(r["stage"], -1)),
                             -((r["model"] or {}).get("per_share") or 0), r["name"] or ""))
    return {
        "ok": True,
        "indication": {"id": own["id"], "name": own["name"],
                       "members": [m["name"] for m in members]},
        "candidates": rows,
        "companies": sorted({r["ticker"] for r in rows}),
        "pool": {k: v for k, v in pool.items() if k != "assets"} if pool else None,
        "endpoints": endpoints(cands, outcomes, analyses),
        "safety": safety(cands, safety_rows, events, pharm),
        "coverage": {
            "candidates": len(rows),
            "with_mechanism": sum(1 for r in rows if r["mechanisms"]),
            "with_model": sum(1 for r in rows if r["model"]),
            "trials": len(ncts), "trials_with_results": len(have)},
    }
