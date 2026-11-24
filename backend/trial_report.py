"""One completed study, read from what its sponsor posted: a scorecard, a summary of the
results in words, and the points a reader should weigh before leaning on them.

The Portfolio tab opens this when a completed study is clicked. Every figure is the
registry's own (``trial_result_*``, written by ``fetchers/trial_results.py``) or a
sentence a filing or a release carried (``readout_reports``, ``trial_readouts``). Nothing
is estimated: a study with no posted results says so and gives what the registry and the
company said instead, and an arm the registry leaves blank stays blank.

The scorecard is five reading rules, each named with the figures it read, not a verdict
on the drug. Which arm is the drug's and which is its comparator is decided by the rules
the Comps clinical scorecard uses (``landscape.comparator``), so a study reads the same
way in both places.
"""

from __future__ import annotations

import datetime as dt
import json

import db
import landscape
import meta_stats

# A p-value at or under this is read as significant, as the sponsor's own analyses state it.
ALPHA = 0.05
# A difference in serious adverse events this many points worse than the comparator is a
# safety point to weigh; at or under the comparator's rate it is not.
SAFETY_POINTS = 5.0
SMALL_STUDY = 100
LARGE_STUDY = 300
EVENTS_KEPT = 6
RATIO_WORDS = ("ratio",)
# What a study the results fetcher has never asked reads as. The fetcher asks the registry
# for Phase 2 and later studies only, so a Phase 1 or Phase 4 study, or a late one it has
# not reached yet, is not known to have nothing posted: it is unread.
NOT_FETCHED = ("Not fetched: the book reads posted results for Phase 2 and later studies "
               "and has not asked the registry about this one. Its registry page may "
               "hold results.")


def _pct(affected, at_risk):
    if affected is None or not at_risk:
        return None
    return affected / at_risk * 100


def _month(text) -> str:
    try:
        return dt.date.fromisoformat(str(text)[:10]).strftime("%b %Y")
    except (TypeError, ValueError):
        return str(text or "")


def _months_between(a, b):
    try:
        da, dbb = dt.date.fromisoformat(str(a)[:10]), dt.date.fromisoformat(str(b)[:10])
    except (TypeError, ValueError):
        try:
            da = dt.date.fromisoformat(str(a)[:7] + "-01")
            dbb = dt.date.fromisoformat(str(b)[:7] + "-01")
        except (TypeError, ValueError):
            return None
    return (dbb.year - da.year) * 12 + dbb.month - da.month


def _names(conn, asset_id) -> list:
    if asset_id is None:
        return []
    row = conn.execute("SELECT brand_name, generic_name, internal_code FROM assets"
                       " WHERE id = ?", (asset_id,)).fetchone()
    return [n for n in (row["brand_name"], row["generic_name"], row["internal_code"])
            if n] if row else []


def _arms(outcome_rows: list, safety_rows: list) -> list:
    """Each arm once, in the registry's order, with its title and description."""
    seen, out = set(), []
    for r in list(outcome_rows) + list(safety_rows):
        gid = r.get("group_id")
        if gid in seen:
            continue
        seen.add(gid)
        out.append({"group_id": gid, "group_title": r.get("group_title"),
                    "group_description": r.get("group_description")})
    return out


def _roles(arms: list, names: list) -> dict:
    """{group id: role}: "placebo", "control" or "comparator" for an arm the drug is read
    against (every placebo arm, where a study runs one in each cohort), "drug" for an arm
    that names the drug, "other" for the rest. With no arm naming the drug, every arm but
    the comparators is taken as the drug's. The registry numbers the arms of its efficacy
    and its safety tables apart, so each set is read on its own."""
    ident = landscape.drug_identity(names)
    ref, kind = landscape.comparator(arms, names) if names else (None, None)
    roles = {}
    for a in arms:
        title = a.get("group_title")
        if ref is not None and a["group_id"] == ref["group_id"]:
            roles[a["group_id"]] = kind
        elif landscape.is_placebo(title, names):
            # A study of two cohorts has a placebo arm in each.
            roles[a["group_id"]] = "placebo"
        elif landscape._is_control_arm(title, names):
            roles[a["group_id"]] = "control"
        elif landscape.mentions_drug(title, ident):
            roles[a["group_id"]] = "drug"
        else:
            roles[a["group_id"]] = "other"
    if "drug" not in roles.values():
        for gid, role in roles.items():
            if role == "other":
                roles[gid] = "drug"
    return roles


