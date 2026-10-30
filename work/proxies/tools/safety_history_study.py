"""Step 8d, retested without survivorship: does a Phase 2 safety imbalance predict that the
compound never reaches Phase 3?

The first test (``safety_study.py``) read the book's own studies, and the book holds the
assets that went on, so a programme that died after a bad Phase 2 was mostly not in it.
This one reads every Phase 2 and Phase 3 the companies ran from ClinicalTrials.gov,
whether or not the compound is still anywhere in the book.

**Studies.** Phase 2 (not Phase 1/2 or 2/3), started 2008 on, completed or terminated,
with posted adverse events, at least three years since completion, and a placebo or sham
arm (``armGroups.type``) to compare with.

**Compound.** A drug or biological intervention in the experimental arms that is not in
the comparator arms and is not a placebo, matched later by its name or any of its other
names, lower cased, with dose and form words dropped. A compound already in a Phase 3
of the same sponsor that started before the Phase 2 did is not at risk and is left out.

**Imbalance.** Serious adverse events and deaths as a share of patients at risk, the
experimental groups pooled less the comparator groups. Event groups are matched to arms
by title, or told apart by whether the title names placebo or the compound; a study
with a group that names both or neither is left out rather than guessed.

**Outcome.** A Phase 3 of the same sponsor naming the compound, started after the
Phase 2 started and within three years of its completion.

Bias, stated: one sponsor's programmes only, so a compound licensed out before its
Phase 3 counts as stopped; and a sponsor posts results more often for studies it
completed than for ones it stopped.

    python3 work/proxies/tools/safety_history_study.py download <folder>
    python3 work/proxies/tools/safety_history_study.py analyse <folder> [--json out]
"""

import collections
import datetime as dt
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ["protocolSection.identificationModule.nctId",
          "protocolSection.statusModule.overallStatus",
          "protocolSection.statusModule.startDateStruct",
          "protocolSection.statusModule.primaryCompletionDateStruct",
          "protocolSection.statusModule.completionDateStruct",
          "protocolSection.designModule.phases",
          "protocolSection.armsInterventionsModule.armGroups",
          "protocolSection.armsInterventionsModule.interventions",
          "protocolSection.sponsorCollaboratorsModule.leadSponsor",
          "resultsSection.adverseEventsModule.eventGroups"]
FIRST_YEAR = 2008
HORIZON_DAYS = 3 * 365
COMPARATOR_TYPES = {"PLACEBO_COMPARATOR", "SHAM_COMPARATOR"}
PLACEBO = re.compile(r"placebo|vehicle|sham|saline|matching", re.I)
# Words that describe a dose or a form rather than name a compound.
_NOISE = re.compile(r"\b(\d+(\.\d+)?\s*(mg|mcg|µg|ug|g|ml|mg/kg|iu|%)|tablets?|capsules?|"
                    r"injection|infusion|oral|subcutaneous|intravenous|iv|sc|solution|"
                    r"dose|low|high|medium|once|twice|daily|weekly|q\dw|qd|bid)\b", re.I)


def download(folder):
    import acquired_sponsors
    import company_names
    import ctgov
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection()
    tickers = [r[0] for r in conn.execute("SELECT ticker FROM companies ORDER BY ticker")]
    conn.close()
    for ticker in tickers:
        if (folder / f"{ticker}.json").exists():
            continue
        term = company_names.source_name(ticker, "ctgov_sponsor",
                                         ctgov.SPONSOR_LEAD.get(ticker), None)
        if not term:
            continue
        studies, failed = [], False
        for sponsor in [term] + acquired_sponsors.for_company(None, ticker):
            token = None
            while True:
                params = {"query.lead": sponsor, "fields": ",".join(FIELDS),
                          "pageSize": 200,
                          "filter.advanced": "AREA[StudyType]INTERVENTIONAL AND "
                                             "(AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND "
                                             f"AREA[StartDate]RANGE[{FIRST_YEAR}-01-01,MAX]"}
                if token:
                    params["pageToken"] = token
                url = f"{STUDIES_URL}?{urllib.parse.urlencode(params)}"
                data = None
                for attempt in range(4):
                    try:
                        req = urllib.request.Request(
                            url, headers={"User-Agent": "Novatalis Research"})
                        data = json.loads(urllib.request.urlopen(req, timeout=120).read())
                        break
                    except Exception as exc:               # noqa: BLE001
                        print(f"{ticker} {sponsor}: {exc}", flush=True)
                        time.sleep(2 ** (attempt + 1))
                if data is None:
                    failed = True
                    break
                studies += data.get("studies", [])
                token = data.get("nextPageToken")
                if not token:
                    break
                time.sleep(0.3)
        if not failed:
            (folder / f"{ticker}.json").write_text(json.dumps(studies))
        print(ticker, len(studies), "failed" if failed else "", flush=True)


