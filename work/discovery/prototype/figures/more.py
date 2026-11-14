"""Figure data, part 2: the read-depth curve (2020 model on the 2022 cohort) and the
co-authorship links among the top 300 lab heads of a live file.

    python3 work/discovery/prototype/figures/more.py <data folder> <more.json>

Reads ``live.json`` beside the data folder.
"""
import sys, json, collections, datetime as dt
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tools"))
import numpy as np
import backtest as B, live as L
S = sys.argv[1]; TODAY = dt.date(2026, 11, 14)
data = B.load(S)
described = {p["id"]: B.describe(p, data) for p in data["papers"]}
people = L.seniors(data)
a20 = L.cohort(data, described, people, dt.date(2020, 12, 31)); a22 = L.cohort(data, described, people, dt.date(2022, 12, 31))
s = L.Ranker(a20, "lab").score(a22); y = np.array([int(r["lab"]) for r in a22])
order = np.argsort(-s, kind="stable"); cum = np.cumsum(y[order]) / y.sum()
floor = np.array([r["flags"]["papers_log"] for r in a22]); cumf = np.cumsum(y[np.argsort(-floor, kind="stable")]) / y.sum()
pts = [1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100]
gains = [{"read": p, "found": float(cum[max(0, round(len(y) * p / 100) - 1)]), "floor": float(cumf[max(0, round(len(y) * p / 100) - 1)])} for p in pts]
print([(g["read"], round(g["found"], 2), round(g["floor"], 2)) for g in gains], len(y), int(y.sum()))
# network among today's top-ranked lab heads
live = json.load(open(S + "/../live.json")); top = {l["id"]: l for l in live["labs"] if l["rank"] <= 300}
since = TODAY.replace(year=TODAY.year - 4)
edges = collections.Counter()
for p in data["papers"]:
    if not (since < p["date"] <= TODAY): continue
    ids = sorted({(a.get("oa") or {}).get("aid") for a in p.get("authors") or []} & set(top))
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)): edges[(ids[i], ids[j])] += 1
deg = collections.Counter(x for e in edges for x in e)
print("edges", len(edges), "labs with a link", len(deg), "of", len(top))
# components
adj = collections.defaultdict(set)
for a, b in edges: adj[a].add(b); adj[b].add(a)
seen = set(); comps = []
for n in adj:
    if n in seen: continue
    st = [n]; c = []
    while st:
        x = st.pop()
        if x in seen: continue
        seen.add(x); c.append(x); st += adj[x] - seen
    comps.append(c)
comps.sort(key=len, reverse=True); print("component sizes", [len(c) for c in comps[:12]])
for c in comps[:4]: print("  ", [top[x]["name"] for x in c[:10]], collections.Counter(top[x]["inst"] for x in c).most_common(2))
nodes = [{"id": i, "name": l["name"], "inst": l["inst"], "rank": l["rank"], "rec": len(l["before"]) + len(l["after"]), "new": len(l["after"]), "mod": (l["mods"] or ["Other"])[0]} for i, l in top.items() if i in deg]
json.dump({"gains": gains, "gainsN": len(y), "gainsE": int(y.sum()), "nodes": nodes, "edges": [{"s": a, "t": b, "w": w} for (a, b), w in edges.items()]}, open(sys.argv[2], "w"))
