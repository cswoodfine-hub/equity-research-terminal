"""Verified research JSON -> data/assumptions seed. Usage: assemble.py <verified json> [...]"""
import csv, datetime, glob, io, json, re, sys, pathlib
REPO = pathlib.Path("/home/user/equity-research-terminal")
COMPANY_KEYS = ("beta", "cogs_pct", "cost_of_debt", "debt_weight", "erp", "other_costs_pct",
                "rd_pct", "risk_free", "sga_pct", "tax_rate")
HEADER = ["ticker","brand","indication","region","scenario","key","year","value","text_value","unit","source","note"]

def company_rows(ticker):
    best = None
    for p in sorted(glob.glob(str(REPO / "data/assumptions" / "*.csv"))):
        rows = list(csv.DictReader(l for l in open(p, encoding="utf-8") if not l.startswith("#")))
        got = {r["key"]: r for r in rows if r["ticker"] == ticker and not r["indication"] and r["key"] in COMPANY_KEYS}
        if len(got) == len(COMPANY_KEYS):
            return got, pathlib.Path(p).name
        if got and (best is None or len(got) > len(best[0])): best = (got, pathlib.Path(p).name)
    return best if best else ({}, None)

import sqlite3
def in_epidemiology(indication, key):
    for row in csv.DictReader(l for l in open(REPO / "data/epidemiology.csv", encoding="utf-8") if not l.startswith("#")):
        if row["indication"] == indication and (row.get(key) or "").strip():
            return True
    return False

def carried_by_asset(indication, key):
    """The figure another asset already carries for this disease, copied so one disease keeps one number."""
    c = sqlite3.connect(str(REPO / "backend/er_tool.db")); c.row_factory = sqlite3.Row
    rows = c.execute("""SELECT DISTINCT s.value, s.unit, s.source, a.generic_name, a.brand_name FROM assumptions s
                        JOIN indications i ON i.id = s.indication_id JOIN assets a ON a.id = s.asset_id
                        WHERE i.name = ? AND s.key = ? AND s.scenario = 'base'""", (indication, key)).fetchall()
    vals = {r["value"] for r in rows}
    if len(vals) != 1:
        return None
    r = rows[0]; who = r["brand_name"] or r["generic_name"]
    return {"value": r["value"], "unit": r["unit"] or "",
            "source": f"the figure the {who} seed carries for {indication}, copied so one disease keeps one number: {r['source']}",
            "note": "carried by the book"}

def main(paths):
    for path in paths:
        v = json.load(open(path))
        t, name = v["ticker"], v["name"]
        if v.get("refuse"):
            print(f"REFUSED {t} {name}: {v['refuse']}"); continue
        comp, template = company_rows(t)
        missing = [k for k in COMPANY_KEYS if k not in comp]
        out = []
        for k in COMPANY_KEYS:
            if k in comp:
                r = dict(comp[k]); r["brand"] = name; out.append(r)
        def add(key, f, ind=""):
            if f is None or f.get("value") in (None, "") or f.get("verdict") == "withdrawn": return
            val = f["value"]; tv = ""
            if key == "therapy_mode": tv, val = val, ""
            out.append({"ticker": t, "brand": name, "indication": ind, "region": "US", "scenario": "base",
                        "key": key, "year": "", "value": val, "text_value": tv, "unit": f.get("unit") or "",
                        "source": f.get("source") or "", "note": f.get("note") or ""})
        PER_IND = ("prevalence", "eligible_pct", "incidence", "penetration_peak_pct", "ramp_midpoint_year",
                   "ramp_steepness", "untreated_carryover_pct", "exus_multiple",
                   "diagnosed_pct", "referred_pct", "payer_approved_pct", "accepts_pct")
        blocks = v.get("indications") or []
        for key, f in v["asset"].items():
            if key in PER_IND:
                for block in blocks:                     # the engine reads these per indication
                    block["fields"].setdefault(key, f)
            else:
                add(key, f)
        for block in blocks:
            for key in ("prevalence", "incidence"):
                f = block["fields"].get(key)
                if (f is None or f.get("value") in (None, "")) and not in_epidemiology(block["indication"], key):
                    carried = carried_by_asset(block["indication"], key)
                    if carried:
                        block["fields"][key] = carried
            for key, f in block["fields"].items(): add(key, f, block["indication"])
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
        dest = REPO / "data/assumptions" / f"{t.lower()}_{slug}.csv"
        summ = [("# " + line).rstrip() for line in (v.get("summary") or "").splitlines() if line.strip()]
        head = [f"# {name} ({t}).", *summ, "#",
                f"# Researched and then checked by a second reader who reopened every source, {datetime.datetime.fromtimestamp(pathlib.Path(sys.argv[1]).stat().st_mtime, datetime.timezone.utc):%Y-%m-%d}.",
                f"# Company-level rows copied from {template}." if template else "# No company-level rows on file for this company.",
                "#", "# Seeds are insert-only. Edit a number in the terminal, not here."]
        buf = io.StringIO(); w = csv.DictWriter(buf, fieldnames=HEADER, lineterminator="\n", extrasaction="ignore")
        w.writeheader(); w.writerows(out)
        dest.write_text("\n".join(head) + "\n" + buf.getvalue(), encoding="utf-8")
        print(f"wrote {dest.name}: {len(out)} rows" + (f"; company keys missing: {missing}" if missing else ""))

if __name__ == "__main__":
    main(sys.argv[1:])
