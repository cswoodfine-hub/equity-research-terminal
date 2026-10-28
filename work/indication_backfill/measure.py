import sys, json, collections
sys.path.insert(0, "backend")
import db, approved_indications

conn = db.get_connection()
conn.row_factory = __import__("sqlite3").Row

# marketed, forecastable: an asset whose assumptions say therapy_mode = marketed
marketed = {r["asset_id"] for r in conn.execute(
    "SELECT DISTINCT asset_id FROM assumptions "
    " WHERE key='therapy_mode' AND text_value='marketed'")}
has_rev = {r["asset_id"] for r in conn.execute(
    "SELECT DISTINCT asset_id FROM assumptions WHERE key='base_revenue' AND value IS NOT NULL")}
pool = sorted(marketed & has_rev)
print("marketed with a revenue anchor:", len(pool))

LAYER_KEYS = ("base_pool_overlap_pct", "pos", "penetration_peak_pct",
              "prevalence", "incidence", "eligible_pct")
# indication-level rows that exist anywhere, keyed (asset_id, indication_id)
seeded = collections.defaultdict(set)
for r in conn.execute(
        "SELECT asset_id, indication_id, key FROM assumptions "
        " WHERE indication_id IS NOT NULL"):
    seeded[(r["asset_id"], r["indication_id"])].add(r["key"])

# a disease whose pool is already sourced somewhere in the book
pool_known = {r["indication_id"] for r in conn.execute(
    "SELECT DISTINCT indication_id FROM assumptions "
    " WHERE indication_id IS NOT NULL AND key IN ('prevalence','incidence') "
    "   AND value IS NOT NULL")}

rows = []
for aid in pool:
    approved = approved_indications.for_asset(conn, aid)
    for r in conn.execute(
            "SELECT ai.id pair_id, ai.indication_id, ai.phase, ai.development_status,"
            "       i.name iname, i.therapeutic_area ta,"
            "       a.brand_name, a.generic_name, a.internal_code, c.ticker"
            "  FROM asset_indications ai"
            "  JOIN indications i ON i.id = ai.indication_id"
            "  JOIN assets a ON a.id = ai.asset_id"
            "  JOIN companies c ON c.id = a.owner_company_id"
            " WHERE ai.asset_id = ?", (aid,)):
        if r["pair_id"] in approved:
            continue
        if (r["phase"] or "") in ("Approved", "Phase 4"):
            continue
        keys = seeded.get((aid, r["indication_id"]), set())
        rows.append(dict(
            asset_id=aid, pair_id=r["pair_id"], indication_id=r["indication_id"],
            ticker=r["ticker"], brand=r["brand_name"] or r["generic_name"] or r["internal_code"],
            indication=r["iname"], area=r["ta"], phase=r["phase"],
            status=r["development_status"],
            seeded=bool(keys & set(LAYER_KEYS)), keys=sorted(keys),
            pool_known=r["indication_id"] in pool_known))

print("unapproved indications on those assets:", len(rows))
s = [r for r in rows if r["seeded"]]
u = [r for r in rows if not r["seeded"]]
print("  already carrying layer seeds:", len(s))
print("  genuinely untouched         :", len(u))
print("     of those, pool in book   :", sum(1 for r in u if r["pool_known"]))
print()
print("untouched by phase:", dict(collections.Counter(r["phase"] for r in u).most_common()))
print()
print("untouched by ticker:", dict(collections.Counter(r["ticker"] for r in u).most_common()))
print()
print("untouched by status:", dict(collections.Counter(r["status"] for r in u).most_common()))
json.dump(rows, open(sys.argv[1], "w"), indent=1)
