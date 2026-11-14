"""Figure data, part 1: topics (growth against company share), rising phrases, founder
co-authors, institutions and stage by modality.

    python3 work/discovery/prototype/figures/analyse.py <data folder> <figs.json>
"""
import sys, json, re, collections, datetime as dt, itertools
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import numpy as np
import backtest as B, live as L
S = sys.argv[1]; TODAY = dt.date(2026, 11, 14)
data = B.load(S)
papers = data["papers"]
text = {p["id"]: (f"{p.get('title') or ''}. {p.get('abstract') or ''}").lower() for p in papers}
TOPICS = {
 "In vivo CAR-T": r"in vivo (car\b|chimeric)|in vivo.{0,40}(generat|engineer|program|produc)\w*.{0,30}(car[- ]t|car t cells|chimeric antigen)|in situ.{0,30}car[- ]t",
 "Allogeneic cells": r"allogeneic|off-the-shelf|universal car",
 "NK cell therapy": r"car[- ]nk|natural killer",
 "TCR-T": r"tcr[- ]t\b|tcr-engineered|t cell receptor[- ](engineered|gene)",
 "TIL therapy": r"tumou?r[- ]infiltrating lymphocyte",
 "CAR-T, solid tumours": r"(car[- ]t|chimeric antigen).{0,200}solid tumou?r|solid tumou?r.{0,200}(car[- ]t|chimeric antigen)",
 "CAR-T, autoimmune": r"(car[- ]t|chimeric antigen).{0,200}(lupus|autoimmun|multiple sclerosis|myasthenia|systemic sclerosis)|(lupus|autoimmun).{0,200}(car[- ]t|chimeric antigen)",
 "Base editing": r"base edit", "Prime editing": r"prime edit",
 "Epigenetic editing": r"epigenom\w* edit|epigenetic edit|crispr(off|on)\b|crispr interference|crispra\b|crispri\b",
 "RNA editing": r"rna edit|\badar\b",
 "Large insertion": r"integrase|transposase|retrotranspos|gene writ|large (dna )?(insertion|cargo)",
 "Capsid engineering": r"capsid.{0,30}(engineer|evolution|librar|variant)|engineered capsid|novel capsid",
 "AAV, brain": r"(aav|adeno-associated).{0,200}(brain|\bcns\b|blood-brain|intrathecal|neurodegenerat)",
 "AAV, eye": r"(aav|adeno-associated|gene therapy).{0,200}(retina|subretinal|intravitreal|ocular)",
 "AAV, muscle": r"(aav|adeno-associated|gene therapy).{0,200}(duchenne|dystrophin|muscular dystrophy|skeletal muscle)",
 "LNP beyond liver": r"(lipid nanoparticle|\blnps?\b).{0,200}(extrahepatic|lung|spleen|t cells|bone marrow|brain|non-liver|hematopoietic)",
 "mRNA therapeutics": r"mrna.{0,40}(therap|deliver|vaccin|lipid)",
 "Virus-like particles": r"virus-like particle|\bvlps?\b|\bevlp",
 "iPSC-derived cells": r"\bipsc|induced pluripotent",
 "Blood stem cell gene therapy": r"hematopoietic stem.{0,120}(gene therap|lentivir|edit)|sickle cell|thalass",
 "Regulatory T cells": r"regulatory t cell|\btregs?\b",
 "Macrophage therapy": r"car[- ]m\b|car[- ]macrophage|engineered macrophage|macrophage.{0,30}cell therap",
 "Extracellular vesicles": r"extracellular vesicle|exosome",
 "Manufacturing": r"manufactur|bioprocess|\bgmp\b",
}
TOPICS = {k: re.compile(v) for k, v in TOPICS.items()}
tags = {pid: [k for k, r in TOPICS.items() if r.search(t)] for pid, t in text.items()}
print("tagged", sum(bool(v) for v in tags.values()), "of", len(tags), flush=True)

# who has a company record, and from when (every US/UK author, by OpenAlex id)
first_rec = {}
for p in papers:
    for a in p.get("authors") or []:
        aid = (a.get("oa") or {}).get("aid")
        key, addresses, american, in_uk, _c = B._author(a)
        if not aid or not key or not (american or in_uk): continue
        for kind, when, detail, label in L._labelled(a, addresses, american, in_uk, data):
            if kind == "award" or kind == "formd" or kind == "uk":
                if aid not in first_rec or when < first_rec[aid]: first_rec[aid] = when
print("authors with a record", len(first_rec), flush=True)

people = L.seniors(data)
def window(d0, d1): return [p for p in papers if d0 < p["date"] <= d1]
recent2 = TODAY.replace(year=TODAY.year - 2); prior2 = TODAY.replace(year=TODAY.year - 4)
# ---- A. topics: growth against how commercial the labs are
A = []
for k in TOPICS:
    now = [p for p in papers if recent2 < p["date"] <= TODAY and k in tags[p["id"]]]
    then = [p for p in papers if prior2 < p["date"] <= recent2 and k in tags[p["id"]]]
    heads = {aid for aid, theirs in people.items() if any(recent2 < t[0]["date"] <= TODAY and k in tags[t[0]["id"]] for t in theirs)}
    withrec = {a for a in heads if a in first_rec and first_rec[a] <= TODAY}
    by_year = collections.Counter(p["date"].year for p in papers if k in tags[p["id"]])
    late = [p for p in now if set(B.describe(p, data)["flags"]) and any(B.describe(p, data)["flags"][s] for s in ("patients", "primate", "large_animal"))] if False else []
    A.append({"topic": k, "now": len(now), "then": len(then), "growth": len(now) / max(1, len(then)), "heads": len(heads), "withrec": len(withrec),
              "share": len(withrec) / max(1, len(heads)), "by_year": [by_year.get(y, 0) for y in range(2017, 2027)]})
