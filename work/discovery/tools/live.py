"""Rank today's lab heads and the last year's papers with the models the backtest tested,
and write the file the Discovery prototype reads.

    python3 work/discovery/tools/live.py <data folder> <backtest json> <out.json> [as-of date]

The data folder is the backtest's, with the corpus and the company records brought up to
the as-of date. Three things differ from the backtest, each because there is no "three
years later" to look at yet:

- **Lab heads** are everyone who was last or corresponding author, at a US or UK address,
  on a paper in the two years to a date, described by their papers in the four years to
  it. The model is trained on the cohorts at the end of 2020 and 2022, whose three years
  have run, and scores the cohort at the as-of date. Before that it is trained on 2020
  alone and checked on 2022, and the check is printed.
- **Papers** from the last twelve months get three scores, each from a model trained on
  every earlier paper whose three years have run. Feasibility and commercial pull read
  the title and abstract alone (``paper_scores.py``): 2017 to 2020 for a clinical
  citation, 2017 to 2022 for a citation by industry. The team's score is the backtest's
  company model, which sees the authors' record: 2017 to 2022.
- **Areas** (``areas.py``) each get their papers over time as a trailing twelve months,
  their growth, their lab heads and their best papers on each score.
- **A company record** is "new" when it is dated in the last twelve months.
"""

import collections
import datetime as dt
import json
import pathlib
import re
import sys

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

import areas as A
import backtest as B
import paper_scores as P

WINDOW_YEARS = 4          # the papers a lab head is described by
ACTIVE_YEARS = 2          # a senior-author paper this recently makes someone a lab head
MODALITIES = {
    "AAV": r"\baav\d*\b|adeno-associated", "Lentiviral": r"lentivir|retrovir",
    "CAR-T": r"car[- ]t\b|chimeric antigen|tcr[- ]t\b|car[- ]nk",
    "Cell therapy": r"cell therap|ipsc|pluripotent|mesenchymal|stem cell transplant|"
                    r"adoptive cell",
    "Gene editing": r"crispr|cas9|cas12|base edit|prime edit|genome edit|gene edit|"
                    r"talen\b|zinc[- ]finger",
    "LNP / mRNA": r"lipid nanoparticle|\blnps?\b|\bmrna\b"}
STAGE = ["patients", "primate", "large_animal", "mouse", "human_cells"]
DERISK = ["dose", "biodistribution", "immunogenicity", "off_target", "manufacturing",
          "durability"]
COI = ["coi_founder", "coi_equity", "coi_patent", "coi_employee", "coi_advisor"]
NOT_AT_COHORT = ("authors_log", "senior_works", "senior_cited", "most_cited_author",
                 "prior_award", "prior_filing", "prior_uk_company")


class Ranker:
    """The backtest's rules-and-words model, fitted on rows and used to score others."""

    def __init__(self, rows, outcome):
        self.names = sorted(rows[0]["flags"])
        self.scaler = StandardScaler().fit(self._flags(rows))
        self.words = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_df=0.6,
                                     sublinear_tf=True, stop_words="english",
                                     max_features=200_000)
        text = self.words.fit_transform([r["text"] for r in rows])
        self.model = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
        self.model.fit(self._join(text, rows), np.array([int(r[outcome]) for r in rows]))

    def _flags(self, rows):
        return [[r["flags"][n] for n in self.names] for r in rows]

    def _join(self, text, rows):
        return sparse.hstack([text, sparse.csr_matrix(
            self.scaler.transform(self._flags(rows)))]).tocsr()

    def score(self, rows):
        return self.model.decision_function(
            self._join(self.words.transform([r["text"] for r in rows]), rows))


def _share(scores):
    """Each row's place in the list, 1.0 for the top."""
    return (np.argsort(np.argsort(scores)) + 1) / len(scores)


def _labelled(author, addresses, american, in_uk, data):
    """``backtest._footprints`` with the name each record was filed under."""
    key = B._name(author.get("first"), author.get("last"))
    found = []
    if not key:
        return found
    if american:
        found += [("award", start, about, org)
                  for start, about, org in data["awards"].get(key) or ()]
        states, initial = B._states(addresses), B._initial(author.get("first"))
        found += [("formd", when, True, issuer)
                  for when, where, theirs, issuer in data["officers"].get(key) or ()
                  if states & where or (initial and initial == theirs)]
    if in_uk:
        text = " ".join(addresses).lower()
        found += [("uk", notified, born, company)
                  for notified, born, town, titled, company in data["owners"].get(key) or ()
                  if titled or (town and town in text)]
    return found


