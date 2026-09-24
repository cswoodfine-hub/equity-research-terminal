"""Read-only lookups against a copy of the book. Usage:
  python lookup.py demand <brand substring>      CMS Part B/D spending, claims, beneficiaries by year
  python lookup.py pool <indication substring>   prevalence/incidence the book already carries
  python lookup.py seed <asset name substring>   every assumption row the book holds for an asset
"""
import sqlite3, sys, csv
c = sqlite3.connect("file:/tmp/claude-0/price/book.db?mode=ro", uri=True); c.row_factory = sqlite3.Row
cmd, arg = sys.argv[1], "%" + sys.argv[2] + "%"
if cmd == "demand":
    for r in c.execute("SELECT brand_name, part, year, total_spending, total_claims, total_beneficiaries, total_dosage_units FROM drug_demand WHERE brand_name LIKE ? ORDER BY brand_name, part, year", (arg,)):
        b = r["total_beneficiaries"] or 0
        print(dict(r), "| spend per beneficiary:", round(r["total_spending"] / b) if b else None)
elif cmd == "pool":
    for r in c.execute("""SELECT i.name, s.key, s.value, s.source, a.generic_name FROM assumptions s JOIN indications i ON i.id=s.indication_id
                          JOIN assets a ON a.id=s.asset_id WHERE i.name LIKE ? AND s.key IN ('prevalence','incidence','eligible_pct') AND s.scenario='base'""", (arg,)):
        print(dict(r))
    for row in csv.DictReader(l for l in open("/home/user/equity-research-terminal/data/epidemiology.csv") if not l.startswith("#")):
        if sys.argv[2].lower() in list(row.values())[0].lower(): print("epidemiology.csv:", row)
elif cmd == "seed":
    for r in c.execute("""SELECT a.generic_name, i.name ind, s.key, s.value, s.text_value, s.unit, s.source FROM assumptions s JOIN assets a ON a.id=s.asset_id
                          LEFT JOIN indications i ON i.id=s.indication_id WHERE a.generic_name LIKE ? OR a.brand_name LIKE ?""", (arg, arg)):
        print(dict(r))
