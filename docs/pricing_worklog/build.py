"""Load the seeds into backend/er_tool.db and build named assets. Usage: build.py TICKER:Name [...]"""
import sys
sys.path.insert(0, "/home/user/equity-research-terminal/backend")
import db, assumptions, forecast_view
conn = db.get_connection()
print("seeds:", assumptions.load_seeds(conn)); conn.commit()
for arg in sys.argv[1:]:
    t, name = arg.split(":", 1)
    a = conn.execute("""SELECT a.id FROM assets a JOIN companies c ON c.id=a.owner_company_id WHERE c.ticker=?
        AND (LOWER(TRIM(a.brand_name))=LOWER(?) OR LOWER(TRIM(a.generic_name))=LOWER(?))
        ORDER BY a.is_marketed DESC, a.id LIMIT 1""", (t, name, name)).fetchone()
    if not a:
        print(arg, "NO ASSET"); continue
    r = forecast_view.asset_forecast(str(db.DB_PATH), t, a["id"])
    if not r.get("ok"):
        print(arg, "NOT BUILT, missing:", r.get("missing")); continue
    res = r.get("result") or r
    rev = res.get("revenue") or []
    yrs = res.get("years") or []
    peak = max(rev) if rev else None
    py = yrs[rev.index(peak)] if rev else None
    print(f"{arg}: asset {a['id']} peak {peak:,.0f}mm in {py}, rNPV {res.get('rnpv')}, pos {res.get('pos')}, currency {res.get('currency')}")
