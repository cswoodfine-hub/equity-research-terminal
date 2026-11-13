"""Step 1 backtest: can a score built from what a paper says on publication day put the
papers that later led somewhere at the top of the list?

**Papers.** CGT research papers first published 2017 to 2020 (``corpus.py``), with an
abstract, less editorials, comments, letters and errata.

**Outcomes, each within three years of publication:**
- ``clinical``: cited by a clinical article (iCite ``cited_by_clin``, by year).
- ``sbir``: an author at a US address is an investigator on an NIH small-business award
  (SBIR or STTR) that starts after the paper and is about gene or cell therapy, matched
  on full first name and last name. ``sbir_new`` counts only investigators with no such
  award before the paper: new commercial activity. The awards are American, so these
  studies take only papers with a named author at a US address. Europe PMC gives
  preprints no per-author address, so preprints fall out of them.

**Features, all knowable on the day:** words of the title and abstract; rule flags for the
model the work reached and for CGT de-risking terms; a company among the affiliations; an
author already holding a small-business award; phrases of the conflict-of-interest
statement. MeSH terms are not used: they are assigned months later.

**Split.** Trained on 2017 and 2018, scored on 2019 and 2020.

**Baseline.** iCite's ``apt``. It is computed from today's record, citations since
publication included, so it is a harder baseline than a day-one score would face.

    python3 work/discovery/tools/backtest.py <data folder> [--json out]
"""

import collections
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

HORIZON_DAYS = 3 * 365
NOT_RESEARCH = {"Editorial", "Comment", "Letter", "News", "Published Erratum",
                "Retraction of Publication", "Biography", "Interview", "Review",
                "Systematic Review", "Meta-Analysis", "Congress"}
CLINICAL_TYPES = ("Clinical Trial", "Randomized Controlled Trial", "Observational Study",
                  "Case Reports", "Clinical Study")
# What marks a small-business award as gene or cell therapy, so a shared name alone is
# never a match.
CGT_AWARD = re.compile(
    r"gene therap|cell therap|cell-based therap|gene transfer|\baav\b|adeno-associated|"
    r"lentivir|viral vector|car[- ]t\b|chimeric antigen|crispr|genome edit|gene edit|"
    r"base edit|prime edit|lipid nanoparticle|transduc|transgene|\bipsc|gene delivery|"
    r"adoptive cell|engineered t cell|cell transplant", re.I)
# The award is American, so the matched author has to be at a US address on the paper.
# Without this, over half the matches were authors abroad sharing a common name with a US
# investigator (checked 2026-11-13: 301 of 574).
_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
           "MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY")
US_ADDRESS = re.compile(r"\bUSA\b|United States|U\.S\.A|,\s*(" + _STATES + r")\b[\s,.\d-]*$|"
                        r",\s*(" + _STATES + r")\s+\d{5}")
COMPANY = re.compile(
    r"\b(inc|llc|ltd|gmbh|corp|corporation|s\.a\.|therapeutics|pharmaceuticals?|"
    r"biosciences?|biotherapeutics|biotech(nology|nologies)?|pharma|genomics)\b\.?", re.I)
NOT_COMPANY = re.compile(r"universit|hospital|institut|school|college|center|centre|"
                         r"academy|department of", re.I)
RULES = {
    "mouse": r"\bmice\b|\bmouse\b|\bmurine\b",
    "large_animal": r"\bpigs?\b|\bporcine\b|\bdogs?\b|\bcanine\b|\bsheep\b|\bovine\b",
    "primate": r"non-?human primate|\bnhps?\b|macaque|cynomolgus|rhesus",
    "human_cells": r"patient-derived|primary human|human ipsc|organoid|human donor",
    "patients": r"\bpatients\b|phase (i|1|ii|2)\b|clinical trial|first-in-human",
    "in_vivo": r"in vivo",
    "dose": r"vg/kg|vector genomes?|dose[- ]dependent|dose[- ]response|dose escalation",
    "biodistribution": r"biodistribution",
    "immunogenicity": r"neutrali[sz]ing antibod|immunogenic|pre-existing immunity",
    "off_target": r"off-target|guide-seq|genotoxic|insertional",
    "manufacturing": r"\bgmp\b|manufactur|scal(e|able) (up|production)|large-scale",
    "durability": r"long-term|durable|sustained expression|persisten",
    "safety": r"\btoxicit|\bsafety\b|well tolerated",
    "efficacy": r"\befficacy\b|therapeutic (effect|benefit)|rescue[ds]?\b|survival",
    "novel": r"\bnovel\b|first time|new class|engineered",
    "platform": r"\bplatform\b|versatile|broadly applicable|modular",
    "capsid": r"capsid|serotype|tropism",
    "delivery": r"deliver",
}
COI_RULES = {
    "coi_founder": r"founder|co-founder|cofounder",
    "coi_equity": r"equity|stock|shares|shareholder|ownership",
    "coi_patent": r"patent|inventor|licens",
    "coi_employee": r"employee|employed by|employment",
    "coi_advisor": r"advisory board|consult|advisor",
}