def _date(struct):
    text = (struct or {}).get("date") or ""
    parts = text.split("-")
    try:
        if len(parts) == 3:
            return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return dt.date(int(parts[0]), int(parts[1]), 15)
    except ValueError:
        return None
    return None


def _key(name):
    text = _NOISE.sub(" ", (name or "").lower())
    text = re.sub(r"[^a-z0-9-]+", " ", text).strip()
    return re.sub(r"\s+", " ", text)


def _names(intervention):
    out = {_key(intervention.get("name"))}
    out.update(_key(n) for n in intervention.get("otherNames") or [])
    return {n for n in out if len(n) > 3 and not PLACEBO.search(n)}


def _study(raw):
    p = raw.get("protocolSection") or {}
    status = p.get("statusModule") or {}
    arms = (p.get("armsInterventionsModule") or {}).get("armGroups") or []
    drugs = [i for i in (p.get("armsInterventionsModule") or {}).get("interventions") or []
             if i.get("type") in ("DRUG", "BIOLOGICAL")]
    return {"nct": (p.get("identificationModule") or {}).get("nctId"),
            "status": status.get("overallStatus"),
            "start": _date(status.get("startDateStruct")),
            "done": (_date(status.get("primaryCompletionDateStruct"))
                     or _date(status.get("completionDateStruct"))),
            "phases": tuple((p.get("designModule") or {}).get("phases") or ()),
            "arms": arms, "drugs": drugs,
            "groups": ((raw.get("resultsSection") or {}).get("adverseEventsModule")
                       or {}).get("eventGroups") or []}


def _compound(study):
    """The names of the compound under test: in an experimental arm, in no comparator."""
    by_label = {}
    for d in study["drugs"]:
        for label in d.get("armGroupLabels") or []:
            by_label.setdefault(label, set()).update(_names(d))
    exp = set().union(*[by_label.get(a.get("label"), set()) for a in study["arms"]
                        if a.get("type") == "EXPERIMENTAL"] or [set()])
    comp = set().union(*[by_label.get(a.get("label"), set()) for a in study["arms"]
                         if a.get("type") in COMPARATOR_TYPES] or [set()])
    return exp - comp


def _rate(groups, field_n, field_at_risk):
    n = sum(g.get(field_n) or 0 for g in groups)
    at_risk = sum(g.get(field_at_risk) or 0 for g in groups)
    return n / at_risk if at_risk else None


def _imbalance(study, compound=()):
    """(serious events, deaths) as drug less comparator, or None.

    A group takes the type of the arm whose label it repeats. Otherwise its title says:
    placebo without the compound is the comparator, the compound without placebo is the
    drug, and a title naming both (a crossover period, a placebo then drug group) or
    neither leaves the study out."""
    labels = {a.get("label", "").strip().lower(): a.get("type") for a in study["arms"]}
    words = {w for name in compound for w in name.split() if len(w) > 3}
    exp, comp = [], []
    for g in study["groups"]:
        title = (g.get("title") or "").strip().lower()
        kind = labels.get(title)
        if kind is None:
            named = bool(words & set(_key(title).split()))
            if PLACEBO.search(title) and not named:
                kind = "PLACEBO_COMPARATOR"
            elif named and not PLACEBO.search(title):
                kind = "EXPERIMENTAL"
        if kind in COMPARATOR_TYPES:
            comp.append(g)
        elif kind == "EXPERIMENTAL":
            exp.append(g)
        elif kind is None and title not in ("total", "overall"):
            return None                     # a group that cannot be told apart
    if not exp or not comp:
        return None
    sae = [_rate(x, "seriousNumAffected", "seriousNumAtRisk") for x in (exp, comp)]
    deaths = [_rate(x, "deathsNumAffected", "deathsNumAtRisk") for x in (exp, comp)]
    if None in sae:
        return None
    return {"sae": sae[0] - sae[1], "sae_drug": sae[0], "sae_comp": sae[1],
            "deaths": (deaths[0] - deaths[1]) if None not in deaths else None,
            "at_risk": sum(g.get("seriousNumAtRisk") or 0 for g in exp + comp)}


