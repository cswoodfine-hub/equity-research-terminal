"""Step 8c: what the market moved on past readouts, beside the model's stakes.

**Events.** Each "Other events" (Item 8.01) or "Regulation FD" (Item 7.01) 8-K in
``filings`` is read from EDGAR (``--download``), and the item's text kept. A filing is a
readout when that text names a trial or a phase and results or data. Its outcome is read
by fixed wording, never by judgement:
- failed: "did not meet", "did not achieve", "failed to", "not statistically
  significant", "discontinue";
- met: "met its primary", "met the primary", "achieved its primary", "achieved the
  primary", "statistically significant", "positive topline", "positive results";
- otherwise unclassified.

**Move.** The two-day return from the close before the filing date to the close the day
after it, less the health care sector ETF (XLV) over the same days, from ``prices`` and
``benchmark_prices``.

**The model's side.** The latest ``gate_calls`` row for each pending catalyst: the move on
success, (per_share_success - per_share_now) / price, and on failure, by the company's
market capitalisation band.

    ER_TOOL_DB=<copy> python3 work/proxies/tools/readout_moves.py --download <dir>
    ER_TOOL_DB=<copy> python3 work/proxies/tools/readout_moves.py <dir> [--json out]
"""

import bisect
import collections
import html
import json
import os
import pathlib
import re
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

UA = os.getenv("SEC_USER_AGENT") or "Novatalis Research research@example.com"
_ITEM = re.compile(r"item\s*(8\.01|7\.01)", re.I)
READOUT = re.compile(r"\b(phase\s*(1|2|3|i{1,3})|trial|study)\b", re.I)
RESULTS = re.compile(r"\b(topline|top-line|results|data|primary endpoint)\b", re.I)
FAILED = re.compile(r"did not (meet|achieve)|failed to|not statistically significant|"
                    r"discontinu|did not demonstrate", re.I)
MET = re.compile(r"met (its|the|both|all) (co-)?primary|achieved (its|the) (co-)?primary|"
                 r"statistically significant|positive topline|positive top-line|"
                 r"positive results", re.I)
BANDS = ((0, 1e9, "under $1bn"), (1e9, 10e9, "$1bn to $10bn"), (10e9, 1e15, "over $10bn"))


def _text(raw):
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return " ".join(html.unescape(raw).split())


def download(folder):
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection()
    rows = conn.execute(
        "SELECT f.accession, f.filed_date, f.url, c.ticker FROM filings f"
        "  JOIN companies c ON c.id = f.company_id WHERE f.form_type = '8-K'"
        "   AND (f.title LIKE '%Other events%' OR f.title LIKE '%Regulation FD%')").fetchall()
    out_path = folder / "items.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["accession"] for l in out_path.open()}
    with out_path.open("a") as out:
        for r in rows:
            if r["accession"] in done or not r["url"]:
                continue
            try:
                req = urllib.request.Request(r["url"], headers={"User-Agent": UA})
                text = _text(urllib.request.urlopen(req, timeout=60).read().decode(
                    "utf-8", "replace"))
            except Exception as exc:                       # noqa: BLE001
                print(r["accession"], exc, flush=True)
                continue
            m = _ITEM.search(text)
            item = text[m.start(): m.start() + 2500] if m else ""
            out.write(json.dumps({"accession": r["accession"], "ticker": r["ticker"],
                                  "filed": r["filed_date"], "item": item}) + "\n")
            time.sleep(0.25)
    print("done")


def classify(item):
    if not (READOUT.search(item) and RESULTS.search(item)):
        return None
    if FAILED.search(item):
        return "failed"
    if MET.search(item):
        return "met"
    return "unclassified"


def _series(conn, ticker):
    rows = conn.execute(
        "SELECT p.as_of, p.close, p.market_cap FROM prices p JOIN companies c"
        "  ON c.id = p.company_id WHERE c.ticker = ? AND p.interval = '1d'"
        "   AND p.close IS NOT NULL ORDER BY p.as_of", (ticker,)).fetchall()
    return [r["as_of"][:10] for r in rows], [r["close"] for r in rows], \
        [r["market_cap"] for r in rows]


