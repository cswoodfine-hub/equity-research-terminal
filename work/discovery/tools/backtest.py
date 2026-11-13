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
- ``formd``: an author at a US address is named as an executive officer, director or
  promoter on an SEC Form D filed after the paper by an issuer that gives its industry as
  biotechnology or pharmaceuticals. A shared name is not enough: the filing's state has to
  be one the author's address names, or the middle initials have to agree.
- ``uk_company``: an author at a UK address is a person with significant control of a UK
  company registered under a biotechnology, pharmaceutical or natural-science research
  code and incorporated after the paper. The company's town has to be in the author's
  address, or the register has to title the person Dr or Professor. Companies House
  publishes only live companies and only holders of 25% or more, so this undercounts:
  a founder diluted below 25%, or a company since dissolved, is not seen.
- ``company``: any of the three. ``company_new`` counts only authors with no company
  record of any of the three kinds before the paper.

**Features, all knowable on the day:** words of the title and abstract; rule flags for the
model the work reached and for CGT de-risking terms; a company among the affiliations; an
author already holding a small-business award; phrases of the conflict-of-interest
statement. MeSH terms are not used: they are assigned months later.

**Split.** Trained on 2017 and 2018, scored on 2019 and 2020.

**Baselines.** iCite's ``apt``, computed from today's record, citations since
publication included, so it is a harder baseline than a day-one score would face. And the
number of authors alone: every company outcome is found by matching author names, so a
long author list raises the hit rate whatever the paper says.

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
_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
    "ohio": "OH", "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", "tennessee": "TN",
    "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY"}
UK_ADDRESS = re.compile(r"\bUK\b|United Kingdom|\bU\.K\.|England|Scotland|\bWales\b|"
                        r"Northern Ireland")
ACADEMIC_TITLE = re.compile(r"^(dr|prof|professor)\.?$", re.I)
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


def _states(addresses):
    """The US states a set of addresses names, as two-letter codes."""
    found = set()
    for address in addresses:
        found |= set(re.findall(r",\s*(" + _STATES + r")\b", address))
        low = address.lower()
        found |= {code for name, code in _STATE_NAMES.items() if name in low}
    return found


def _initial(first, middle=""):
    """The middle initial, from a middle name or from a first name that carries it."""
    middle = (middle or "").strip()
    parts = (first or "").split()
    return (middle[:1] or (parts[1][:1] if len(parts) > 1 else "")).upper()


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
    officers = collections.defaultdict(list)     # name -> [(filed, states, initial, issuer)]
    if (folder / "formd.ndjson").exists():
        for line in (folder / "formd.ndjson").open():
            f = json.loads(line)
            filed = _date(f.get("filed"))
            if not filed:
                continue
            for person in f.get("people") or []:
                key = _name(person.get("first"), person.get("last"))
                if key:
                    officers[key].append((filed, {person.get("state"), f.get("state")},
                                          _initial(person.get("first"), person.get("middle")),
                                          f.get("issuer")))
    owners = collections.defaultdict(list)       # name -> [(notified, incorporated, ...)]
    if (folder / "uk.ndjson").exists():
        for line in (folder / "uk.ndjson").open():
            c = json.loads(line)
            try:
                born = dt.datetime.strptime(c.get("incorporated") or "", "%d/%m/%Y").date()
            except ValueError:
                continue
            for person in c.get("psc") or []:
                key = _name(person.get("first"), person.get("last"))
                notified = _date(person.get("notified"))
                if key and notified and "individual" in (person.get("kind") or ""):
                    owners[key].append((notified, born, (c.get("post_town") or "").lower(),
                                        bool(ACADEMIC_TITLE.match(person.get("title") or "")),
                                        c.get("name")))
    return {"papers": list(papers.values()), "icite": icite, "coi": coi, "awards": awards,
            "officers": officers, "owners": owners}


def describe(paper, data):
    """The outcomes and the day-one rule flags for one paper."""
    icite, coi, awards = data["icite"], data["coi"], data["awards"]
    date = paper["date"]
    until = date + dt.timedelta(days=HORIZON_DAYS)
    # A company record can only be seen for a paper with a named author at a US or UK
    # address: the awards and Form D are American, the ownership register British.
    eligible = british = False
    before = after = after_new = False
    filed_before = filed = owned_before = owned = fresh = False
    for author in paper.get("authors") or []:
        addresses = [x.strip() for x in (author.get("affiliations") or []) if x]
        american = any(US_ADDRESS.search(x) for x in addresses)
        in_uk = any(UK_ADDRESS.search(x) for x in addresses)
        key = _name(author.get("first"), author.get("last"))
        if not key or not (american or in_uk):
            continue
        eligible |= american
        british |= in_uk
        had = later = had_filing = later_filing = had_company = later_company = False
        if american:
            mine = awards.get(key) or ()
            had = any(start <= date for start, _a, _o in mine)
            later = any(date < start <= until and about for start, about, _o in mine)
            states, initial = _states(addresses), _initial(author.get("first"))
            for when, where, theirs, _issuer in data["officers"].get(key) or ():
                if not (states & where or (initial and initial == theirs)):
                    continue
                had_filing |= when <= date
                later_filing |= date < when <= until
        if in_uk:
            text = " ".join(addresses).lower()
            for notified, born, town, titled, _company in data["owners"].get(key) or ():
                if not (titled or (town and town in text)):
                    continue
                had_company |= notified <= date
                later_company |= born > date and date < notified <= until
        before |= had
        after |= later
        after_new |= later and not had
        filed_before |= had_filing
        filed |= later_filing
        owned_before |= had_company
        owned |= later_company
        fresh |= ((later or later_filing or later_company)
                  and not (had or had_filing or had_company))
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
    flags["prior_filing"] = int(filed_before)
    flags["prior_uk_company"] = int(owned_before)
    flags["us_author"] = int(eligible)
    flags["uk_author"] = int(british)
    flags["preprint"] = int(paper.get("source") == "PPR")
    flags["authors_log"] = float(np.log1p(len(paper.get("authors") or [])))
    types = " ".join(paper.get("pub_types") or [])
    return {"text": text, "flags": flags, "year": date.year,
            "clinical": clinical, "sbir": after, "sbir_new": after_new,
            "formd": filed, "uk_company": owned,
            "company": after or filed or owned, "company_new": fresh,
            "apt": (record or {}).get("apt"),
            "is_clinical_paper": bool((record or {}).get("is_clinical"))
                                 or any(t in types for t in CLINICAL_TYPES),
            "academic": not (company or before or filed_before or owned_before),
            "us": eligible, "uk": british,
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
    # A paper with more authors has more names that can match a company record, by chance
    # or not, so the count alone is the floor any company outcome has to clear.
    scores["author count (floor)"] = np.array([r["flags"]["authors_log"] for r in test])
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
    data = load(argv[1])
    rows = [describe(p, data) for p in data["papers"]]
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
        ("sbir_new", "the same, academic US papers only (no company author, no prior"
                     " company record)", lambda r: r["us"] and r["academic"]),
        ("formd", "an author named on a later biotech Form D, US papers", lambda r: r["us"]),
        ("uk_company", "an author owning a new UK research company, UK papers",
         lambda r: r["uk"]),
        ("company", "any company record (award, Form D, UK company), US and UK papers",
         lambda r: r["us"] or r["uk"]),
        ("company_new", "an author's first company record, US and UK papers",
         lambda r: r["us"] or r["uk"]),
        ("company_new", "the same, academic papers only",
         lambda r: (r["us"] or r["uk"]) and r["academic"]),
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