def _book_names():
    conn = db.get_connection()
    out = set()
    for r in conn.execute("SELECT brand_name, generic_name, internal_code FROM assets"):
        out.update(_key(n) for n in r if n)
    conn.close()
    return out


def analyse(folder, out_path=None):
    today = dt.date.today()
    book = _book_names()
    rows = []
    for path in sorted(pathlib.Path(folder).glob("*.json")):
        studies = [_study(s) for s in json.loads(path.read_text())]
        phase3 = [s for s in studies if "PHASE3" in s["phases"] and s["start"]]
        p3_names = [(s["start"], set().union(*[_names(d) for d in s["drugs"]] or [set()]))
                    for s in phase3]
        for s in studies:
            if (s["phases"] != ("PHASE2",) or s["status"] not in ("COMPLETED", "TERMINATED")
                    or not s["groups"] or not s["start"] or not s["done"]
                    or (today - s["done"]).days < HORIZON_DAYS
                    or not any(a.get("type") in COMPARATOR_TYPES for a in s["arms"])):
                continue
            compound = _compound(s)
            if not compound:
                continue
            if any(start < s["start"] and names & compound for start, names in p3_names):
                continue                    # already in Phase 3: not at risk
            gap = _imbalance(s, compound)
            if gap is None:
                continue
            went_on = any(s["start"] <= start <= s["done"] + dt.timedelta(days=HORIZON_DAYS)
                          and names & compound for start, names in p3_names)
            rows.append({"ticker": path.stem, "nct": s["nct"], "status": s["status"],
                         "compound": sorted(compound), "went_on": went_on,
                         "in_book": bool(compound & book), **gap})
    # A compound with several Phase 2s counts once per study; the table says so.
    print(len(rows), "Phase 2 studies,", len({r["compound"][0] for r in rows}), "compounds;",
          f"{sum(r['went_on'] for r in rows) / len(rows):.0%} reached Phase 3;",
          f"{sum(not r['in_book'] for r in rows) / len(rows):.0%} name no compound the"
          " book holds")
    bands = [("lower by over 5 points", lambda g: g < -0.05),
             ("lower by up to 5", lambda g: -0.05 <= g < 0),
             ("higher by up to 5", lambda g: 0 <= g < 0.05),
             ("higher by 5 to 10", lambda g: 0.05 <= g < 0.10),
             ("higher by over 10", lambda g: g >= 0.10)]
    table = []
    for label, test in bands:
        part = [r for r in rows if test(r["sae"])]
        if part:
            table.append((label, len(part), sum(r["went_on"] for r in part) / len(part),
                          sum(r["status"] == "TERMINATED" for r in part) / len(part)))
            print(f"  serious events {label}: n {len(part)}, reached Phase 3 "
                  f"{table[-1][2]:.0%}, terminated {table[-1][3]:.0%}")
    deaths = [r for r in rows if r["deaths"] is not None and r["deaths"] > 0]
    if deaths:
        print(f"  deaths higher in the drug arm: n {len(deaths)}, reached Phase 3 "
              f"{sum(r['went_on'] for r in deaths) / len(deaths):.0%}")
    on = [r["sae"] for r in rows if r["went_on"]]
    off = [r["sae"] for r in rows if not r["went_on"]]
    if on and off:
        print(f"  mean imbalance: went on {statistics.mean(on):+.3f},"
              f" stopped {statistics.mean(off):+.3f}")
        # Rank correlation of the imbalance with stopping, by hand to stay stdlib.
        ranked = sorted(range(len(rows)), key=lambda i: rows[i]["sae"])
        rank = {i: k for k, i in enumerate(ranked)}
        stops = [0 if r["went_on"] else 1 for r in rows]
        mean_r, mean_s = statistics.mean(rank.values()), statistics.mean(stops)
        cov = sum((rank[i] - mean_r) * (stops[i] - mean_s) for i in range(len(rows)))
        var_r = sum((v - mean_r) ** 2 for v in rank.values())
        var_s = sum((v - mean_s) ** 2 for v in stops)
        print(f"  rank correlation of imbalance with stopping: {cov / (var_r * var_s) ** 0.5:+.3f}")
    if out_path:
        pathlib.Path(out_path).write_text(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    if sys.argv[1] == "download":
        download(sys.argv[2])
    else:
        analyse(sys.argv[2], sys.argv[4] if len(sys.argv) > 4 else None)