REF_ROLES = ("placebo", "control", "comparator")


def _read(a: dict, groups: list, against: bool) -> dict:
    p = meta_stats.parse_p(a.get("p_value"))
    return {"method": a.get("method"), "param_type": a.get("param_type"),
            "value": a.get("param_value"), "ci_pct": a.get("ci_pct"),
            "lo": a.get("ci_lower"), "hi": a.get("ci_upper"),
            "p_value": a.get("p_value"), "p": p[0] if p else None,
            "p_kind": p[1] if p else None, "groups": groups,
            "against_comparator": against}


def _comparisons(analyses: list, roles: dict) -> list:
    """Every analysis of one drug arm against one comparator arm, in the registry's order;
    where there is none, the first analysis posted of any arms."""
    out, first = [], None
    for a in analyses:
        try:
            groups = json.loads(a.get("group_ids") or "[]")
        except (TypeError, ValueError):
            continue
        if first is None:
            first = _read(a, groups, False)
        kinds = sorted(roles.get(g) or "" for g in groups)
        if len(groups) == 2 and "drug" in kinds and any(k in REF_ROLES for k in kinds):
            out.append(_read(a, groups, True))
    return out or ([first] if first else [])


def _lead(comps: list) -> dict | None:
    """The comparison the card leads on: the one with the smallest p-value posted, else the
    first. Every comparison is listed beside it, so a dose that missed is not hidden."""
    with_p = [c for c in comps if c.get("p") is not None]
    if with_p:
        return min(with_p, key=lambda c: (c["p"], c["p_kind"] != "below"))
    return comps[0] if comps else None


def significant(comp: dict | None):
    """True, False, or None where the posted p-value cannot say."""
    if not comp or comp.get("p") is None:
        return None
    p, kind = comp["p"], comp["p_kind"]
    if kind == "below":
        return True if p <= ALPHA else None
    if kind == "above":
        return False if p >= ALPHA else None
    return p <= ALPHA


def _null(param_type) -> float:
    text = str(param_type or "").lower()
    return 1.0 if any(w in text for w in RATIO_WORDS) else 0.0


def excludes_null(comp: dict | None):
    if not comp or comp.get("lo") is None or comp.get("hi") is None:
        return None
    null = _null(comp.get("param_type"))
    return not (comp["lo"] <= null <= comp["hi"])


def _num(v, places: int = 2) -> str:
    if v is None:
        return "no free data"
    text = f"{abs(v):,.{places}f}".rstrip("0").rstrip(".") if places else f"{abs(v):,.0f}"
    return ("−" if v < 0 else "") + text


def _value_text(row: dict) -> str:
    if row.get("value") is None:
        return row.get("value_text") or "not posted"
    return _num(row["value"])