def seniors(data):
    """Every lab head's senior-author papers: identifier -> [(paper, author, ...)]."""
    people = collections.defaultdict(list)
    for paper in data["papers"]:
        for author in paper.get("authors") or []:
            theirs = author.get("oa") or {}
            key, addresses, american, in_uk, _c = B._author(author)
            if (theirs.get("aid") and key and (american or in_uk)
                    and (theirs.get("position") == "last" or theirs.get("corresponding"))):
                people[theirs["aid"]].append((paper, author, addresses, american, in_uk))
    return people


def cohort(data, described, people, cutoff):
    """One row per lab head at ``cutoff``, with what the backtest's lab test uses."""
    since = cutoff.replace(year=cutoff.year - WINDOW_YEARS)
    active = cutoff.replace(year=cutoff.year - ACTIVE_YEARS)
    until = cutoff + dt.timedelta(days=B.HORIZON_DAYS)
    rows = []
    for aid, theirs in people.items():
        known = sorted((t for t in theirs if since < t[0]["date"] <= cutoff),
                       key=lambda t: t[0]["date"])
        if not known or known[-1][0]["date"] <= active:
            continue
        records = set()
        for _paper, author, addresses, american, in_uk in known:
            records |= set(_labelled(author, addresses, american, in_uk, data))
        had = {k for k, when, _d, _l in records if when <= cutoff}
        later = {k for k, when, detail, _l in records
                 if cutoff < when <= until and (detail > cutoff if k == "uk" else detail)}
        papers = [described[t[0]["id"]] for t in known]
        flags = {name: float(np.mean([p["flags"][name] for p in papers]))
                 for name in papers[0]["flags"] if name not in NOT_AT_COHORT}
        works, cited = B._before(data["people"].get(aid), cutoff.year + 1)
        flags.update({"papers_log": float(np.log1p(len(known))),
                      "works_log": float(np.log1p(works)),
                      "cited_log": float(np.log1p(cited)),
                      "prior_award": int("award" in had), "prior_filing": int("formd" in had),
                      "prior_uk_company": int("uk" in had)})
        rows.append({"id": aid, "text": " ".join(p["text"] for p in papers)[:20000],
                     "flags": flags, "lab": bool(later), "known": known,
                     "records": records, "works": works, "cited": cited})
    return rows


def _check(train, test):
    scores = Ranker(train, "lab").score(test)
    y = np.array([int(r["lab"]) for r in test])
    floor = np.array([r["flags"]["papers_log"] for r in test])
    top = max(1, round(len(test) * 0.05))
    hit = lambda s: y[np.argsort(-s, kind="stable")[:top]].mean()     # noqa: E731
    print(f"check: trained on the 2020 cohort ({len(train):,} lab heads, "
          f"{sum(r['lab'] for r in train)} events), scored on 2022 ({len(test):,}, "
          f"{int(y.sum())} events, base {y.mean():.1%}): AUC {roc_auc_score(y, scores):.3f},"
          f" top 5% {hit(scores):.0%} against {hit(floor):.0%} for the paper count",
          flush=True)
    return {"auc": float(roc_auc_score(y, scores)), "top5": float(hit(scores)),
            "floor5": float(hit(floor)), "base": float(y.mean()), "n": len(test),
            "events": int(y.sum())}


def _institution(*authors):
    """The institution OpenAlex names most often for one person across their papers, with
    its country; failing that, the start of the address as printed."""
    seen = collections.Counter(
        (i.get("name"), i.get("country")) for a in authors
        for i in (a.get("oa") or {}).get("institutions") or [] if i.get("name"))
    if seen:
        return seen.most_common(1)[0][0]
    for a in authors:
        _key, addresses, american, in_uk, _c = B._author(a)
        if addresses:
            return addresses[0][:70], "US" if american else "GB" if in_uk else None
    return None, None


def _person(author):
    return f"{(author.get('first') or '').strip()} {(author.get('last') or '').strip()}".strip()


