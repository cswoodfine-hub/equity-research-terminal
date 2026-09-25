"""Write a comparator cost block into an assembled seed. Usage:
  comparator_block.py SEED_CSV TICKER COMPARATOR_TICKER DEBT_WEIGHT "DEBT_SOURCE" "WHY_THIS_COMPARATOR"
Borrows the comparator's cogs, SG&A, R&D, other costs and tax rows (its modal values across its
seeds), computes the company's own beta from stored prices, copies the dated risk-free, ERP and
cost-of-debt rows, and states the debt weight given. Register the pair in
interest_addback.COMPARATORS as well, so a charge restatement follows the comparator's."""
import csv, glob, io, pathlib, sys, collections
sys.path.insert(0, "/home/user/equity-research-terminal/backend")
import db, beta
seed, t, comp, dw, dsrc, why = sys.argv[1:7]
REPO = pathlib.Path("/home/user/equity-research-terminal")
BORROW = ("cogs_pct", "sga_pct", "rd_pct", "other_costs_pct", "tax_rate")
COMMON = ("risk_free", "erp", "cost_of_debt")
votes = collections.defaultdict(collections.Counter); rows_by = {}
for p in sorted(glob.glob(str(REPO / "data/assumptions/*.csv"))):
    for r in csv.DictReader(l for l in open(p, newline="", encoding="utf-8") if not l.startswith("#")):
        if r["ticker"] == comp and not r["indication"] and r["scenario"] == "base" and r["key"] in BORROW:
            votes[r["key"]][r["value"]] += 1; rows_by[(r["key"], r["value"])] = r
common = {r["key"]: r for r in csv.DictReader(l for l in open(REPO / "data/assumptions/incy_jakafi.csv", newline="", encoding="utf-8") if not l.startswith("#")) if r["key"] in COMMON}
c = db.get_connection(); b, bsrc = beta.compute(c, t)
p = pathlib.Path(seed); lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
head = [l.replace("# No company-level rows on file for this company.", f"# Company-level rows: own beta and debt; cost lines borrowed from {comp}, the comparator, as Viking's are from Lilly's.") for l in lines if l.startswith("#")]
body = [l for l in lines if not l.startswith("#")]
rows = list(csv.DictReader(body)); fields = csv.DictReader(body).fieldnames; brand = rows[0]["brand"]
def mk(key, value, unit, source, note=""):
    return {"ticker": t, "brand": brand, "indication": "", "region": "US", "scenario": "base", "key": key, "year": "",
            "value": value, "text_value": "", "unit": unit, "source": source, "note": note}
block = [mk("beta", b, "", bsrc)]
for key in BORROW:
    val = votes[key].most_common(1)[0][0]; r = rows_by[(key, val)]
    block.append(mk(key, val, r["unit"], f"comparator estimate: {comp}'s row, {why}. {t} has no product revenue of its own to read a ratio from. {comp}'s source: {r['source']}",
                    f"a comparator, not a measurement; revisit when {t} files a cost of sales"))
block.append(mk("debt_weight", dw, "", dsrc, "a reading of the balance sheet"))
for key in COMMON: block.append({**common[key], "ticker": t, "brand": brand})
block.sort(key=lambda r: r["key"])
buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n", extrasaction="ignore"); w.writeheader(); w.writerows(block + rows)
p.write_text("".join(head) + buf.getvalue(), encoding="utf-8")
print("block written:", {r["key"]: r["value"] for r in block})