# --- the scorecard -------------------------------------------------------------------------
def _card(primary: list, comp: dict | None, comps: list, safety: list, study: dict,
          roles: dict, has_results: bool, fetched: bool = True) -> list:
    """Five rows, each {k, verdict, tone, text}: the primary endpoint, the size of the
    effect, serious adverse events, stopping for adverse events, and the evidence the study
    is. Tone is "good", "bad" or "neutral" by the rule named in the row."""
    rows = []
    if not fetched:
        rows.append({"k": "Primary endpoint", "verdict": "results not fetched",
                     "tone": "neutral", "text": NOT_FETCHED})
    elif not has_results:
        rows.append({"k": "Primary endpoint", "verdict": "no results posted", "tone": "neutral",
                     "text": "The sponsor has not posted results to the registry."})
    else:
        sig = significant(comp)
        p_text = f"p {comp['p_value']}" if comp and comp.get("p_value") else ""
        tested = [c for c in comps if significant(c) is not None]
        hits = [c for c in tested if significant(c)]
        spans = [c for c in comps if excludes_null(c) is not None]
        clear = [c for c in spans if excludes_null(c)]
        if comps and not any(c.get("p_value") for c in comps) and spans:
            # No p-value posted (an estimation or Bayesian analysis): read by its interval.
            rows.append({"k": "Primary endpoint",
                         "verdict": (f"interval clear of no effect in {len(clear)} of "
                                     f"{len(spans)}" if len(spans) > 1 else
                                     "interval clear of no effect" if clear else
                                     "interval spans no effect"),
                         "tone": ("good" if len(clear) == len(spans) else
                                  "bad" if not clear else "neutral"),
                         "text": "No p-value is posted, so the comparison is read by whether "
                                 "its interval leaves out no effect."})
        elif len(tested) > 1 and hits and len(hits) < len(tested):
            rows.append({"k": "Primary endpoint",
                         "verdict": f"significant in {len(hits)} of {len(tested)} comparisons",
                         "tone": "neutral",
                         "text": "Each drug arm against its comparator: "
                                 + "; ".join(f"p {c['p_value']}" for c in tested) + "."})
        elif comp is None:
            rows.append({"k": "Primary endpoint", "verdict": "no test posted", "tone": "neutral",
                         "text": "The arms are posted without a statistical comparison."})
        elif sig is True:
            rows.append({"k": "Primary endpoint", "verdict": "significant", "tone": "good",
                         "text": f"The sponsor's analysis gives {p_text}, at or under {ALPHA}."})
        elif sig is False:
            rows.append({"k": "Primary endpoint", "verdict": "not significant", "tone": "bad",
                         "text": f"The sponsor's analysis gives {p_text}, above {ALPHA}."})
        else:
            rows.append({"k": "Primary endpoint", "verdict": "unclear", "tone": "neutral",
                         "text": "A comparison is posted, but its p-value does not say "
                                 "which side of " + str(ALPHA) + " it falls."})
    if comp and comp.get("value") is not None:
        ex = excludes_null(comp)
        ci = (f", {int(comp['ci_pct'] or 95)}% interval {_num(comp['lo'])} to {_num(comp['hi'])}"
              if comp.get("lo") is not None and comp.get("hi") is not None else "")
        rows.append({"k": "Size of effect",
                     "verdict": ("interval clear of no effect" if ex else
                                 "interval spans no effect" if ex is False else "no interval"),
                     "tone": "good" if ex else "bad" if ex is False else "neutral",
                     "text": f"{comp.get('param_type') or 'Estimate'} {_num(comp['value'])}{ci}."})
    else:
        rows.append({"k": "Size of effect", "verdict": "not posted", "tone": "neutral",
                     "text": "No estimate of the difference between arms is posted."})
    drug = [s for s in safety if s["role"] == "drug" and s["serious_pct"] is not None]
    ref = [s for s in safety if s["role"] in REF_ROLES and s["serious_pct"] is not None]
    if drug and ref:
        d = max(s["serious_pct"] for s in drug)
        r = ref[0]["serious_pct"]
        gap = d - r
        rows.append({"k": "Serious adverse events",
                     "verdict": f"{'+' if gap >= 0 else '−'}{abs(gap):.1f} points against "
                                f"{ref[0]['role']}",
                     "tone": "bad" if gap >= SAFETY_POINTS else "good" if gap <= 0 else "neutral",
                     "text": f"{d:.1f}% on the drug (highest arm) against {r:.1f}% on "
                             f"{ref[0]['group_title']}. Worse by {SAFETY_POINTS:.0f} points or "
                             "more reads red; at or under the comparator reads green."})
    elif drug:
        d = max(s["serious_pct"] for s in drug)
        rows.append({"k": "Serious adverse events", "verdict": f"{d:.1f}% on the drug",
                     "tone": "neutral", "text": "No comparator arm to read the rate against."})
    else:
        rows.append({"k": "Serious adverse events", "verdict": "not posted", "tone": "neutral",
                     "text": "No safety table is posted."})
    wd = [s for s in safety if s["role"] == "drug" and s["withdrawn_pct"] is not None]
    wr = [s for s in safety if s["role"] in REF_ROLES and s["withdrawn_pct"] is not None]
    if wd:
        d = max(s["withdrawn_pct"] for s in wd)
        if wr:
            r = wr[0]["withdrawn_pct"]
            rows.append({"k": "Stopped for adverse events",
                         "verdict": f"{d:.1f}% against {r:.1f}%",
                         "tone": "bad" if d - r >= SAFETY_POINTS else "good" if d <= r else "neutral",
                         "text": "Participants the flow records as withdrawn for an adverse "
                                 "event, drug (highest arm) against comparator."})
        else:
            rows.append({"k": "Stopped for adverse events", "verdict": f"{d:.1f}% on the drug",
                         "tone": "neutral", "text": "No comparator arm to read it against."})
    else:
        rows.append({"k": "Stopped for adverse events", "verdict": "not posted",
                     "tone": "neutral", "text": "The participant flow records none by arm."})
    n = study.get("enrollment")
    kind = next((r for r in roles.values() if r in REF_ROLES), None)
    phase = study.get("phase") or "phase not stated"
    big = n is not None and n >= LARGE_STUDY
    small = n is not None and n < SMALL_STUDY
    tone = ("good" if kind and big and "3" in phase else
            "bad" if (not kind) or small else "neutral")
    rows.append({"k": "Evidence",
                 "verdict": f"{phase}, {f'{n:,}' if n else 'no count'} participants",
                 "tone": tone,
                 "text": (f"Read against a {kind} arm." if kind else "No placebo or control arm.")
                         + f" Green for a controlled Phase 3 of {LARGE_STUDY} or more; red "
                           f"for no comparator or under {SMALL_STUDY} participants."})
    return rows


