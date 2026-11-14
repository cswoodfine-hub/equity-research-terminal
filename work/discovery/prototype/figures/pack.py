"""Figure data, part 3: lay the network out and add ``figs`` to the live file the
prototype reads. Run from the folder holding ``figs.json`` and ``more.json``.

    python3 work/discovery/prototype/figures/pack.py <folder holding live.json>
"""
import json, sys, collections
import numpy as np
S = sys.argv[1]
f = json.load(open("figs.json")); m = json.load(open("more.json")); live = json.load(open(S + "/live.json"))
nodes = {n["id"]: n for n in m["nodes"]}; edges = m["edges"]
adj = collections.defaultdict(set)
for e in edges: adj[e["s"]].add(e["t"]); adj[e["t"]].add(e["s"])
seen, comps = set(), []
for n in sorted(adj, key=lambda x: nodes[x]["rank"]):
    if n in seen: continue
    st, c = [n], []
    while st:
        x = st.pop()
        if x in seen: continue
        seen.add(x); c.append(x); st += sorted(adj[x] - seen)
    comps.append(c)
comps.sort(key=lambda c: (-len(c), min(nodes[x]["rank"] for x in c)))
def layout(ids, seed=7, iters=600):
    n = len(ids); idx = {x: i for i, x in enumerate(ids)}
    if n == 1: return np.array([[.5, .5]])
    if n == 2: return np.array([[.25, .5], [.75, .5]])
    rng = np.random.default_rng(seed); pos = rng.random((n, 2)); k = 0.9 / np.sqrt(n)
    es = [(idx[e["s"]], idx[e["t"]]) for e in edges if e["s"] in idx and e["t"] in idx]
    t = 0.12
    for _ in range(iters):
        d = pos[:, None, :] - pos[None, :, :]; dist = np.maximum(np.linalg.norm(d, axis=2), 1e-3)
        disp = (d / dist[..., None] * (k * k / dist)[..., None]).sum(axis=1)
        for a, b in es:
            v = pos[a] - pos[b]; l = max(np.linalg.norm(v), 1e-3); fa = v / l * (l * l / k)
            disp[a] -= fa; disp[b] += fa
        disp -= pos - 0.5                                   # a weak pull to the middle
        l = np.maximum(np.linalg.norm(disp, axis=1), 1e-3)
        pos += disp / l[:, None] * np.minimum(l, t)[:, None]; t *= 0.994
    pos -= pos.min(axis=0); pos /= np.maximum(pos.max(axis=0), 1e-6)
    return pos
W, H = 960, 580
boxes = [(24, 36, 600, 520)]
cols, tw, th = 3, 104, 86
for i in range(len(comps) - 1):
    boxes.append((640 + (i % cols) * tw, 30 + (i // cols) * th, tw - 26, th - 34))
for c, (x0, y0, w, h) in zip(comps, boxes):
    pos = layout(c)
    for x, p in zip(c, pos):
        nodes[x]["x"] = round(float(x0 + p[0] * w), 1); nodes[x]["y"] = round(float(y0 + p[1] * h), 1); nodes[x]["deg"] = len(adj[x])
big = comps[0]
lab = set(sorted(big, key=lambda x: (-len(adj[x]), nodes[x]["rank"]))[:13]) | {min(c, key=lambda x: nodes[x]["rank"]) for c in comps[1:9]}
for x in nodes: nodes[x]["label"] = x in lab
print(len(comps), "components;", "rows of tiles", (len(comps) - 1 + cols - 1) // cols, "; labelled", len(lab))
inst = sorted([r for r in f["D"] if r["heads"] >= 40], key=lambda r: -r["share"])
any_ = []
for year in (2020, 2022):
    g = {r["group"]: r for r in f["C"] if r["cohort"] == year}
    n1 = g["1"]["n"] + g["2+"]["n"]; e1 = g["1"]["events"] + g["2+"]["events"]
    any_.append({"cohort": year, "none": {"n": g["0"]["n"], "events": g["0"]["events"], "rate": g["0"]["rate"]}, "some": {"n": n1, "events": e1, "rate": e1 / n1},
                 "one": g["1"], "more": g["2+"]})
    print(year, round(g["0"]["rate"], 4), round(e1 / n1, 4), round(e1 / n1 / g["0"]["rate"], 2))
live["figs"] = {"topics": f["A"], "gains": m["gains"], "gainsN": m["gainsN"], "gainsE": m["gainsE"], "net": {"w": W, "h": H, "nodes": list(nodes.values()), "edges": edges, "of": 300},
                "inst": inst, "founder": any_, "modal": f["E"], "papers": f["papers"]}
json.dump(live, open(S + "/live.json", "w"), separators=(",", ":"))
print(len(inst), "institutions")
