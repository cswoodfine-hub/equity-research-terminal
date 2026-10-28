"""Layers indication_layer prices, counted over worklist.json units matched by name.

worklist.json carries asset and indication ids from the owner's book, which differ from
this copy's, so each unit is matched on (ticker, brand, indication name) instead.
"""
import json, sys
sys.path.insert(0, "backend")
import db, indication_layer

conn = db.get_connection()
units = json.load(open("work/indication_backfill/worklist.json"))["units"]
built = unmatched = 0
for u in units:
    a = conn.execute("SELECT a.id FROM assets a JOIN companies c ON c.id = a.owner_company_id"
                     " WHERE c.ticker = ? AND a.brand_name = ?", (u["ticker"], u["brand"])).fetchall()
    i = conn.execute("SELECT id FROM indications WHERE name = ?", (u["indication"],)).fetchall()
    if len(a) != 1 or len(i) != 1:
        unmatched += 1
        continue
    b = indication_layer.build(conn, a[0][0], i[0][0])
    if b and b.get("ok"):
        built += 1
print(f"layers priced: {built} of {len(units)} units ({unmatched} not matched by name)")
