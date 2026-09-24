"""Convert a seed's USD prices into the company's reporting currency. Usage: fx_seed.py <seed csv> [...]"""
import csv, io, sqlite3, sys, pathlib
REPO = pathlib.Path("/home/user/equity-research-terminal")
CUR = {r["ticker"].strip().upper(): r["reporting_currency"].strip().upper()
       for r in csv.DictReader(open(REPO / "data/companies_seed.csv", encoding="utf-8")) if r.get("ticker")}
db = sqlite3.connect(str(REPO / "backend/er_tool.db"))
MONEY = ("list_price_per_patient", "net_price_per_patient")
for path in sys.argv[1:]:
    p = pathlib.Path(path)
    text = p.read_text(encoding="utf-8").splitlines(keepends=True)
    head = [l for l in text if l.startswith("#")]
    body = [l for l in text if not l.startswith("#")]
    rows = list(csv.DictReader(body)); fields = list(csv.DictReader(body).fieldnames)
    changed = 0
    for r in rows:
        if r["key"] not in MONEY or "mm USD" not in (r["unit"] or ""): continue
        cur = CUR.get(r["ticker"].strip().upper(), "USD")
        if cur == "USD": continue
        rate, asof = db.execute("SELECT rate, as_of FROM fx_rates WHERE base=? AND quote='USD' ORDER BY as_of DESC LIMIT 1", (cur,)).fetchone()
        usd = float(r["value"]); local = usd / rate
        r["value"] = f"{local:.11g}"; r["unit"] = r["unit"].replace("mm USD", f"mm {cur}")
        note = (r["note"] or "").rstrip()
        sep = "" if not note else (" " if note.endswith(".") else ". ")
        r["note"] = (note + sep + f"In {cur} because the engine models a company in its reporting currency and converts to dollars only at the end: "
                     f"${usd*1e6:,.2f} at {cur}/USD {rate:.6f} (ECB via fetchers/fx_ecb.py, {asof}) is {cur} {local*1e6:,.2f}")
        changed += 1
    buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n"); w.writeheader(); w.writerows(rows)
    p.write_text("".join(head) + buf.getvalue(), encoding="utf-8")
    print(p.name, "converted", changed)