A.sort(key=lambda r: -r["growth"])
for r in A: print(f"{r['topic']:30} now {r['now']:5} then {r['then']:5} x{r['growth']:.2f} heads {r['heads']:4} with record {r['share']:.0%}")

# ---- B. phrases rising in titles
STOP = set("a an and the of in for to with by on from as at is are via using based its their into against after during between through new novel study analysis role effect effects efficacy safety patients patient human mouse mice model models cell cells gene therapy therapies treatment clinical trial phase results".split())
def grams(title):
    w = re.findall(r"[a-z][a-z0-9\-]+", re.sub(r"<[^>]+>", " ", title.lower()))
    out = set()
    for n in (2, 3):
        for i in range(len(w) - n + 1):
            g = w[i:i + n]
            if g[0] in STOP or g[-1] in STOP: continue
            out.add(" ".join(g))
    return out
y1 = TODAY - dt.timedelta(days=365); y4 = TODAY - dt.timedelta(days=4 * 365)
new = collections.Counter(); old = collections.Counter(); nn = on = 0
for p in papers:
    g = grams(p.get("title") or "")
    if y1 < p["date"] <= TODAY: new.update(g); nn += 1
    elif y4 < p["date"] <= y1: old.update(g); on += 1
rows = [(g, c, old[g], (c / nn) / ((old[g] + 3) / on)) for g, c in new.items() if c >= 25]
rows.sort(key=lambda r: -r[3])
keep = []
for g, c, o, ratio in rows:
    if any(g in k[0] or k[0] in g for k in keep): continue
    keep.append((g, c, o, ratio))
    if len(keep) == 24: break
print("\nrising phrases (last 12 months n=%d vs 3 years before n=%d)" % (nn, on))
for g, c, o, ratio in keep: print(f"  {g:38} {c:4} now, {o:4} before, x{ratio:.1f}")
Bout = [{"phrase": g, "now": c, "before": o, "ratio": ratio, "rate_now": c / nn, "rate_before": o / on} for g, c, o, ratio in keep]

# ---- C. does publishing with a founder predict a first company record?
described = {p["id"]: None for p in papers}
Cout = []
for year in (2020, 2022):
    cutoff = dt.date(year, 12, 31); since = cutoff.replace(year=year - 4); until = cutoff + dt.timedelta(days=B.HORIZON_DAYS)
    groups = collections.defaultdict(lambda: [0, 0])
    for aid, theirs in people.items():
        known = [t for t in theirs if since < t[0]["date"] <= cutoff]
        if not known or max(t[0]["date"] for t in known) <= cutoff.replace(year=year - 2): continue
        if aid in first_rec and first_rec[aid] <= cutoff: continue          # only labs with no record yet
        co = set()
        for t in known:
            for a in t[0].get("authors") or []:
                other = (a.get("oa") or {}).get("aid")
                if other and other != aid and other in first_rec and first_rec[other] <= cutoff: co.add(other)
        event = aid in first_rec and cutoff < first_rec[aid] <= until
        g = "0" if not co else "1" if len(co) == 1 else "2+"
        groups[g][0] += 1; groups[g][1] += event
    for g in ("0", "1", "2+"):
        n, e = groups[g]; print(f"cohort {year}: co-authors with a company record {g:2}: {n:5} labs, {e:3} first records, {e / max(1, n):.1%}")
        Cout.append({"cohort": year, "group": g, "n": n, "events": e, "rate": e / max(1, n)})

# ---- D. institutions
inst = collections.defaultdict(lambda: {"heads": set(), "rec": set(), "new": set()})
for aid, theirs in people.items():
    known = [t for t in theirs if prior2 < t[0]["date"] <= TODAY]
    if not known or max(t[0]["date"] for t in known) <= recent2: continue
    name, country = L._institution(*(t[1] for t in reversed(known)))
    if not name: continue
    inst[(name, country)]["heads"].add(aid)
    if aid in first_rec and first_rec[aid] <= TODAY: inst[(name, country)]["rec"].add(aid)
    if aid in first_rec and first_rec[aid] > TODAY - dt.timedelta(days=3 * 365): inst[(name, country)]["new"].add(aid)
Dout = sorted(({"inst": k[0], "country": k[1], "heads": len(v["heads"]), "rec": len(v["rec"]), "share": len(v["rec"]) / len(v["heads"])} for k, v in inst.items() if len(v["heads"]) >= 15), key=lambda r: -r["heads"])
print("\ninstitutions with 15+ lab heads:", len(Dout))
for r in Dout[:40]: print(f"  {r['inst'][:44]:44} {r['country']} heads {r['heads']:3} with record {r['share']:.0%}")

# ---- E. maturity: share of papers with large-animal, primate or patient data, by modality and year
E = {}
for m, rule in L.MODALITIES.items():
    rx = re.compile(rule, re.I); series = []
    for y in range(2017, 2027):
        ps = [p for p in papers if p["date"].year == y and rx.search(text[p["id"]])]
        adv = sum(bool(re.search(B.RULES["patients"] + "|" + B.RULES["primate"] + "|" + B.RULES["large_animal"], text[p["id"]], re.I)) for p in ps)
        pat = sum(bool(re.search(B.RULES["patients"], text[p["id"]], re.I)) for p in ps)
        series.append({"year": y, "n": len(ps), "adv": adv, "patients": pat})
    E[m] = series
    print(m, [f"{s['n']}:{s['patients'] / max(1, s['n']):.0%}" for s in series])
json.dump({"A": A, "B": Bout, "C": Cout, "D": Dout, "E": E, "asOf": TODAY.isoformat(), "papers": len(papers)}, open(sys.argv[2], "w"))
