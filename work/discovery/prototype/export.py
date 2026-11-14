"""The data behind the Discovery tab prototype: the backtest's scored 2019-20 papers and the
lab heads as ranked at the end of 2020, with each one's company records before and after.

    python3 work/discovery/prototype/export.py <data folder> <out.json>

The page is ``template.html`` with ``__DATA__`` replaced by that file's text. Nothing here
is app code: it is the mock-up the front-end plan in ``PLAN.md`` is drawn from.
"""
import sys, json, re, collections, datetime as dt
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import backtest as B

S = sys.argv[1]
data = B.load(S)
rows = [B.describe(p, data) for p in data["papers"]]
by_id = {p["id"]: p for p in data["papers"]}

def fit(rows, outcome, where):
    rows = [r for r in rows if r[outcome] is not None and where(r)]
    train = [r for r in rows if r["year"] <= 2018]; test = [r for r in rows if r["year"] >= 2019]
    y = np.array([int(r[outcome]) for r in train])
    names = sorted(train[0]["flags"])
    sc = StandardScaler().fit([[r["flags"][n] for n in names] for r in train])
    ft, fs = (sc.transform([[r["flags"][n] for n in names] for r in rs]) for rs in (train, test))
    tv = TfidfVectorizer(ngram_range=(1, 2), min_df=5, max_df=0.6, sublinear_tf=True, stop_words="english", max_features=200_000)
    wt, ws = tv.fit_transform([r["text"] for r in train]), tv.transform([r["text"] for r in test])
    m = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000)
    m.fit(sparse.hstack([wt, sparse.csr_matrix(ft)]).tocsr(), y)
    s = m.decision_function(sparse.hstack([ws, sparse.csr_matrix(fs)]).tocsr())
    rank = s.argsort().argsort()            # 0 = lowest
    pct = (rank + 1) / len(s)               # 1.0 = top
    return {r["id"]: float(p) for r, p in zip(test, pct)}

clin = fit(rows, "clinical", lambda r: True)
comp = fit(rows, "company", lambda r: r["us"] or r["uk"])
heads = B.labs(data, rows)
labscore = fit(heads, "lab", lambda r: True)

MOD = {"AAV": r"\baav\d*\b|adeno-associated", "Lentiviral": r"lentivir|retrovir",
       "CAR-T": r"car[- ]t\b|chimeric antigen|tcr[- ]t\b|car[- ]nk",
       "Cell therapy": r"cell therap|ipsc|pluripotent|mesenchymal|stem cell transplant|adoptive cell",
       "Gene editing": r"crispr|cas9|cas12|base edit|prime edit|genome edit|gene edit|talen\b|zinc[- ]finger",
       "LNP / mRNA": r"lipid nanoparticle|\blnps?\b|\bmrna\b"}
def mods(text): return [k for k, v in MOD.items() if re.search(v, text, re.I)]
STAGE = ["patients", "primate", "large_animal", "mouse", "human_cells"]
DERISK = ["dose", "biodistribution", "immunogenicity", "off_target", "manufacturing", "durability"]
COI = ["coi_founder", "coi_equity", "coi_patent", "coi_employee", "coi_advisor"]

def records(author, addresses, american, in_uk):
    key = B._name(author.get("first"), author.get("last")); out = []
    if not key: return out
    if american:
        out += [("award", s, about, org) for s, about, org in data["awards"].get(key) or ()]
        st, ini = B._states(addresses), B._initial(author.get("first"))
        out += [("formd", w, True, issuer) for w, where, theirs, issuer in data["officers"].get(key) or () if st & where or (ini and ini == theirs)]
    if in_uk:
        text = " ".join(addresses).lower()
        out += [("uk", n, born, co) for n, born, town, titled, co in data["owners"].get(key) or () if titled or (town and town in text)]
    return out

def inst(author):
    oa = author.get("oa") or {}
    i = (oa.get("institutions") or [{}])[0]
    return i.get("name"), i.get("country")

CUT = dt.date(2020, 12, 31); UNTIL = CUT + dt.timedelta(days=B.HORIZON_DAYS)
people = collections.defaultdict(list)
for p in data["papers"]:
    for a in p.get("authors") or []:
        oa = a.get("oa") or {}
        key, addresses, american, in_uk, _c = B._author(a)
        if oa.get("aid") and key and (american or in_uk) and (oa.get("position") == "last" or oa.get("corresponding")):
            people[oa["aid"]].append((p, a, addresses, american, in_uk))