# --- the words -----------------------------------------------------------------------------
def _summary(study: dict, primary: list, comp: dict | None, has_results: bool,
             roles: dict, fetched: bool = True) -> str:
    n = study.get("enrollment")
    head = (f"{study.get('phase') or 'A study'} of {n:,} participants" if n
            else f"{study.get('phase') or 'A study'}")
    when = study.get("primary_completion_date") or study.get("completion_date")
    head += f", {str(study.get('status') or '').lower() or 'status not stated'}"
    head += f", primary completion {_month(when)}." if when else "."
    if not fetched:
        return head + " " + NOT_FETCHED
    if not has_results:
        return head + " No results are posted to the registry yet."
    if not primary:
        return head + " Results are posted, but no primary endpoint is among them."
    p = primary[0]
    arms = []
    for row in p["rows"][:4]:
        if row.get("category"):
            continue
        arms.append(f"{row.get('group_title') or 'an arm'} {_value_text(row)}"
                    + (f" {p['unit']}" if p.get("unit") else ""))
    said = f" On the primary endpoint, {p['title']}"
    said += f" ({p['time_frame']})" if p.get("time_frame") else ""
    said += (": " + "; ".join(arms) + ".") if arms else "."
    if comp:
        est = (f" The sponsor's analysis gives {comp.get('param_type') or 'an estimate'} "
               f"{_num(comp.get('value'))}")
        if comp.get("lo") is not None and comp.get("hi") is not None:
            est += (f" ({int(comp.get('ci_pct') or 95)}% interval {_num(comp['lo'])} to "
                    f"{_num(comp['hi'])})")
        if comp.get("p_value"):
            est += f", p {comp['p_value']}"
        said += est + "."
    else:
        said += " No comparison between the arms is posted."
    return head + said


def _factors(study: dict, primary: list, comp: dict | None, comps: list, safety: list,
             roles: dict, has_results: bool, results_date, readouts: list,
             fetched: bool = True) -> list:
    out = []
    status = str(study.get("status") or "").lower()
    if "terminated" in status:
        out.append("The study was stopped early (terminated); a result from a stopped "
                   "study is read with its reason, which the registry states separately.")
    kind = next((r for r in roles.values() if r in REF_ROLES), None)
    if has_results and not kind:
        out.append("No placebo or control arm: nothing in the study to read the result "
                   "against, so any effect is relative to the participants' own baseline.")
    drug_arms = [g for g, r in roles.items() if r == "drug"]
    if len(drug_arms) > 1:
        out.append(f"{len(drug_arms)} arms are the drug (doses, regimens or cohorts); the "
                   "card leads on the comparison with the smallest p-value and the summary "
                   "lists every arm.")
    if len(primary) > 1:
        out.append(f"{len(primary)} primary endpoints are posted; the first is the one "
                   "summarised. A study can meet one and miss another.")
    if comp and not comp.get("against_comparator") and kind:
        out.append("The comparison posted is not of the drug against the control arm.")
    n = study.get("enrollment")
    if n is not None and n < SMALL_STUDY:
        out.append(f"A small study ({n:,} participants): one result at this size moves "
                   "little on its own.")
    if comp and comp.get("value") is not None and excludes_null(comp) is False:
        out.append("The interval around the effect includes no effect.")
    deaths = [(s["group_title"], s["deaths"]) for s in safety
              if s.get("deaths") and s["role"] == "drug"]
    if deaths:
        out.append("Deaths on the drug: " + ", ".join(f"{t} {d}" for t, d in deaths) + ".")
    done = study.get("primary_completion_date")
    if has_results and results_date and done:
        lag = _months_between(done, results_date)
        if lag is not None and lag > 12:
            out.append(f"Results were posted {lag} months after primary completion, past "
                       "the registry's twelve-month rule.")
    elif fetched and not has_results and done:
        lag = _months_between(done, dt.date.today().isoformat())
        if lag is not None and lag > 12:
            out.append(f"Primary completion was {lag} months ago and no results are posted.")
    if readouts:
        signed = [r for r in readouts if r.get("outcome")]
        if signed:
            out.append("The company's own words read as " + signed[0]["outcome"]
                       + f" ({signed[0].get('source') or 'a source'}, "
                       f"{_month(signed[0].get('date'))}).")
    out.append("Posted by the sponsor to ClinicalTrials.gov and not adjudicated here: the "
               "colours are reading rules, not a judgement of the drug.")
    return out


