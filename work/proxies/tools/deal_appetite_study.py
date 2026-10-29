"""Step 8e: does revenue about to lose exclusivity predict deal spend?

**Gap.** For each company and year Y from 2021: the share of its product revenue
(``asset_revenue``, fiscal year Y) carried by products whose LOE (``loe.for_assets``) falls
in the five years after Y.

**Deal spend.** The cash the company paid for deals in Y+1 and Y+2, from its own cash flow
statement and income statement (``financials``, USD): acquisitions net of cash acquired,
acquired intangibles, and acquired in-process R&D expensed. As a share of revenue in Y.

**Test.** The rank correlation across company-years, and deal spend for the companies
with the largest gaps against the rest.

LOE dates are today's record; a date the company only disclosed later is a look-ahead.

    ER_TOOL_DB=<copy> python3 work/proxies/tools/deal_appetite_study.py [--json out]
"""

import collections
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402
import loe  # noqa: E402

DEAL_METRICS = ("AcquisitionsNet", "AcquiredIntangibles", "AcquiredIprd")


def _rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    for r, i in enumerate(order):
        ranks[i] = r
    return ranks


def spearman(x, y):
    import numpy as np
    return float(np.corrcoef(_rank(x), _rank(y))[0, 1])


def main(argv):
    conn = db.get_connection()
    dates = loe.for_assets(conn, exclude_orphan=True)
    revenue = collections.defaultdict(dict)       # company -> year -> {asset: value}
    for r in conn.execute(
            "SELECT a.owner_company_id AS cid, ar.asset_id, ar.fiscal_year, ar.value"
            "  FROM asset_revenue ar JOIN assets a ON a.id = ar.asset_id"
            " WHERE ar.period = 'FY' AND ar.value > 0"):
        revenue[r["cid"]].setdefault(r["fiscal_year"], {})[r["asset_id"]] = r["value"]
    deals = collections.defaultdict(lambda: collections.defaultdict(float))
    for r in conn.execute(
            f"SELECT company_id, fiscal_year, SUM(ABS(value)) AS v FROM financials"
            f" WHERE period_type = 'FY' AND unit = 'USD' AND metric IN"
            f" ({','.join('?' * len(DEAL_METRICS))}) GROUP BY company_id, fiscal_year",
            DEAL_METRICS):
        deals[r["company_id"]][r["fiscal_year"]] = r["v"]
    tickers = {r["id"]: r["ticker"] for r in conn.execute("SELECT id, ticker FROM companies")}
    rows = []
    for cid, years in revenue.items():
        if cid not in deals:
            continue
        for year, products in years.items():
            total = sum(products.values())
            if total < 1e9 or year + 2 > 2025:
                continue
            at_risk = sum(v for a, v in products.items()
                          if (dates.get(a) or {}).get("date")
                          and year < int(dates[a]["date"][:4]) <= year + 5)
            spend = deals[cid].get(year + 1, 0.0) + deals[cid].get(year + 2, 0.0)
            rows.append({"ticker": tickers[cid], "year": year, "gap": at_risk / total,
                         "spend_share": spend / total})
    print(f"{len(rows)} company-years with product revenue over $1bn and deal spend on file")
    if len(rows) < 8:
        return
    rho = spearman([r["gap"] for r in rows], [r["spend_share"] for r in rows])
    print(f"rank correlation, revenue share losing exclusivity in 5 years against deal "
          f"spend in the next 2 years: {rho:+.2f}")
    rows.sort(key=lambda r: r["gap"])
    third = len(rows) // 3
    for name, part in (("smallest third of gaps", rows[:third]),
                       ("middle third", rows[third:2 * third]),
                       ("largest third of gaps", rows[2 * third:])):
        print(f"  {name:22s}: gap median {statistics.median(r['gap'] for r in part):.0%}, "
              f"deal spend over two years median {statistics.median(r['spend_share'] for r in part):.0%}"
              f" of revenue, mean {statistics.mean(r['spend_share'] for r in part):.0%} (n={len(part)})")
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
