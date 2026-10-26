import sys, json, collections, sqlite3
sys.path.insert(0, "backend")
import db, forecast_view
conn = db.get_connection(); conn.row_factory = sqlite3.Row
tickers = [r[0] for r in conn.execute("SELECT ticker FROM companies ORDER BY ticker")]
out, counts = [], collections.Counter()
npriced = 0
for t in tickers:
    try:
        res = forecast_view.catalyst_stakes(str(db.DB_PATH), t)
    except Exception as e:
        print("ERR", t, type(e).__name__, e); continue
    if not res: continue
    npriced += len(res["priced"])
    for r in res["unpriced"]:
        reason = r.get("reason") or r.get("stake_reason") or "?"
        counts[reason] += 1
        if reason == "no_gate":
            out.append({"ticker": t, **{k: r.get(k) for k in
                        ("id","asset_id","asset_indication_id","catalyst_type",
                         "expected_date","title","why")}})
print("priced:", npriced)
print(dict(counts.most_common()))
print("no_gate rows:", len(out))
json.dump(out, open(sys.argv[1],"w"), indent=1)