def main(folder, backtest, out, today=None):
    today = dt.date.fromisoformat(today) if today else dt.date.today()
    recent = today - dt.timedelta(days=365)
    data = B.load(folder)
    described = {p["id"]: B.describe(p, data) for p in data["papers"]}
    by_id = {p["id"]: p for p in data["papers"]}
    P.label(described.values(), P.industry(folder))
    tags = {pid: A.tag(row["text"]) for pid, row in described.items()}
    print(f"{len(by_id):,} papers to {max(p['date'] for p in data['papers'])}", flush=True)

    people = seniors(data)
    at_2020 = cohort(data, described, people, dt.date(2020, 12, 31))
    at_2022 = cohort(data, described, people, dt.date(2022, 12, 31))
    check = _check(at_2020, at_2022)
    now = cohort(data, described, people, today)
    share = _share(Ranker(at_2020 + at_2022, "lab").score(now))
    print(f"{len(now):,} lab heads active in the two years to {today}", flush=True)

    labs = []
    for row, place in zip(now, share):
        known, text = row["known"], row["text"]
        name, country = _institution(*(t[1] for t in reversed(known)))
        flags = [described[t[0]["id"]]["flags"] for t in known]
        dated = sorted({(k, when.isoformat(), label) for k, when, _d, label in row["records"]
                        if when <= today}, key=lambda r: r[1])
        labs.append({
            "id": row["id"], "name": (data["people"].get(row["id"]) or {}).get("name")
                                     or _person(known[-1][1]),
            "inst": name, "country": country, "n": len(known), "works": row["works"],
            "cited": row["cited"], "pct": float(place),
            "mods": [m for m, rule in MODALITIES.items()
                     if sum(bool(re.search(rule, described[t[0]["id"]]["text"], re.I))
                            for t in known) >= max(1, len(known) / 3)],
            "coi": [c[4:] for c in COI if any(f[c] for f in flags)],
            "stage": next((s for s in STAGE if any(f[s] for f in flags)), None),
            "before": [r for r in dated if r[1] <= recent.isoformat()],
            "after": [r for r in dated if r[1] > recent.isoformat()],
            "papers": [t[0]["id"] for t in known][-8:][::-1]})
    labs.sort(key=lambda lab: -lab["pct"])
    for place, lab in enumerate(labs, 1):
        lab["rank"] = place
    ranked = {lab["id"]: lab for lab in labs}

    scored = [r for r in described.values() if recent < by_id[r["id"]]["date"] <= today]
    feasible = P.ContentModel([r for r in described.values()
                               if r["year"] <= 2020 and r["clinical"] is not None], "clinical")
    pulled = P.ContentModel([r for r in described.values()
                             if r["year"] <= 2022 and r["industry"] is not None], "industry")
    company = Ranker([r for r in described.values()
                      if r["year"] <= 2022 and (r["us"] or r["uk"])], "company")
    clin = dict(zip((r["id"] for r in scored), _share(feasible.score(scored))))
    comm = dict(zip((r["id"] for r in scored), _share(pulled.score(scored))))
    local = [r for r in scored if r["us"] or r["uk"]]
    comp = dict(zip((r["id"] for r in local), _share(company.score(local))))

    # Areas: interest over time, growth, who works in them, and their best papers.
    two, four = today.replace(year=today.year - 2), today.replace(year=today.year - 4)
    ends = [dt.date(y, m, d) for y in range(2017, today.year + 1)
            for m, d in ((3, 31), (6, 30), (9, 30), (12, 31)) if dt.date(y, m, d) < today]
    ends = [e for e in ends if e >= dt.date(2017, 12, 31)] + [today]
    every = sorted(p["date"] for p in data["papers"])
    span = lambda dates, end: (np.searchsorted(dates, end, "right")                # noqa: E731
                               - np.searchsorted(dates, end - dt.timedelta(days=365), "right"))
    has_record = {row["id"]: any(when <= today for _k, when, _d, _l in row["records"])
                  for row in now}
    fresh = {lab["id"]: len(lab["after"]) for lab in labs}
    fields = []
    for name in A.AREAS:
        mine = [p for p in data["papers"] if name in tags[p["id"]]]
        dates = sorted(p["date"] for p in mine)
        latest = [p["id"] for p in mine if p["id"] in clin]
        heads = {aid for aid, theirs in people.items() if aid in ranked and any(
            two < t[0]["date"] <= today and name in tags[t[0]["id"]] for t in theirs)}
        recent_n = sum(two < d <= today for d in dates)
        before_n = sum(four < d <= two for d in dates)
        fields.append({
            "id": name, "name": name,
            "series": [{"d": e.isoformat(), "n": int(span(dates, e)),
                        "share": float(span(dates, e) / max(1, span(every, e)))} for e in ends],
            "now": recent_n, "then": before_n, "growth": recent_n / max(1, before_n),
            "year": len(latest), "heads": len(heads),
            "withrec": sum(has_record.get(a, False) for a in heads),
            "newRecs": sum(fresh.get(a, 0) for a in heads),
            "feasTop": float(np.mean([clin[i] >= 0.9 for i in latest])) if latest else None,
            "commTop": float(np.mean([comm[i] >= 0.9 for i in latest])) if latest else None,
            "topFeas": sorted(latest, key=lambda i: -clin[i])[:6],
            "topComm": sorted(latest, key=lambda i: -comm[i])[:6],
            "labs": sorted(heads, key=lambda a: ranked[a]["rank"])[:6]})

    # The top of the ranking; below it every lab head with a record in the last year, so
    # the feed of new records is whole, and each area's leading labs.
    wanted = {a for field in fields for a in field["labs"]}
    top = labs[:300] + [lab for lab in labs[300:] if lab["after"] or lab["id"] in wanted]
    keep = set()
    for places in (clin, comm, comp):
        keep |= {i for i, _ in sorted(places.items(), key=lambda x: -x[1])[:350]}
    keep |= {i for i in sorted(clin, key=lambda i: by_id[i]["date"], reverse=True)[:200]}
    for lab in top:
        keep |= set(lab["papers"])
    for field in fields:
        keep |= set(field["topFeas"]) | set(field["topComm"])
    papers = []
    for pid in keep:
        paper, row = by_id[pid], described[pid]
        authors = paper.get("authors") or []
        last = next((a for a in authors if (a.get("oa") or {}).get("position") == "last"),
                    authors[-1] if authors else {})
        name, country = _institution(last) if last else (None, None)
        flags = row["flags"]
        papers.append({
            "id": pid, "t": re.sub(r"<[^>]+>", "", paper.get("title") or ""),
            "d": paper["date"].isoformat(),
            "j": paper.get("journal") or ("Preprint" if paper.get("source") == "PPR" else None),
            "pre": paper.get("source") == "PPR", "pmid": paper.get("pmid"),
            "doi": paper.get("doi"), "first": _person(authors[0]) if authors else None,
            "last": _person(last) if last else None,
            "lastId": (last.get("oa") or {}).get("aid") if last else None,
            "nAu": len(authors), "inst": name, "country": country,
            "clin": float(clin[pid]) if pid in clin else None,
            "comm": float(comm[pid]) if pid in comm else None,
            "comp": float(comp[pid]) if pid in comp else None,
            "why": {"clin": feasible.reasons(row), "comm": pulled.reasons(row)}
                   if pid in clin else None,
            "areas": tags[pid],
            "mods": [m for m, rule in MODALITIES.items() if re.search(rule, row["text"], re.I)],
            "stage": [s for s in STAGE if flags[s]], "derisk": [s for s in DERISK if flags[s]],
            "coi": [c[4:] for c in COI if flags[c]], "co": bool(flags["company_author"]),
            "prior": [k for k in ("prior_award", "prior_filing", "prior_uk_company")
                      if flags[k]],
            "cited": None, "after": []})
    summary = {k: {"n": v["n"], "events": v["events"], "base": v["base"],
                   "scores": v["scores"]}
               for k, v in json.loads(pathlib.Path(backtest).read_text()).items()}
    print("\nthe paper scores, trained on 2017-18 and scored on 2019-20", flush=True)
    summary.update(P.run(list(described.values())))
    latest = lambda kind: max((r[1] for lab in labs for r in lab["before"] + lab["after"]  # noqa: E731
                               if r[0] == kind), default=None)
    json.dump({"mode": "live", "asOf": today.isoformat(), "since": recent.isoformat(),
               "labs": top, "labsTotal": len(labs), "papers": papers,
               "papersTotal": len(scored), "compTotal": len(comp), "summary": summary,
               "check": check, "areas": fields,
               "studies": {"clin": P.STUDIES[0][2], "comm": P.STUDIES[2][2]},
               "industryCitations": P.INDUSTRY_CITATIONS,
               "latest": {"paper": max(p["d"] for p in papers if p["d"] <= today.isoformat()),
                          "formd": latest("formd"),
                          "award": latest("award"), "uk": latest("uk")}},
              open(out, "w"), separators=(",", ":"))
    print(f"{len(top)} labs and {len(papers):,} papers written; "
          f"{len(scored):,} papers scored since {recent}", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:5])
