import sys, json, collections, sqlite3
sys.path.insert(0,"backend"); import db
conn=db.get_connection(); conn.row_factory=sqlite3.Row
rows=json.load(open(sys.argv[1]))
LAYER_PH={"Phase 3","Phase 2/3","Phase 2"}
buckets=collections.Counter(); seedable=[]
for r in rows:
    pid=r.get("asset_indication_id")
    if not pid: buckets["no asset_indication link"]+=1; continue
    p=conn.execute("SELECT ai.asset_id, ai.indication_id, ai.phase, i.name iname,"
                   " i.therapeutic_area ta, a.brand_name, a.generic_name, a.internal_code,"
                   " c.ticker FROM asset_indications ai"
                   " JOIN indications i ON i.id=ai.indication_id"
                   " JOIN assets a ON a.id=ai.asset_id"
                   " JOIN companies c ON c.id=a.owner_company_id WHERE ai.id=?",(pid,)).fetchone()
    if p is None: buckets["dangling pair"]+=1; continue
    mode=conn.execute("SELECT text_value FROM assumptions WHERE asset_id=? AND key='therapy_mode'",(p["asset_id"],)).fetchone()
    mode=mode["text_value"] if mode else None
    if mode not in ("marketed","franchise","launch"):
        buckets[f"not a selling product (mode={mode})"]+=1; continue
    if (p["phase"] or "") not in LAYER_PH:
        buckets[f"phase not layer-eligible ({p['phase']})"]+=1; continue
    seedable.append({**r, "asset_id":p["asset_id"], "indication_id":p["indication_id"],
        "phase":p["phase"], "indication":p["iname"], "area":p["ta"], "mode":mode,
        "brand":p["brand_name"] or p["generic_name"] or p["internal_code"]})
print("no_gate catalysts:",len(rows))
for k,v in buckets.most_common(): print(f"  {v:4d}  {k}")
print("  ---- seedable (selling product, layer phase, unapproved):",len(seedable))
# dedupe to the unit of work: one (asset, indication)
units={}
for s in seedable: units.setdefault((s["asset_id"],s["indication_id"]),[]).append(s)
print("  distinct (asset, indication) units:",len(units))
print()
print("units by ticker:",dict(collections.Counter(v[0]["ticker"] for v in units.values()).most_common()))
print()
print("units by phase:",dict(collections.Counter(v[0]["phase"] for v in units.values()).most_common()))
json.dump([{"key":f"{k[0]}:{k[1]}", **v[0], "catalyst_ids":[x["id"] for x in v]}
           for k,v in units.items()], open(sys.argv[2],"w"), indent=1)