# --- the call ------------------------------------------------------------------------------
def report(db_path, nct_id: str) -> dict | None:
    """Everything the book holds on one study's results, or None for a study it does not
    hold at all."""
    nct = str(nct_id or "").strip().upper()
    conn = db.get_connection(db_path)
    try:
        t = conn.execute(
            "SELECT t.*, a.brand_name, a.generic_name, c.ticker FROM trials t"
            " LEFT JOIN assets a ON a.id = t.asset_id"
            " LEFT JOIN companies c ON c.id = t.sponsor_company_id WHERE t.nct_id = ?",
            (nct,)).fetchone()
        if t is None:
            t = conn.execute(
                "SELECT ct.*, 'Completed' AS overall_status, ct.completion_date AS"
                " primary_completion_date, a.brand_name, a.generic_name, c.ticker,"
                " NULL AS acronym, NULL AS design FROM completed_trials ct"
                " LEFT JOIN assets a ON a.id = ct.asset_id"
                " LEFT JOIN companies c ON c.id = ct.sponsor_company_id WHERE ct.nct_id = ?",
                (nct,)).fetchone()
        if t is None:
            return None
        t = dict(t)
        fetch = conn.execute("SELECT has_results, results_date FROM trial_result_fetches"
                             " WHERE nct_id = ?", (nct,)).fetchone()
        fetched = fetch is not None
        has_results = bool(fetch and fetch["has_results"])
        results_date = fetch["results_date"] if fetch else None
        outcomes = [dict(r) for r in conn.execute(
            "SELECT * FROM trial_result_outcomes WHERE nct_id = ? AND outcome_type = 'PRIMARY'"
            " ORDER BY outcome_index, id", (nct,))]
        analyses = [dict(r) for r in conn.execute(
            "SELECT * FROM trial_result_analyses WHERE nct_id = ? ORDER BY outcome_index, id",
            (nct,))]
        safety_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM trial_result_safety WHERE nct_id = ? ORDER BY id", (nct,))]
        events = [dict(r) for r in conn.execute(
            "SELECT * FROM trial_result_events WHERE nct_id = ?", (nct,))]
        names = _names(conn, t.get("asset_id"))
        readouts = [{"date": r["published_at"], "sentence": r["sentence"],
                     "outcome": r["outcome"], "source": r["source"], "url": r["url"]}
                    for r in conn.execute(
                        "SELECT * FROM readout_reports WHERE nct_id = ? AND sentence IS NOT NULL"
                        " ORDER BY published_at DESC", (nct,))]
        readouts += [{"date": r["event_date"], "sentence": r["quote"],
                      "outcome": {"positive": "met", "negative": "missed"}.get(r["outcome"]),
                      "source": "filing", "url": r["source_url"]}
                     for r in conn.execute(
                         "SELECT * FROM trial_readouts WHERE nct_id = ? AND quote IS NOT NULL"
                         " ORDER BY event_date DESC", (nct,))]
    finally:
        conn.close()

    study = {"nct_id": nct, "title": t.get("title"), "acronym": t.get("acronym"),
             "phase": t.get("phase"), "status": t.get("overall_status"),
             "primary_completion_date": t.get("primary_completion_date"),
             "completion_date": t.get("completion_date"), "enrollment": t.get("enrollment"),
             "primary_outcome": t.get("primary_outcome"), "design": t.get("design"),
             "sponsor": t.get("ticker"), "asset_id": t.get("asset_id"),
             "drug": t.get("brand_name") or t.get("generic_name")}
    arms = _arms(outcomes, [])
    roles = _roles(arms, names)
    safety_arms = _arms([], safety_rows)
    safety_roles = _roles(safety_arms, names)
    primary = []
    for index in dict.fromkeys(o["outcome_index"] for o in outcomes):
        rows = [o for o in outcomes if o["outcome_index"] == index]
        first = rows[0]
        primary.append({
            "index": index, "title": first.get("title"), "time_frame": first.get("time_frame"),
            "unit": first.get("unit"), "param_type": first.get("param_type"),
            "rows": [{"group_id": r["group_id"], "group_title": r["group_title"],
                      "role": roles.get(r["group_id"], "other"), "category": r.get("category"),
                      "value": r.get("value"), "value_text": r.get("value_text"),
                      "spread": r.get("spread"), "lower": r.get("lower"),
                      "upper": r.get("upper"), "n": r.get("n_analysed")} for r in rows]})
    comps = []
    if primary:
        comps = _comparisons([a for a in analyses
                              if a["outcome_index"] == primary[0]["index"]], roles)
    comp = _lead(comps)
    safety = [{"group_id": s["group_id"], "group_title": s["group_title"],
               "role": safety_roles.get(s["group_id"], "other"),
               "at_risk": s.get("serious_at_risk"), "deaths": s.get("deaths_affected"),
               "serious_pct": _pct(s.get("serious_affected"), s.get("serious_at_risk")),
               "other_pct": _pct(s.get("other_affected"), s.get("other_at_risk")),
               "withdrawn_ae": s.get("withdrawn_ae"),
               "withdrawn_pct": _pct(s.get("withdrawn_ae"), s.get("serious_at_risk"))}
              for s in safety_rows]
    by_term: dict = {}
    for e in events:
        key = (e["term"], e["serious"])
        by_term.setdefault(key, {})[e["group_id"]] = _pct(e.get("affected"), e.get("at_risk"))
    ranked = sorted(by_term.items(), key=lambda kv: -max((v or 0) for v in kv[1].values()))
    top = [{"term": term, "serious": bool(serious),
            "arms": [{"group_title": a["group_title"], "role": safety_roles.get(a["group_id"]),
                      "pct": rates.get(a["group_id"])} for a in safety_arms]}
           for (term, serious), rates in ranked[:EVENTS_KEPT]]
    return {"study": study, "fetched": fetched, "has_results": has_results,
            "results_date": results_date,
            "arms": [{**a, "role": roles.get(a["group_id"])} for a in arms],
            "primary": primary, "comparison": comp, "comparisons": comps,
            "safety": safety, "events": top, "readouts": readouts,
            "scorecard": _card(primary, comp, comps, safety, study, roles, has_results,
                               fetched),
            "summary": _summary(study, primary, comp, has_results, roles, fetched),
            "factors": _factors(study, primary, comp, comps, safety, roles, has_results,
                                results_date, readouts, fetched)}