def _bench(conn):
    rows = conn.execute("SELECT as_of, COALESCE(adjclose, close) AS c FROM benchmark_prices"
                        " WHERE symbol = 'XLV' ORDER BY as_of").fetchall()
    return [r["as_of"][:10] for r in rows], [r["c"] for r in rows]


def move(dates, closes, day):
    """Close before ``day`` to the close one trading day after it."""
    i = bisect.bisect_left(dates, day)
    if i < 1 or i + 1 >= len(dates):
        return None
    return closes[i + 1] / closes[i - 1] - 1


def band(cap):
    for lo, hi, name in BANDS:
        if cap is not None and lo <= cap < hi:
            return name
    return None


def model_stakes(conn):
    """{band: {"success": [...], "failure": [...]}} from the latest call per catalyst."""
    latest = {}
    for r in conn.execute("SELECT * FROM gate_calls ORDER BY as_of"):
        latest[r["catalyst_id"]] = dict(r)
    caps = {}
    for r in conn.execute(
            "SELECT c.ticker, p.market_cap FROM prices p JOIN companies c ON c.id ="
            " p.company_id WHERE p.interval = '1d' AND p.market_cap IS NOT NULL"
            " ORDER BY p.as_of"):
        caps[r["ticker"]] = r["market_cap"]
    out = collections.defaultdict(lambda: {"success": [], "failure": []})
    for call in latest.values():
        price, now = call["price"], call["per_share_now"]
        if not price or now is None:
            continue
        b = band(caps.get(call["ticker"]))
        if call["per_share_success"] is not None:
            out[b]["success"].append((call["per_share_success"] - now) / price)
        if call["per_share_failure"] is not None:
            out[b]["failure"].append((call["per_share_failure"] - now) / price)
    return out


def main(argv):
    if argv and argv[0] == "--download":
        download(argv[1])
        return
    conn = db.get_connection()
    items = [json.loads(l) for l in (pathlib.Path(argv[0]) / "items.jsonl").open()]
    bd, bc = _bench(conn)
    series = {}
    events = []
    for it in items:
        kind = classify(it["item"])
        if not kind:
            continue
        if it["ticker"] not in series:
            series[it["ticker"]] = _series(conn, it["ticker"])
        dates, closes, caps = series[it["ticker"]]
        m, b = move(dates, closes, it["filed"]), move(bd, bc, it["filed"])
        if m is None or b is None:
            continue
        i = bisect.bisect_left(dates, it["filed"])
        events.append({"ticker": it["ticker"], "filed": it["filed"], "outcome": kind,
                       "abnormal": m - b, "band": band(caps[i - 1] if i else None)})
    print(f"{len(items)} items read; {len(events)} readouts with prices "
          f"({collections.Counter(e['outcome'] for e in events)})")
    stakes = model_stakes(conn)
    print("\nband | outcome | n | realised abnormal 2-day move: median, interquartile | model's move on that outcome (pending calls): median, n")
    report = []
    for _, _, name in BANDS:
        for kind, leg in (("met", "success"), ("failed", "failure"), ("unclassified", None)):
            v = sorted(e["abnormal"] for e in events if e["band"] == name and e["outcome"] == kind)
            if not v:
                continue
            mv = sorted(stakes.get(name, {}).get(leg, [])) if leg else []
            line = {"band": name, "outcome": kind, "n": len(v),
                    "median": statistics.median(v), "q1": v[len(v) // 4],
                    "q3": v[3 * len(v) // 4],
                    "model_median": statistics.median(mv) if mv else None,
                    "model_n": len(mv)}
            report.append(line)
            print(f"  {name:13s} | {kind:12s} | {len(v):3d} | {line['median']:+.1%}, "
                  f"{line['q1']:+.1%} to {line['q3']:+.1%} | "
                  + (f"{line['model_median']:+.1%}, n={len(mv)}" if mv else "n/a"))
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps({"events": events, "report": report}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
