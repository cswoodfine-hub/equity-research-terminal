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

**OpenAlex**, where ``openalex/`` is in the data folder, adds an identifier per author,
the address of each author on a preprint (Europe PMC gives none, so with it preprints
join the company studies), the institution's country and type, and how much the last
author had published and been cited before the paper's year. OpenAlex gives an author's
totals as they stand today and by year, so the years from the paper's on are taken off.

**Labs.** A second test ranks people, not papers: everyone who was last or corresponding
author on a paper in the two years to a cutoff, described by all their papers to that
date, and scored on whether they themselves get a company record in the three years
after. Trained at the end of 2018, scored at the end of 2020.

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
    people = {}
    if (folder / "openalex" / "works.ndjson").exists():
        for line in (folder / "openalex" / "works.ndjson").open():
            record = json.loads(line)
            if record["id"] in papers:
                _attach(papers[record["id"]], record["authors"])
        people = {r["aid"]: r for r in map(json.loads,
                                           (folder / "openalex" / "authors.ndjson").open())}
    return {"papers": list(papers.values()), "icite": icite, "coi": coi, "awards": awards,
            "officers": officers, "owners": owners, "people": people}


def _attach(paper, theirs):
    """Give each of the paper's authors OpenAlex's record of them, matched on position and
    surname. A paper with no author list of its own takes OpenAlex's."""
    ours = paper.get("authors") or []
    if not ours:
        ours = paper["authors"] = [
            {"first": " ".join((a.get("name") or "").split()[:-1]),
             "last": (a.get("name") or " ").split()[-1], "affiliations": []} for a in theirs]
    names = [_norm(f"{a.get('raw_name') or ''} {a.get('name') or ''}") for a in theirs]
    taken = set()
    for i, author in enumerate(ours):
        last = _norm(author.get("last"))
        if len(last) < 2:
            continue
        order = ([i] if len(ours) == len(theirs) else []) + list(range(len(theirs)))
        for j in order:
            if j not in taken and last in names[j]:
                taken.add(j)
                author["oa"] = theirs[j]
                break


def _before(person, year):
    """(works, citations) OpenAlex credits a person with before ``year``."""
    if not person:
        return 0, 0
    works = (person.get("works") or 0) - sum(w or 0 for y, w, _c in person["by_year"]
                                             if y >= year)
    cited = (person.get("cited") or 0) - sum(c or 0 for y, _w, c in person["by_year"]
                                             if y >= year)
    return max(0, works), max(0, cited)


def _author(author):
    """(name key, addresses, at a US address, at a UK address, at a company)."""
    theirs = author.get("oa") or {}
    addresses = ([x.strip() for x in (author.get("affiliations") or []) if x]
                 or [x.strip() for x in theirs.get("addresses") or [] if x])
    countries = set(theirs.get("countries") or [])
    return (_name(author.get("first"), author.get("last")), addresses,
            "US" in countries or any(US_ADDRESS.search(x) for x in addresses),
            "GB" in countries or any(UK_ADDRESS.search(x) for x in addresses),
            any(i.get("type") == "company" for i in theirs.get("institutions") or []))


def _footprints(key, initial, addresses, american, in_uk, data):
    """The company records taken as this person's: (kind, date, detail), where detail is
    whether an award is about gene or cell therapy, or the day a UK company was formed."""
    found = []
    if american:
        found += [("sbir", start, about) for start, about, _o in data["awards"].get(key) or ()]
        states = _states(addresses)
        found += [("formd", when, True)
                  for when, where, theirs, _issuer in data["officers"].get(key) or ()
                  if states & where or (initial and initial == theirs)]
    if in_uk:
        text = " ".join(addresses).lower()
        found += [("uk", notified, born)
                  for notified, born, town, titled, _c in data["owners"].get(key) or ()
                  if titled or (town and town in text)]
    return found


def _split(records, date, until):
    """The kinds of record a person had by ``date`` and gained by ``until``. A UK company
    counts as gained only if it was formed after the date."""
    had = {kind for kind, when, _d in records if when <= date}
    later = {kind for kind, when, detail in records
             if date < when <= until and (detail > date if kind == "uk" else detail)}
    return had, later


