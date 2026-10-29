"""Step 8b: how much cash left predicts a raise, and how much it dilutes.

For every company-quarter in ``financials`` where the trailing twelve months of operating
cash flow is negative (a company burning cash), the months of cash left: cash and
short- and long-term investments (``runway.liquidity``'s definition) over the trailing
burn. Then what followed over the next four quarters:

- the growth in weighted average diluted shares, quarter four against quarter zero;
- whether financing inflows over those quarters exceeded 10% of the cash on hand.

Grouped by months of cash, that is a measured raise probability and dilution, the
quantity a per-share value is missing for a company that has to finance before its
readout.

    ER_TOOL_DB=<copy> python3 work/proxies/tools/runway_study.py [--json out]
"""

import collections
import datetime as dt
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

BUCKETS = ((0, 6), (6, 12), (12, 18), (18, 24), (24, 36), (36, 60), (60, 10 ** 6))
RAISE_SHARE = 0.10


def _quarters(conn, company_id, metric):
    """{period end: value} for a quarterly flow. EDGAR states cash flow cumulative from
    the start of the fiscal year ("3M", "6M", "9M", "12M"), so each quarter is the
    difference between consecutive cumulative figures inside one fiscal year."""
    cum = collections.defaultdict(dict)        # fiscal year -> {months: (end, value)}
    for r in conn.execute(
            "SELECT period_end, value, fiscal_period, fiscal_year FROM financials"
            " WHERE company_id = ? AND metric = ? AND value IS NOT NULL"
            "   AND fiscal_period IN ('3M', '6M', '9M', '12M')", (company_id, metric)):
        months = int(r["fiscal_period"][:-1])
        cum[r["fiscal_year"]][months] = (r["period_end"], r["value"])
    q = {}
    for year, by in cum.items():
        for months in (3, 6, 9, 12):
            if months not in by:
                continue
            end, value = by[months]
            if months == 3:
                q[end] = value
            elif months - 3 in by:
                q[end] = value - by[months - 3][1]
    return q


def _instant(conn, company_id, metric):
    return {r["period_end"]: r["value"] for r in conn.execute(
        "SELECT period_end, value FROM financials WHERE company_id = ? AND metric = ?"
        "   AND period_type = 'instant' AND value IS NOT NULL", (company_id, metric))}


def company_quarters(conn, company_id):
    ocf = _quarters(conn, company_id, "CashFlowOperating")
    fin = _quarters(conn, company_id, "CashFlowFinancing")
    shares = {r["period_end"]: r["value"] for r in conn.execute(
        "SELECT period_end, value FROM financials WHERE company_id = ?"
        "   AND metric = 'WeightedAverageDilutedShares' AND period_type = 'Q'", (company_id,))}
    cash = _instant(conn, company_id, "CashAndEquivalents")
    sti = _instant(conn, company_id, "ShortTermInvestments")
    lti = _instant(conn, company_id, "LongTermInvestments")
    ends = sorted(ocf)
    out = []
    for i, end in enumerate(ends):
        if i < 3 or end not in cash:
            continue
        window = ends[i - 3:i + 1]
        span = (dt.date.fromisoformat(window[-1]) - dt.date.fromisoformat(window[0])).days
        if not 250 <= span <= 300:
            continue                      # four consecutive quarters, nothing missing
        ttm = sum(ocf[e] for e in window)
        if ttm >= 0:
            continue
        liquid = cash[end] + (sti.get(end) or 0) + (lti.get(end) or 0)
        months = liquid / (-ttm / 12)
        ahead = [e for e in ends[i + 1:i + 5]]
        if len(ahead) < 4:
            continue
        s0, s4 = shares.get(end), shares.get(ahead[-1])
        raised = sum(max(0.0, fin.get(e) or 0.0) for e in ahead)
        out.append({"end": end, "months": months, "cash": liquid, "burn": -ttm,
                    "share_growth": (s4 / s0 - 1) if s0 and s4 else None,
                    "raised": raised, "raised_share": raised / liquid if liquid > 0 else None})
    return out


def main(argv):
    conn = db.get_connection()
    rows = []
    for c in conn.execute("SELECT id, ticker FROM companies"):
        for r in company_quarters(conn, c["id"]):
            rows.append({"ticker": c["ticker"], **r})
    print(f"{len(rows)} burning company-quarters with four quarters after, "
          f"{len({r['ticker'] for r in rows})} companies")
    report = []
    print("months of cash | n | raised over 10% of cash within 12m | share growth 12m: median, mean, 75th pct | raised as share of cash, median where raised")
    for lo, hi in BUCKETS:
        b = [r for r in rows if lo <= r["months"] < hi]
        g = sorted(r["share_growth"] for r in b if r["share_growth"] is not None)
        if len(b) < 5 or not g:
            continue
        raised = [r for r in b if (r["raised_share"] or 0) > RAISE_SHARE]
        sizes = [r["raised_share"] for r in raised]
        line = {"months": f"{lo}-{hi if hi < 10 ** 6 else 'up'}", "n": len(b),
                "p_raise": len(raised) / len(b), "growth_median": statistics.median(g),
                "growth_mean": statistics.mean(g), "growth_p75": g[3 * len(g) // 4],
                "raise_size_median": statistics.median(sizes) if sizes else None}
        report.append(line)
        print(f"  {line['months']:>7} | {line['n']:4d} | {line['p_raise']:.0%} | "
              f"{line['growth_median']:+.1%}, {line['growth_mean']:+.1%}, {line['growth_p75']:+.1%} | "
              + (f"{line['raise_size_median']:.2f}" if sizes else "n/a"))
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps({"report": report, "rows": rows}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
