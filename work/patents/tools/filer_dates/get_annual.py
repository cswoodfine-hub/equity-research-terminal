"""Fetch each filer's latest annual report (10-K or 20-F) from EDGAR as plain text."""
import html, json, re, sys, time, urllib.request, pathlib
UA = {"User-Agent": "Novatalis Research contact@example.com"}
out = pathlib.Path(sys.argv[1])
def get(url):
    time.sleep(0.25)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        return r.read()
meta = {}
for pair in sys.argv[2:]:
    ticker, cik = pair.split(":")
    try:
        sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik}.json"))
        rec = sub["filings"]["recent"]
        idx = next(i for i, f in enumerate(rec["form"]) if f in ("10-K", "20-F"))
        acc, doc = rec["accessionNumber"][idx], rec["primaryDocument"][idx]
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{doc}"
        raw = get(url).decode("utf-8", "replace")
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", html.unescape(text))
        (out / f"{ticker}.txt").write_text(text)
        meta[ticker] = {"form": rec["form"][idx], "accession": acc, "filed": rec["filingDate"][idx],
                        "report_date": rec["reportDate"][idx], "url": url, "chars": len(text)}
        print(ticker, meta[ticker]["form"], acc, rec["filingDate"][idx], len(text), flush=True)
    except Exception as exc:
        print(ticker, "FAILED", exc, flush=True)
(out / "meta.json").write_text(json.dumps(meta, indent=1))