def _norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text.lower())


def _date(text):
    try:
        return dt.date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


def _name(first, last):
    """(first name, last name) as a key, or None where the first name is an initial."""
    first = _norm((first or "").split(" ")[0])
    last = _norm(last)
    return (first, last) if len(first) >= 3 and len(last) >= 2 else None


def load(folder):
    folder = pathlib.Path(folder)
    papers = {}
    for path in sorted(folder.glob("corpus/*.ndjson")):
        for line in path.open():
            r = json.loads(line)
            date = _date(r.get("first_date"))
            if (not date or not r.get("abstract") or len(r["abstract"]) < 200
                    or set(r.get("pub_types") or []) & NOT_RESEARCH):
                continue
            r["date"] = date
            papers.setdefault(r["id"], r)
    icite = {}
    if (folder / "icite.ndjson").exists():
        icite = {r["pmid"]: r for r in map(json.loads, (folder / "icite.ndjson").open())}
    coi = {}
    if (folder / "coi.ndjson").exists():
        coi = {r["pmid"]: r["coi"] for r in map(json.loads, (folder / "coi.ndjson").open())}
    awards = collections.defaultdict(list)       # name -> [(start, is CGT, org)]
    for line in (folder / "sbir.ndjson").open():
        a = json.loads(line)
        start = _date(a.get("start") or a.get("notice"))
        if not start:
            continue
        about = bool(CGT_AWARD.search(f"{a.get('title') or ''} {a.get('terms') or ''}"))
        for pi in a.get("pis") or []:
            key = _name(pi.get("first"), pi.get("last"))
            if key:
                awards[key].append((start, about, a.get("org")))
    return list(papers.values()), icite, coi, awards


def describe(paper, icite, coi, awards):
    """The outcomes and the day-one rule flags for one paper."""
    date = paper["date"]
    until = date + dt.timedelta(days=HORIZON_DAYS)
    names = {_name(a.get("first"), a.get("last")) for a in paper.get("authors") or []
             if any(US_ADDRESS.search(x.strip()) for x in (a.get("affiliations") or []) if x)}
    names.discard(None)
    # The award outcome can only be seen for a paper with a named author at a US address.
    eligible = bool(names)
    before = after = after_new = False
    for key in names:
        mine = awards.get(key) or ()
        had = any(start <= date for start, _a, _o in mine)
        later = any(date < start <= until and about for start, about, _o in mine)
        before |= had
        after |= later
        after_new |= later and not had
    record = icite.get(str(paper.get("pmid") or ""))
    clinical = None
    if record is not None:
        clinical = any(y is not None and date.year <= y <= date.year + 3
                       for y in record.get("clin_years") or [])
    affiliations = " ; ".join(x for a in paper.get("authors") or []
                              for x in (a.get("affiliations") or []) if x)
    affiliations = affiliations or (paper.get("affiliation") or "")
    company = any(COMPANY.search(part) and not NOT_COMPANY.search(part)
                  for part in re.split(r";", affiliations))
    text = f"{paper.get('title') or ''}. {paper.get('abstract') or ''}"
    flags = {name: int(bool(re.search(rule, text, re.I))) for name, rule in RULES.items()}
    stated = coi.get(str(paper.get("pmid") or ""), "")
    flags.update({name: int(bool(re.search(rule, stated, re.I)))
                  for name, rule in COI_RULES.items()})
    flags["company_author"] = int(company)
    flags["prior_award"] = int(before)
    flags["preprint"] = int(paper.get("source") == "PPR")
    flags["authors_log"] = float(np.log1p(len(paper.get("authors") or [])))
    types = " ".join(paper.get("pub_types") or [])
    return {"text": text, "flags": flags, "year": date.year,
            "clinical": clinical, "sbir": after, "sbir_new": after_new,
            "apt": (record or {}).get("apt"),
            "is_clinical_paper": bool((record or {}).get("is_clinical"))
                                 or any(t in types for t in CLINICAL_TYPES),
            "academic": not company and not before, "us": eligible,
            "id": paper["id"], "title": paper.get("title")}


def _top(scores, labels, share):
    order = np.argsort(-scores, kind="stable")
    k = max(1, int(round(len(scores) * share)))
    hits = labels[order[:k]].sum()
    return hits / k, hits / max(1, labels.sum())


