"""Step 8a: can a company's own trials predict its R&D?

**Data.** Every interventional study each universe company leads, from 2010, any status,
read from ClinicalTrials.gov v2 with the book's own sponsor map (``--download``): phase,
start, primary completion, enrolment and whether that enrolment is actual or anticipated.
Reported R&D is ``ResearchLessExpensedIprd`` in ``financials`` (USD filers, fiscal years),
R&D with acquired in-process R&D taken out, since a licensing upfront expensed through
R&D is not trial spend.

**The proxy.** A study's spend is spread evenly over its run from start to primary
completion, in proportion to its enrolment, so a company-year's load in each phase is
sum(enrolment x share of the study's run inside that year). The cost of a unit of load
in each phase is fitted from the companies' own R&D, not taken from a published rate.

**The test.** The change in R&D from one year to the next, predicted from the change in
load, against two rules the engine could use instead: R&D flat, and R&D as last year's
share of revenue times this year's revenue (the engine's ``rd_pct``, given the actual
revenue, so as generous to it as possible). Fitted on fiscal years up to 2021, scored on
2022 to 2025, and by leaving one company out at a time.

Look-ahead bias, stated: the registry is today's record. A completed study's enrolment
is its actual count, where the company planned on the target.

    python3 work/proxies/tools/trial_spend_study.py --download <dir>
    ER_TOOL_DB=<copy> python3 work/proxies/tools/trial_spend_study.py <dir> [--json out]
"""

import collections
import datetime as dt
import json
import pathlib
import statistics
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ["protocolSection.identificationModule.nctId",
          "protocolSection.statusModule.overallStatus",
          "protocolSection.statusModule.startDateStruct",
          "protocolSection.statusModule.primaryCompletionDateStruct",
          "protocolSection.designModule.phases",
          "protocolSection.designModule.studyType",
          "protocolSection.designModule.enrollmentInfo",
          "protocolSection.sponsorCollaboratorsModule.leadSponsor"]
PHASES = {"EARLY_PHASE1": "p1", "PHASE1": "p1", "PHASE2": "p2", "PHASE3": "p3",
          "PHASE4": "p4"}
BANDS = ("p1", "p2", "p3", "p4")
FIRST_YEAR = 2010
SPLIT_YEAR = 2021                 # fit on fiscal years up to this, score after it


def download(folder):
    import acquired_sponsors
    import company_names
    import ctgov
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection()
    tickers = [r[0] for r in conn.execute("SELECT ticker FROM companies ORDER BY ticker")]
    conn.close()
    for ticker in tickers:
        term = company_names.source_name(ticker, "ctgov_sponsor",
                                         ctgov.SPONSOR_LEAD.get(ticker), None)
        if not term:
            continue
        studies = []
        for sponsor in [term] + acquired_sponsors.for_company(None, ticker):
            token = None
            while True:
                params = {"query.lead": sponsor, "fields": ",".join(FIELDS),
                          "pageSize": 1000,
                          "filter.advanced": f"AREA[StudyType]INTERVENTIONAL AND "
                                             f"AREA[StartDate]RANGE[{FIRST_YEAR}-01-01,MAX]"}
                if token:
                    params["pageToken"] = token
                url = f"{STUDIES_URL}?{urllib.parse.urlencode(params)}"
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Novatalis Research"})
                    data = json.loads(urllib.request.urlopen(req, timeout=120).read())
                except Exception as exc:                   # noqa: BLE001
                    print(f"{ticker} {sponsor}: {exc}", flush=True)
                    break
                studies += data.get("studies", [])
                token = data.get("nextPageToken")
                if not token:
                    break
                time.sleep(0.3)
        (folder / f"{ticker}.json").write_text(json.dumps(studies))
        print(ticker, len(studies), flush=True)


def _date(struct):
    text = (struct or {}).get("date") or ""
    parts = text.split("-")
    try:
        if len(parts) == 3:
            return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return dt.date(int(parts[0]), int(parts[1]), 15)
    except ValueError:
        return None
    return None


def study_rows(studies):
    """[(band, enrolment, start, end, actual?)] for studies with what the spread needs."""
    out, seen = [], set()
    for st in studies:
        p = st.get("protocolSection", {})
        nct = p.get("identificationModule", {}).get("nctId")
        if not nct or nct in seen:
            continue
        seen.add(nct)
        phases = p.get("designModule", {}).get("phases") or []
        bands = [PHASES[x] for x in phases if x in PHASES]
        if not bands:
            continue
        band = max(bands)                  # PHASE1|PHASE2 counts as Phase 2
        info = p.get("designModule", {}).get("enrollmentInfo") or {}
        n = info.get("count")
        start = _date(p.get("statusModule", {}).get("startDateStruct"))
        end = _date(p.get("statusModule", {}).get("primaryCompletionDateStruct"))
        if not n or not start or not end or end <= start:
            continue
        out.append((band, float(n), start, end, info.get("type") == "ACTUAL"))
    return out


def load_by_year(rows):
    """{year: {band: enrolment x share of the study's run inside the year}}."""
    out = collections.defaultdict(lambda: dict.fromkeys(BANDS, 0.0))
    for band, n, start, end, _ in rows:
        days = (end - start).days
        for year in range(start.year, end.year + 1):
            lo = max(start, dt.date(year, 1, 1))
            hi = min(end, dt.date(year, 12, 31))
            share = max(0, (hi - lo).days + 1) / days
            out[year][band] += n * share
    return out


