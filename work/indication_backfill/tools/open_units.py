import json, sys, sqlite3, collections
sys.path.insert(0, "work/indication_backfill"); sys.path.insert(0, "backend")
import db, steps_to_priced as S, assumptions as A
conn = db.get_connection(); conn.row_factory = sqlite3.Row
rows = S.classify(conn, json.load(open(sys.argv[1])))
pick = [r for r in rows if r["steps"] == ["layer seeds"]]
units = collections.OrderedDict()
for r in sorted(pick, key=lambda x: (x["ticker"], x["brand"], str(x["indication"]))):
    units.setdefault((r["asset_id"], r["ticker"], r["brand"], r["indication"]), []).append(r)
open_, done = [], []
for (aid, t, b, ind), rs in units.items():
    loaded = A.load(conn, aid, "base") or {}
    e = next((x for x in loaded.get("indications") or [] if x.get("name") == ind), None)
    sc = (e or {}).get("scalars") or {}
    ov, pos = sc.get("base_pool_overlap_pct"), sc.get("pos")
    have = sorted(k for k, v in sc.items() if v is not None)
    tag = "answered: overlap 1" if ov is not None and ov >= 1 else ("answered: pos 0" if pos == 0 else None)
    cats = []
    for r in rs:
        c = conn.execute("SELECT source_url, expected_date FROM catalysts WHERE id=?", (r["catalyst"],)).fetchone()
        cats.append(f'{c["expected_date"]} {c["source_url"].rsplit("/",1)[-1]}')
    line = f"{t}|{b}|{ind}|{'; '.join(cats)}|has: {','.join(have) or '-'}"
    (done if tag else open_).append((tag, line))
print(len(open_), "open units;", len(done), "already answered")
for _, l in open_: print("OPEN ", l)
for t, l in done: print("DONE ", t, "|", l)
