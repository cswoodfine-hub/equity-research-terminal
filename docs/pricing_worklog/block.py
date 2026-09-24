"""Draft a company cost block from the filed lines in the book. Usage: block.py TICKER [FY]
Prints the rows; nothing is written. The charge (other_costs_pct) is rebuilt separately,
once these rows are loaded, with charge_floor.measure."""
import sys, csv
sys.path.insert(0, "/home/user/equity-research-terminal/backend")
import db, beta
t = sys.argv[1].upper(); fy = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
c = db.get_connection()
cid = c.execute("SELECT id FROM companies WHERE ticker=?", (t,)).fetchone()[0]
def fyv(metric, year):
    r = c.execute("SELECT value, unit FROM financials WHERE company_id=? AND metric=? AND fiscal_year=? AND period_type='FY' ORDER BY rowid DESC LIMIT 1", (cid, metric, year)).fetchone()
    return (r["value"], r["unit"]) if r else (None, None)
rev, unit = fyv("Revenues", fy)
out = {"revenue": (rev, unit)}
for key, metric in (("cogs_pct", "CostOfRevenue"), ("sga_pct", "SellingGeneralAndAdministrative"), ("rd_pct", "ResearchAndDevelopmentExpense")):
    v, _ = fyv(metric, fy); out[key] = round(v / rev, 4) if (v is not None and rev) else None
tax = pre = 0.0; yrs = []
for y in range(fy - 5, fy + 1):
    ni, _ = fyv("NetIncomeLoss", y); tx, _ = fyv("IncomeTaxExpense", y)
    if ni is None or tx is None: continue
    p = ni + tx
    if p > 0: tax += tx; pre += p; yrs.append(y)
out["tax_rate"] = (round(tax / pre, 4) if pre else None, f"aggregate effective rate over the {len(yrs)} years to {fy} with positive pre-tax income, taken as net income plus the tax charge" if yrs else "")
out["beta"] = beta.compute(c, t)
d = c.execute("SELECT fiscal_year, value, unit FROM financials WHERE company_id=? AND metric='TotalDebt' ORDER BY fiscal_year DESC, rowid DESC LIMIT 1", (cid,)).fetchone()
sh = c.execute("SELECT fiscal_year, value FROM financials WHERE company_id=? AND metric='SharesOutstanding' ORDER BY fiscal_year DESC, rowid DESC LIMIT 1", (cid,)).fetchone()
px = c.execute("SELECT as_of, close FROM prices WHERE company_id=? AND interval='1d' ORDER BY as_of DESC LIMIT 1", (cid,)).fetchone()
out["debt"] = tuple(d) if d else None; out["shares"] = tuple(sh) if sh else None; out["price"] = tuple(px) if px else None
if d and sh and px and d["fiscal_year"] >= fy:
    mcap = sh["value"] * px["close"]; out["debt_weight"] = round(d["value"] / (d["value"] + mcap), 6)
for k, v in out.items(): print(f"{k:12} {v}")
