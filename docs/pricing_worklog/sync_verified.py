"""Copy a seed row's value, source and note into its verified record, with a verdict saying why.
  sync_verified.py VERIFIED_JSON SEED_CSV KEY INDICATION_OR_- VERDICT "CHECK" """
import csv, json, sys
vf, seed, key, ind, verdict, check = sys.argv[1:7]
ind = "" if ind == "-" else ind
row = next(r for r in csv.DictReader(l for l in open(seed, encoding="utf-8") if not l.startswith("#"))
           if r["key"] == key and r["indication"] == ind)
v = json.load(open(vf))
val = row["text_value"] if key == "therapy_mode" else (float(row["value"]) if row["value"] not in ("", None) else None)
field = {"value": val, "unit": row["unit"], "source": row["source"], "note": row["note"], "verdict": verdict, "check": check}
if ind:
    block = next(b for b in v["indications"] if b["indication"] == ind)
    old = block["fields"].get(key); block["fields"][key] = field
else:
    old = v["asset"].get(key); v["asset"][key] = field
if old: field["check"] += f"; was {old.get('value')} ({old.get('verdict')})"
open(vf, "w").write(json.dumps(v, indent=1, ensure_ascii=False))
print(vf, key, ind or "(asset)", val)
