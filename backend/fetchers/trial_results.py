"""The results a sponsor posted to ClinicalTrials.gov: efficacy, safety and dropouts.

The registry fetches keep what a study is (its phase, status, dates and the name of its
primary endpoint). What it found is a separate and much larger document, the results
section, and nothing read it: the only efficacy on file was a sentence quoted from a
press release, classified for 57 of 1,200 readouts. Comparing candidates on one
indication, which is what the landscape is for, needs the numbers.

Per study this stores, per arm:

- **Outcome measures**: every primary endpoint and the first secondaries, value,
  dispersion, confidence limits and the number analysed, exactly as posted.
- **Analyses**: the comparisons the sponsor ran, with the estimate, interval and p value.
- **Safety**: deaths, serious and other adverse events over the number at risk, and the
  withdrawals the participant flow puts down to an adverse event.
- **Events**: the most frequent adverse event terms, each with its rate in every arm.

Nothing is derived here. A value the registry posted as "NA" is stored as text beside a
null, never as a number.

Run for the big pharma companies only, on their Phase 2 and later studies mapped to an
asset. A study is asked once and again only when it is 90 days stale, since posted
results rarely change; the registry is asked in batches of 20 by NCT id.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

import ctgov
import db
from fetchers.base import BaseFetcher, RefreshResult

SOURCE = "trial_results"
TTL_SECONDS = 24 * 60 * 60
REFETCH_DAYS = 90
BATCH = 20
MAX_STUDIES_PER_RUN = 1500      # a first run over a large sponsor finishes over several nights
SECONDARY_KEPT = 10
OTHER_EVENTS_KEPT = 15
SERIOUS_EVENTS_KEPT = 10
LATE = ("Phase 2", "Phase 2/3", "Phase 3")
_TIMEOUT_S = 90
_POLITE_SLEEP_S = 0.3
_USER_AGENT = "NovatalisResearch/0.1 (contact cswoodfine@icloud.com)"

FIELDS = "|".join((
    "protocolSection.identificationModule.nctId",
    "hasResults",
    "resultsSection",
    "protocolSection.statusModule.resultsFirstPostDateStruct",
    "protocolSection.statusModule.lastUpdatePostDateStruct",
))


def get_json(url: str, params: dict) -> dict:
    """GET a registry page. Module level so a test can stand a fixture in for it."""
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        return json.loads(response.read().decode("utf-8"))


def _num(value):
    """A posted value as a float, or None where the registry posted text such as NA."""
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _int(value):
    got = _num(value)
    return int(got) if got is not None else None


# --- pure parser ------------------------------------------------------------------
def parse_study(study: dict) -> dict:
    """One registry study to the rows of the four result tables."""
    ident = (study.get("protocolSection") or {}).get("identificationModule") or {}
    status = (study.get("protocolSection") or {}).get("statusModule") or {}
    nct = ident.get("nctId")
    results = study.get("resultsSection") or {}
    out = {"nct_id": nct, "has_results": bool(study.get("hasResults") and results),
           "results_date": ((status.get("lastUpdatePostDateStruct") or {}).get("date")
                            or (status.get("resultsFirstPostDateStruct") or {}).get("date")),
           "outcomes": [], "analyses": [], "safety": [], "events": []}
    if not out["has_results"]:
        return out

    measures = (results.get("outcomeMeasuresModule") or {}).get("outcomeMeasures") or []
    secondary_seen = 0
    for index, m in enumerate(measures):
        kind = m.get("type")
        if kind == "SECONDARY":
            secondary_seen += 1
            if secondary_seen > SECONDARY_KEPT:
                continue
        elif kind != "PRIMARY":
            continue
        groups = {g.get("id"): g for g in m.get("groups") or []}
        n = {}
        for denom in m.get("denoms") or []:
            for count in denom.get("counts") or []:
                n.setdefault(count.get("groupId"), _int(count.get("value")))
        for cls in m.get("classes") or [{}]:
            for cat in cls.get("categories") or [{}]:
                label = " · ".join(t for t in (cls.get("title"), cat.get("title")) if t) or None
                for meas in cat.get("measurements") or []:
                    gid = meas.get("groupId")
                    group = groups.get(gid) or {}
                    out["outcomes"].append({
                        "outcome_index": index, "outcome_type": kind,
                        "title": m.get("title"), "time_frame": m.get("timeFrame"),
                        "unit": m.get("unitOfMeasure"), "param_type": m.get("paramType"),
                        "dispersion_type": m.get("dispersionType"),
                        "group_id": gid, "group_title": group.get("title"),
                        "group_description": (group.get("description") or "")[:500] or None,
                        "category": label,
                        "value": _num(meas.get("value")), "value_text": meas.get("value"),
                        "spread": _num(meas.get("spread")),
                        "lower": _num(meas.get("lowerLimit")),
                        "upper": _num(meas.get("upperLimit")),
                        "n_analysed": n.get(gid)})
        for a in m.get("analyses") or []:
            out["analyses"].append({
                "outcome_index": index, "group_ids": json.dumps(a.get("groupIds") or []),
                "method": a.get("statisticalMethod"), "param_type": a.get("paramType"),
                "param_value": _num(a.get("paramValue")), "ci_pct": _num(a.get("ciPctValue")),
                "ci_lower": _num(a.get("ciLowerLimit")),
                "ci_upper": _num(a.get("ciUpperLimit")), "p_value": a.get("pValue")})

    ae = results.get("adverseEventsModule") or {}
    withdrawn = _withdrawn_for_ae(results.get("participantFlowModule") or {})
    for g in ae.get("eventGroups") or []:
        out["safety"].append({
            "group_id": g.get("id"), "group_title": g.get("title"),
            "deaths_affected": _int(g.get("deathsNumAffected")),
            "deaths_at_risk": _int(g.get("deathsNumAtRisk")),
            "serious_affected": _int(g.get("seriousNumAffected")),
            "serious_at_risk": _int(g.get("seriousNumAtRisk")),
            "other_affected": _int(g.get("otherNumAffected")),
            "other_at_risk": _int(g.get("otherNumAtRisk")),
            "withdrawn_ae": withdrawn.get(_key(g.get("title"))),
            "time_frame": ae.get("timeFrame")})
    for serious, events, kept in ((1, ae.get("seriousEvents") or [], SERIOUS_EVENTS_KEPT),
                                  (0, ae.get("otherEvents") or [], OTHER_EVENTS_KEPT)):
        for e in _most_frequent(events, kept):
            for s in e.get("stats") or []:
                out["events"].append({
                    "term": e.get("term"), "organ_system": e.get("organSystem"),
                    "serious": serious, "group_id": s.get("groupId"),
                    "affected": _int(s.get("numAffected")),
                    "at_risk": _int(s.get("numAtRisk"))})
    return out


def _key(title) -> str:
    return " ".join((title or "").lower().split())


def _withdrawn_for_ae(flow: dict) -> dict:
    """Withdrawals the flow puts down to an adverse event, per arm title, summed across
    periods. Matched to the adverse event groups by title, because the flow and the
    adverse event module number their groups separately (FG000 against EG000)."""
    titles = {g.get("id"): _key(g.get("title")) for g in flow.get("groups") or []}
    out: dict = {}
    for period in flow.get("periods") or []:
        for drop in period.get("dropWithdraws") or []:
            if (drop.get("type") or "").lower() != "adverse event":
                continue
            for reason in drop.get("reasons") or []:
                title = titles.get(reason.get("groupId"))
                n = _int(reason.get("numSubjects"))
                if title is not None and n is not None:
                    out[title] = out.get(title, 0) + n
    return out


def _most_frequent(events: list, kept: int) -> list:
    """The events with the highest rate in any arm, so the placebo arm's rate stays
    beside the drug's."""
    def top(e):
        rates = [(_int(s.get("numAffected")) or 0) / (_int(s.get("numAtRisk")) or 1)
                 for s in e.get("stats") or [] if _int(s.get("numAtRisk"))]
        return max(rates, default=0.0)
    return sorted(events, key=top, reverse=True)[:kept]


