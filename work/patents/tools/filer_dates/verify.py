"""Check each agent finding against its filing and against the model's date.

A quote is kept only if every ' ... '-joined part is a verbatim substring of the filing
text. A stated date is turned into the date the book would use (loe._period_end) and
compared with the model's date: a difference of more than 31 days is a candidate row."""
import calendar, datetime as dt, json, pathlib, sys
review = pathlib.Path(sys.argv[1]); filings = pathlib.Path(sys.argv[2])
texts = {}
def text(t):
    if t not in texts:
        texts[t] = (filings / f"{t}.txt").read_text()
    return texts[t]
def period_end(s):
    parts = s.strip().split("-")
    if len(parts) == 1:
        return f"{parts[0]}-12-31"
    if len(parts) == 2:
        y, m = int(parts[0]), int(parts[1])
        return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
    return s.strip()
model = {}
for f in review.glob("g*_in.json"):
    for p in json.load(open(f))["products"]:
        model[(p["ticker"], p["brand"])] = p
rows = []
for f in sorted(review.glob("g*_out.json")):
    for r in json.load(open(f)):
        key = (r["ticker"], r["brand"]); m = model.get(key, {})
        q = r.get("quote") or ""
        quote_ok = bool(q) and all(part.strip() in text(r["ticker"])
                                   for part in q.split(" ... ") if part.strip())
        stated = r.get("stated_us")
        status = "none stated"
        if stated:
            if not quote_ok:
                status = "QUOTE NOT FOUND"
            elif stated.lower() == "expired":
                status = "expired" if not (m.get("model_us_date") or "") < dt.date.today().isoformat() else "agrees (past)"
            else:
                try:
                    d = period_end(stated)
                    md = m.get("model_us_date")
                    if md and abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(md)).days) <= 31:
                        status = "agrees"
                    else:
                        status = "DIFFERS"
                except ValueError:
                    status = "UNPARSED"
        rows.append({**r, "model_us_date": m.get("model_us_date"),
                     "model_basis": m.get("model_basis"), "quote_ok": quote_ok, "status": status})
json.dump(rows, open(review / "verified.json", "w"), indent=1)
from collections import Counter
print(Counter(r["status"] for r in rows))