def evaluate(rows, outcome, where, out):
    """Train on 2017-18, score 2019-20, and report the top of the list."""
    rows = [r for r in rows if r[outcome] is not None and where(r)]
    train = [r for r in rows if r["year"] <= 2018]
    test = [r for r in rows if r["year"] >= 2019]
    y_train = np.array([int(r[outcome]) for r in train])
    y_test = np.array([int(r[outcome]) for r in test])
    if y_train.sum() < 15 or y_test.sum() < 15:
        print(f"  too few events to judge (train {y_train.sum()}, test {y_test.sum()})")
        return None
    names = sorted(train[0]["flags"])
    scaler = StandardScaler().fit([[r["flags"][n] for n in names] for r in train])
    f_train = scaler.transform([[r["flags"][n] for n in names] for r in train])
    f_test = scaler.transform([[r["flags"][n] for n in names] for r in test])
    words = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_df=0.6, sublinear_tf=True,
                            stop_words="english", max_features=200_000)
    w_train = words.fit_transform([r["text"] for r in train])
    w_test = words.transform([r["text"] for r in test])

    def fit(a, b, c=1.0):
        model = LogisticRegression(C=c, class_weight="balanced", max_iter=2000)
        model.fit(a, y_train)
        return model, model.decision_function(b)

    rules_model, rules = fit(f_train, f_test, 0.3)
    _m, text = fit(w_train, w_test)
    _m, both = fit(sparse.hstack([w_train, sparse.csr_matrix(f_train)]).tocsr(),
                   sparse.hstack([w_test, sparse.csr_matrix(f_test)]).tocsr())
    scores = {"rules": rules, "words": text, "rules + words": both}
    apt = np.array([r["apt"] if r["apt"] is not None else np.nan for r in test], float)
    if np.isfinite(apt).mean() > 0.9:
        scores["iCite apt (baseline)"] = np.nan_to_num(apt, nan=-1.0)
    base = y_test.mean()
    print(f"  papers scored {len(test):,}, events {int(y_test.sum())}, base rate {base:.1%}"
          f" (trained on {len(train):,} with {int(y_train.sum())})")
    result = {"n": len(test), "events": int(y_test.sum()), "base": float(base), "scores": {}}
    for name, s in scores.items():
        cells = []
        for share in (0.01, 0.05, 0.10):
            precision, recall = _top(s, y_test, share)
            cells.append((share, precision, recall))
        auc = roc_auc_score(y_test, s)
        result["scores"][name] = {"auc": float(auc), "top": [
            {"share": sh, "precision": float(p), "lift": float(p / base),
             "captured": float(rc)} for sh, p, rc in cells]}
        print(f"    {name:22} AUC {auc:.3f} | " + " | ".join(
            f"top {sh:.0%}: {p:.0%} hit, {p / base:.1f}x, {rc:.0%} of events"
            for sh, p, rc in cells))
    weights = sorted(zip(rules_model.coef_[0], names), reverse=True)
    result["rule_weights"] = [(n, round(float(w), 3)) for w, n in weights]
    print("    strongest rule flags: " + ", ".join(f"{n} {w:+.2f}" for w, n in weights[:6])
          + " ... weakest: " + ", ".join(f"{n} {w:+.2f}" for w, n in weights[-3:]))
    order = np.argsort(-both, kind="stable")[:15]
    result["examples"] = [{"title": test[i]["title"], "id": test[i]["id"],
                           "event": bool(y_test[i])} for i in order]
    out.append(result)
    return result


def main(argv):
    papers, icite, coi, awards = load(argv[1])
    rows = [describe(p, icite, coi, awards) for p in papers]
    print(f"{len(rows):,} research papers and preprints, 2017 to 2020; "
          f"{sum(r['clinical'] is not None for r in rows):,} with an iCite record; "
          f"{sum(bool(r['flags']['coi_founder'] or r['flags']['coi_equity']) for r in rows):,}"
          f" stating a founder or equity interest")
    report = {}
    studies = [
        ("clinical", "cited by a clinical article within 3 years, all papers", lambda r: True),
        ("clinical", "the same, papers that are not themselves clinical",
         lambda r: not r["is_clinical_paper"] and not r["flags"]["patients"]),
        ("sbir", "an author on a later CGT small-business award, US papers",
         lambda r: r["us"]),
        ("sbir_new", "an author's first small-business award, US papers", lambda r: r["us"]),
        ("sbir_new", "the same, academic US papers only (no company author, no prior award)",
         lambda r: r["us"] and r["academic"]),
    ]
    for outcome, label, where in studies:
        print(f"\n{label}")
        out = []
        evaluate(rows, outcome, where, out)
        if out:
            report[label] = out[0]
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv)