class TrialResultsFetcher(BaseFetcher):
    """One company's Phase 2 and later studies' posted results."""

    source = SOURCE
    ttl_seconds = TTL_SECONDS

    def __init__(self, ticker: str, db_path=None):
        super().__init__(db_path)
        self.ticker = ticker.upper()

    @property
    def entity_key(self) -> str:
        return self.ticker

    def due(self, conn) -> list[str]:
        """The company's studies to ask about: Phase 2 and later, mapped to an asset,
        never asked or asked more than REFETCH_DAYS ago. Newest completion first."""
        company = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                               (self.ticker,)).fetchone()
        if company is None:
            return []
        marks = ",".join("?" * len(LATE))
        rows = conn.execute(
            f"""SELECT nct_id, MAX(done) AS done FROM (
                    SELECT nct_id, completion_date AS done FROM completed_trials
                     WHERE sponsor_company_id = ? AND asset_id IS NOT NULL
                       AND phase IN ({marks})
                    UNION ALL
                    SELECT nct_id, primary_completion_date AS done FROM trials
                     WHERE sponsor_company_id = ? AND asset_id IS NOT NULL
                       AND phase IN ({marks})
                       AND overall_status IN ('COMPLETED', 'ACTIVE_NOT_RECRUITING',
                                              'TERMINATED'))
                 WHERE nct_id NOT IN (
                    SELECT nct_id FROM trial_result_fetches
                     WHERE fetched_at >= datetime('now', ?))
                 GROUP BY nct_id ORDER BY done DESC""",
            (company["id"], *LATE, company["id"], *LATE,
             f"-{REFETCH_DAYS} days")).fetchall()
        return [r["nct_id"] for r in rows][:MAX_STUDIES_PER_RUN]

    def fetch(self) -> dict:
        conn = db.get_connection(self.db_path)
        try:
            wanted = self.due(conn)
        finally:
            conn.close()
        studies = []
        for start in range(0, len(wanted), BATCH):
            ids = wanted[start:start + BATCH]
            payload = get_json(ctgov.STUDIES_URL, {
                "filter.ids": ",".join(ids), "fields": FIELDS, "pageSize": BATCH})
            studies.extend(payload.get("studies") or [])
            time.sleep(_POLITE_SLEEP_S)
        return {"asked": wanted, "studies": studies}

    def normalise(self, raw) -> list[dict]:
        parsed = [parse_study(s) for s in raw.get("studies") or []]
        seen = {p["nct_id"] for p in parsed}
        # A study the registry did not return is still marked asked, so it is not asked
        # again every night; it is retried after REFETCH_DAYS like everything else.
        for nct in raw.get("asked") or []:
            if nct not in seen:
                parsed.append({"nct_id": nct, "has_results": False, "results_date": None,
                               "outcomes": [], "analyses": [], "safety": [], "events": []})
        return parsed

    def snapshot(self, rows: list[dict]) -> None:
        conn = db.get_connection(self.db_path)
        try:
            self._write_snapshot(conn, {
                "source": SOURCE, "asked": len(rows),
                "with_results": sum(1 for r in rows if r["has_results"]),
                "fetch_kind": "live"})
            conn.commit()
        finally:
            conn.close()

    def _write_snapshot(self, conn, payload) -> None:
        conn.execute(
            "INSERT INTO snapshots (source, entity_type, entity_key, payload,"
            " refresh_run_id) VALUES (?, 'source', ?, ?, ?)",
            (self.source, self.entity_key, json.dumps(payload), self.refresh_run_id))

    def _snapshot_cache(self) -> None:
        conn = db.get_connection(self.db_path)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM trial_result_fetches f JOIN completed_trials t"
                " ON t.nct_id = f.nct_id JOIN companies c ON c.id = t.sponsor_company_id"
                " WHERE c.ticker = ? AND f.has_results = 1", (self.ticker,)).fetchone()[0]
            self._write_snapshot(conn, {"source": SOURCE, "with_results": n,
                                        "fetch_kind": "cache"})
            conn.commit()
        finally:
            conn.close()

    def upsert(self, rows: list[dict]) -> RefreshResult:
        conn = db.get_connection(self.db_path)
        try:
            for r in rows:
                nct = r["nct_id"]
                for table in ("trial_result_outcomes", "trial_result_analyses",
                              "trial_result_safety", "trial_result_events"):
                    conn.execute(f"DELETE FROM {table} WHERE nct_id = ?", (nct,))
                for o in r["outcomes"]:
                    conn.execute(
                        "INSERT INTO trial_result_outcomes (nct_id, outcome_index,"
                        " outcome_type, title, time_frame, unit, param_type,"
                        " dispersion_type, group_id, group_title, group_description,"
                        " category, value, value_text, spread, lower, upper, n_analysed)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (nct, o["outcome_index"], o["outcome_type"], o["title"],
                         o["time_frame"], o["unit"], o["param_type"], o["dispersion_type"],
                         o["group_id"], o["group_title"], o["group_description"],
                         o["category"], o["value"], o["value_text"], o["spread"],
                         o["lower"], o["upper"], o["n_analysed"]))
                for a in r["analyses"]:
                    conn.execute(
                        "INSERT INTO trial_result_analyses (nct_id, outcome_index,"
                        " group_ids, method, param_type, param_value, ci_pct, ci_lower,"
                        " ci_upper, p_value) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (nct, a["outcome_index"], a["group_ids"], a["method"],
                         a["param_type"], a["param_value"], a["ci_pct"], a["ci_lower"],
                         a["ci_upper"], a["p_value"]))
                for s in r["safety"]:
                    conn.execute(
                        "INSERT OR REPLACE INTO trial_result_safety (nct_id, group_id,"
                        " group_title, deaths_affected, deaths_at_risk, serious_affected,"
                        " serious_at_risk, other_affected, other_at_risk, withdrawn_ae,"
                        " time_frame) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (nct, s["group_id"], s["group_title"], s["deaths_affected"],
                         s["deaths_at_risk"], s["serious_affected"], s["serious_at_risk"],
                         s["other_affected"], s["other_at_risk"], s["withdrawn_ae"],
                         s["time_frame"]))
                for e in r["events"]:
                    conn.execute(
                        "INSERT INTO trial_result_events (nct_id, term, organ_system,"
                        " serious, group_id, affected, at_risk) VALUES (?,?,?,?,?,?,?)",
                        (nct, e["term"], e["organ_system"], e["serious"], e["group_id"],
                         e["affected"], e["at_risk"]))
                conn.execute(
                    "INSERT INTO trial_result_fetches (nct_id, has_results, results_date,"
                    " fetched_at) VALUES (?, ?, ?, datetime('now'))"
                    " ON CONFLICT(nct_id) DO UPDATE SET has_results = excluded.has_results,"
                    " results_date = excluded.results_date, fetched_at = datetime('now')",
                    (nct, int(r["has_results"]), r["results_date"]))
            conn.commit()
        finally:
            conn.close()
        with_results = sum(1 for r in rows if r["has_results"])
        notes = ([f"{len(rows) - with_results} of {len(rows)} studies asked have no posted "
                  "results"] if len(rows) > with_results else [])
        return RefreshResult(self.source, with_results, [], False, 0, notes=notes)
