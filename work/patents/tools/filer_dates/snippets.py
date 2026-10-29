"""For each product without a filer row, the annual report passages that tie its name to
a year: patent-table rows first, then sentences on exclusivity, patents or competition."""
import json, re, sys, pathlib
filings = pathlib.Path(sys.argv[1]); products = json.load(open(sys.argv[2]))
KEY = re.compile(r"patent|exclusiv|expir|biosimilar|generic|loss of|LOE|competition", re.I)
YEAR = re.compile(r"\b20[2-5]\d\b")
def names(brand):
    base = re.split(r"\s*\(|/| And ", brand)[0].strip()
    out = {base}
    first = base.split()[0]
    if len(first) >= 5:
        out.add(first)
    return sorted(out, key=len, reverse=True)
report = []
for p in products:
    if p["disclosed"]:
        continue
    path = filings / f"{p['ticker']}.txt"
    if not path.exists():
        continue
    text = path.read_text()
    hits = []
    for name in names(p["brand"]):
        for m in re.finditer(r"\b" + re.escape(name) + r"\b", text, re.I):
            after = text[m.end(): m.end() + 70]
            window = text[max(0, m.start() - 260): m.end() + 260]
            table = bool(re.match(r"\s*(\(\d+\)\s*)*(20[2-5]\d|Expired|N/A)", after))
            if table or (YEAR.search(window) and KEY.search(window)):
                score = 2 if table else 1
                hits.append((score, m.start(), window))
        if hits:
            break
    hits.sort(key=lambda h: (-h[0], h[1]))
    seen, keep = [], []
    for score, pos, w in hits:
        if any(abs(pos - s) < 300 for s in seen):
            continue
        seen.append(pos); keep.append({"table": score == 2, "text": w})
        if len(keep) >= 4:
            break
    report.append({**{k: p[k] for k in ("ticker", "brand", "modality", "date", "basis", "npv")},
                   "hits": keep})
json.dump(report, open(sys.argv[3], "w"), indent=1)
print(len(report), "products;", sum(1 for r in report if r["hits"]), "with passages;",
      sum(1 for r in report if any(h["table"] for h in r["hits"])), "with a table row")