rowmap = {r["id"]: r for r in rows}
labs = []
for h in heads:
    if h["year"] != 2020: continue
    aid = h["id"]; known = sorted([t for t in people[aid] if t[0]["date"] <= CUT], key=lambda t: t[0]["date"])
    recs = set()
    for p, a, addresses, american, in_uk in known:
        recs |= set(records(a, addresses, american, in_uk))
    before = sorted({(k, d.isoformat(), lab) for k, d, det, lab in recs if d <= CUT}, key=lambda x: x[1])
    after = sorted({(k, d.isoformat(), lab) for k, d, det, lab in recs if CUT < d <= UNTIL and (det > CUT if k == "uk" else det)}, key=lambda x: x[1])
    text = " ".join(rowmap[t[0]["id"]]["text"] for t in known)
    name, country = inst(known[-1][1])
    works, cited = B._before(data["people"].get(aid), 2021)
    fl = [rowmap[t[0]["id"]]["flags"] for t in known]
    labs.append({"id": aid, "name": (data["people"].get(aid) or {}).get("name") or aid, "inst": name, "country": country,
                 "n": len(known), "works": works, "cited": cited, "pct": labscore[aid],
                 "mods": [m for m in MOD if sum(bool(re.search(MOD[m], rowmap[t[0]["id"]]["text"], re.I)) for t in known) >= max(1, len(known) / 3)],
                 "coi": [c[4:] for c in COI if any(f[c] for f in fl)],
                 "stage": next((s for s in STAGE if any(f[s] for f in fl)), None),
                 "before": before, "after": after, "papers": [t[0]["id"] for t in known][-8:][::-1]})
labs.sort(key=lambda l: -l["pct"])
print("labs at cutoff", len(labs), "with after", sum(bool(l["after"]) for l in labs))
top_labs = labs[:300]

keep = set()
test = [r for r in rows if r["year"] >= 2019]
for ids, n in ((clin, 350), (comp, 350)):
    keep |= {i for i, _ in sorted(ids.items(), key=lambda x: -x[1])[:n]}
for l in top_labs: keep |= set(l["papers"])
papers = []
for pid in keep:
    p, r = by_id[pid], rowmap[pid]
    au = p.get("authors") or []
    def nm(a): return f"{(a.get('first') or '').strip()} {(a.get('last') or '').strip()}".strip()
    last = next((a for a in au if (a.get("oa") or {}).get("position") == "last"), au[-1] if au else {})
    name, country = inst(last) if last else (None, None)
    after = set()
    until = p["date"] + dt.timedelta(days=B.HORIZON_DAYS)
    for a in au:
        key, addresses, american, in_uk, _c = B._author(a)
        if not (american or in_uk): continue
        for k, d, det, lab in records(a, addresses, american, in_uk):
            if p["date"] < d <= until and (det > p["date"] if k == "uk" else det):
                after.add((k, d.isoformat(), lab, nm(a)))
    f = r["flags"]
    papers.append({"id": pid, "t": re.sub(r"<[^>]+>", "", p.get("title") or ""), "d": p["date"].isoformat(), "j": p.get("journal") or ("Preprint" if p.get("source") == "PPR" else None),
                   "pre": p.get("source") == "PPR", "pmid": p.get("pmid"), "doi": p.get("doi"),
                   "first": nm(au[0]) if au else None, "last": nm(last) if last else None, "lastId": (last.get("oa") or {}).get("aid") if last else None,
                   "nAu": len(au), "inst": name, "country": country,
                   "clin": clin.get(pid), "comp": comp.get(pid),
                   "mods": mods(r["text"]), "stage": [s for s in STAGE if f[s]], "derisk": [s for s in DERISK if f[s]],
                   "coi": [c[4:] for c in COI if f[c]], "co": bool(f["company_author"]),
                   "prior": [k for k in ("prior_award", "prior_filing", "prior_uk_company") if f[k]],
                   "cited": r["clinical"], "after": sorted(after, key=lambda x: x[1])})
print("papers", len(papers), "test rows", len(test))
bt = json.load(open(S + "/backtest3.json"))
summary = {k: {"n": v["n"], "events": v["events"], "base": v["base"], "scores": v["scores"]} for k, v in bt.items()}
out = {"labs": top_labs, "labsTotal": len(labs), "papers": papers, "papersTotal": len(test), "compTotal": len(comp), "summary": summary}
json.dump(out, open(sys.argv[2], "w"), separators=(",", ":"), default=str)