def reported(conn):
    """{ticker: {fiscal year: (R&D less acquired IPR&D, revenue)}}, USD, $mm."""
    out = collections.defaultdict(dict)
    for r in conn.execute(
            "SELECT c.ticker, f.fiscal_year, f.metric, f.value FROM financials f"
            "  JOIN companies c ON c.id = f.company_id"
            " WHERE f.period_type = 'FY' AND f.unit = 'USD'"
            "   AND f.metric IN ('ResearchLessExpensedIprd', 'Revenues')"):
        rd, rev = out[r["ticker"]].get(r["fiscal_year"], (None, None))
        if r["metric"] == "ResearchLessExpensedIprd":
            rd = r["value"] / 1e6
        else:
            rev = r["value"] / 1e6
        out[r["ticker"]][r["fiscal_year"]] = (rd, rev)
    return out


def panel(folder, conn):
    """Company-years: R&D, revenue, load by phase, this year and last."""
    fin = reported(conn)
    rows = []
    for path in sorted(pathlib.Path(folder).glob("*.json")):
        ticker = path.stem
        load = load_by_year(study_rows(json.loads(path.read_text())))
        for year, (rd, rev) in sorted(fin.get(ticker, {}).items()):
            prev = fin[ticker].get(year - 1)
            if year < FIRST_YEAR + 2 or not rd or not prev or not prev[0]:
                continue
            rows.append({"ticker": ticker, "year": year, "rd": rd, "rd_prev": prev[0],
                         "rev": rev, "rev_prev": prev[1],
                         "load": dict(load.get(year, dict.fromkeys(BANDS, 0.0))),
                         "load_prev": dict(load.get(year - 1, dict.fromkeys(BANDS, 0.0)))})
    return rows


def fit(rows):
    """Least squares, no intercept: change in R&D on the change in load by phase."""
    import numpy as np
    x = np.array([[r["load"][b] - r["load_prev"][b] for b in BANDS] for r in rows])
    y = np.array([r["rd"] - r["rd_prev"] for r in rows])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return dict(zip(BANDS, beta))


def predict(r, beta):
    return r["rd_prev"] + sum(beta[b] * (r["load"][b] - r["load_prev"][b]) for b in BANDS)


def rule_rd_pct(r):
    if r["rev"] and r["rev_prev"] and r["rev_prev"] > 0:
        return r["rd_prev"] / r["rev_prev"] * r["rev"]
    return None


def score(rows, beta):
    def ape(pred, r):
        return abs(pred - r["rd"]) / r["rd"]
    flat = [ape(r["rd_prev"], r) for r in rows]
    pct = [ape(p, r) for r in rows if (p := rule_rd_pct(r)) is not None]
    prox = [ape(predict(r, beta), r) for r in rows]
    both = [ape(predict(r, beta), r) for r in rows if rule_rd_pct(r) is not None]
    return {"n": len(rows), "flat": statistics.median(flat),
            "rd_pct": statistics.median(pct) if pct else None, "n_rd_pct": len(pct),
            "proxy": statistics.median(prox),
            "proxy_where_rd_pct": statistics.median(both) if both else None,
            "proxy_beats_flat": sum(ape(predict(r, beta), r) < ape(r["rd_prev"], r)
                                    for r in rows) / len(rows)}


def main(argv):
    if argv and argv[0] == "--download":
        download(argv[1])
        return
    conn = db.get_connection()
    rows = panel(argv[0], conn)
    big = [r for r in rows if (r["rev"] or 0) >= 1000]
    small = [r for r in rows if (r["rev"] or 0) < 1000]
    print(f"{len(rows)} company-years ({len({r['ticker'] for r in rows})} companies): "
          f"{len(big)} with revenue over $1bn, {len(small)} under")
    train = [r for r in rows if r["year"] <= SPLIT_YEAR]
    test = [r for r in rows if r["year"] > SPLIT_YEAR]
    out = {}
    for label, group in (("all", None), ("revenue over $1bn", "big"),
                         ("revenue under $1bn", "small")):
        def sel(rs):
            if group == "big":
                return [r for r in rs if (r["rev"] or 0) >= 1000]
            if group == "small":
                return [r for r in rs if (r["rev"] or 0) < 1000]
            return rs
        beta = fit(sel(train))
        s = score(sel(test), beta)
        out[label] = {"beta_usd_mm_per_patient_load": beta, "time_split": s}
        print(f"\n{label}: cost per patient-year of load, $mm, fitted to {SPLIT_YEAR}: "
              + ", ".join(f"{b} {beta[b]:.3f}" for b in BANDS))
        print(f"  scored {SPLIT_YEAR + 1} on (n={s['n']}): median abs error of the R&D level"
              f" flat {s['flat']:.1%}, rd_pct x revenue {s['rd_pct']:.1%} (n={s['n_rd_pct']}),"
              f" proxy {s['proxy']:.1%} (on rd_pct's rows {s['proxy_where_rd_pct']:.1%});"
              f" proxy beats flat on {s['proxy_beats_flat']:.0%}")
        # Leave one company out.
        tickers = sorted({r["ticker"] for r in sel(rows)})
        errs = {"flat": [], "rd_pct": [], "proxy": []}
        for t in tickers:
            beta_t = fit([r for r in sel(rows) if r["ticker"] != t])
            for r in sel(rows):
                if r["ticker"] != t:
                    continue
                errs["flat"].append(abs(r["rd_prev"] - r["rd"]) / r["rd"])
                errs["proxy"].append(abs(predict(r, beta_t) - r["rd"]) / r["rd"])
                if (p := rule_rd_pct(r)) is not None:
                    errs["rd_pct"].append(abs(p - r["rd"]) / r["rd"])
        out[label]["leave_one_company_out"] = {k: statistics.median(v) if v else None
                                               for k, v in errs.items()}
        print("  leave one company out, median abs error: " + ", ".join(
            f"{k} {v:.1%}" for k, v in out[label]["leave_one_company_out"].items() if v))
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps({"report": out, "rows": rows}, indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