def completed(db_path, ticker: str, per_asset: int = 60) -> list | None:
    """The company's completed studies, each bound to its asset, newest first, at most
    ``per_asset`` an asset, with whether the sponsor has posted results: True, False, or
    None where the results fetcher has never asked. None for a ticker the book does not
    hold."""
    conn = db.get_connection(db_path)
    try:
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (str(ticker or "").upper(),)).fetchone()
        if company is None:
            return None
        rows = [dict(r) for r in conn.execute(
            "SELECT ct.nct_id, ct.asset_id, ct.title, ct.phase, ct.completion_date,"
            " ct.enrollment, ct.primary_outcome,"
            " CASE WHEN f.nct_id IS NULL THEN NULL ELSE f.has_results END AS has_results"
            " FROM completed_trials ct"
            " LEFT JOIN trial_result_fetches f ON f.nct_id = ct.nct_id"
            " WHERE ct.sponsor_company_id = ? AND ct.asset_id IS NOT NULL"
            " ORDER BY ct.asset_id, (ct.completion_date IS NULL), ct.completion_date DESC",
            (company["id"],))]
    finally:
        conn.close()
    out, kept = [], {}
    for r in rows:
        kept[r["asset_id"]] = kept.get(r["asset_id"], 0) + 1
        if kept[r["asset_id"]] <= per_asset:
            # None for a study the results fetcher has never asked, never False.
            out.append({**r, "has_results": (None if r["has_results"] is None
                                              else bool(r["has_results"]))})
    return out