def describe(paper, data):
    """The outcomes and the day-one rule flags for one paper."""
    icite, coi, awards = data["icite"], data["coi"], data["awards"]
    date = paper["date"]
    until = date + dt.timedelta(days=HORIZON_DAYS)
    # A company record can only be seen for a paper with a named author at a US or UK
    # address: the awards and Form D are American, the ownership register British.
    eligible = british = at_company = False
    before = after = after_new = False
    filed_before = filed = owned_before = owned = fresh = False
    senior = most = (0, 0)
    for author in paper.get("authors") or []:
        key, addresses, american, in_uk, commercial = _author(author)
        at_company |= commercial
        theirs = author.get("oa") or {}
        record = _before(data["people"].get(theirs.get("aid")), date.year)
        most = max(most, record)
        if theirs.get("position") == "last":
            senior = record
        if not key or not (american or in_uk):
            continue
        eligible |= american
        british |= in_uk
        had, later = _split(_footprints(key, _initial(author.get("first")), addresses,
                                        american, in_uk, data), date, until)
        before |= "sbir" in had
        after |= "sbir" in later
        after_new |= "sbir" in later and "sbir" not in had
        filed_before |= "formd" in had
        filed |= "formd" in later
        owned_before |= "uk" in had
        owned |= "uk" in later
        fresh |= bool(later) and not had
    record = icite.get(str(paper.get("pmid") or ""))
    clinical = None
    if record is not None:
        clinical = any(y is not None and date.year <= y <= date.year + 3
                       for y in record.get("clin_years") or [])
    affiliations = " ; ".join(x for a in paper.get("authors") or []
                              for x in (a.get("affiliations") or []) if x)
    affiliations = affiliations or (paper.get("affiliation") or "")
    company = at_company or any(COMPANY.search(part) and not NOT_COMPANY.search(part)
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
    flags["senior_works"] = float(np.log1p(senior[0]))
    flags["senior_cited"] = float(np.log1p(senior[1]))
    flags["most_cited_author"] = float(np.log1p(most[1]))
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


def evaluate(rows, outcome, where, out, floor=("authors_log", "author count (floor)")):
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
    scores[floor[1]] = np.array([r["flags"][floor[0]] for r in test])
    base = y_test.mean()
    print(f"  scored {len(test):,}, events {int(y_test.sum())}, base rate {base:.1%}"
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


def labs(data, described):
    """One row per lab head and cutoff: what was known of them at the cutoff, and whether
    they gained a company record in the three years after."""
    flags_of = {r["id"]: r for r in described}
    people = collections.defaultdict(list)
    for paper in data["papers"]:
        for author in paper.get("authors") or []:
            theirs = author.get("oa") or {}
            key, addresses, american, in_uk, _c = _author(author)
            if (theirs.get("aid") and key and (american or in_uk)
                    and (theirs.get("position") == "last" or theirs.get("corresponding"))):
                people[theirs["aid"]].append((paper, key, _initial(author.get("first")),
                                              addresses, american, in_uk))
    rows = []
    for year in (2018, 2020):
        cutoff = dt.date(year, 12, 31)
        until = cutoff + dt.timedelta(days=HORIZON_DAYS)
        for aid, theirs in people.items():
            known = [t for t in theirs if t[0]["date"] <= cutoff]
            if not any(t[0]["date"].year >= year - 1 for t in known):
                continue
            records = set()
            for _paper, key, initial, addresses, american, in_uk in known:
                records |= set(_footprints(key, initial, addresses, american, in_uk, data))
            had, later = _split(records, cutoff, until)
            papers = [flags_of[t[0]["id"]] for t in known]
            flags = {name: float(np.mean([p["flags"][name] for p in papers]))
                     for name in papers[0]["flags"]
                     if name not in ("authors_log", "senior_works", "senior_cited",
                                     "most_cited_author", "prior_award", "prior_filing",
                                     "prior_uk_company")}
            works, cited = _before(data["people"].get(aid), year + 1)
            flags.update({
                "papers_log": float(np.log1p(len(known))),
                "works_log": float(np.log1p(works)), "cited_log": float(np.log1p(cited)),
                "prior_award": int("sbir" in had), "prior_filing": int("formd" in had),
                "prior_uk_company": int("uk" in had)})
            rows.append({
                "text": " ".join(p["text"] for p in papers)[:20000], "flags": flags,
                "year": year, "apt": None, "id": aid,
                "title": f"{(data['people'].get(aid) or {}).get('name') or aid}"
                         f" ({len(known)} papers)",
                "lab": bool(later), "lab_new": bool(later) and not had, "had": bool(had)})
    return rows


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
    if data["people"]:
        heads = labs(data, rows)
        print(f"\n{len({r['id'] for r in heads}):,} lab heads at a US or UK address")
        for outcome, label, where in (
                ("lab", "lab heads: any company record in the next 3 years", lambda r: True),
                ("lab_new", "lab heads with no company record yet: a first one",
                 lambda r: not r["had"])):
            print(f"\n{label}")
            out = []
            evaluate(heads, outcome, where, out, floor=("papers_log", "paper count (floor)"))
            if out:
                report[label] = out[0]
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv)
