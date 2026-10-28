import json, sys, sqlite3, collections
sys.path.insert(0, "work/indication_backfill"); sys.path.insert(0, "backend")
import db, steps_to_priced as S
conn = db.get_connection(); conn.row_factory = sqlite3.Row
rows = S.classify(conn, json.load(open(sys.argv[1])))
want = sys.argv[2].split("+")
pick = [r for r in rows if r["steps"] == want]
units = collections.OrderedDict()
for r in sorted(pick, key=lambda x: (x["ticker"], x["brand"], str(x["indication"]))):
    units.setdefault((r["ticker"], r["brand"], r["indication"]), []).append((r["catalyst"], r["date"]))
print(len(pick), "catalysts", len(units), "units", len({(t,b) for t,b,_ in units}), "assets")
for (t,b,i), c in units.items():
    print(f"{t:5} {b[:28]:<30} {str(i)[:44]:<46} {len(c)} {c[0][1]}")
print()
for r in sorted(pick, key=lambda x: (x["ticker"], x["brand"])):
    c = conn.execute("SELECT title, source_url, expected_date FROM catalysts WHERE id=?", (r["catalyst"],)).fetchone()
    print(f'{r["ticker"]}|{r["brand"]}|{r["indication"]}|{c["expected_date"]}|{c["source_url"]}|{(c["title"] or "")[:100]}')
