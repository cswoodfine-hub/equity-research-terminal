"""Does a product past its loss keep falling, or level off? Backtest of the fade.

For every product with a yearly series and an LOE date the valuation uses
(``loe.for_assets``, orphan left out), take each year t where the series fell and the loss
was already past. Two series: the filer's reported full years (``asset_revenue``, thin),
and CMS Medicare spending, Part D and Part B summed (``drug_demand``, 2013 on: gross and
Medicare only, but long). Project the next k years two ways from year t's level and
rate, and compare with what the filer reported:

- fade: the rate fades linearly to zero over five years (the engine's rule today);
- hold: the rate holds, no steeper than the erosion row for that many years past the loss;
- curve: the erosion row's own decay for that many years past the loss, ignoring the rate.

Reports the median log error of each against the reported level, by horizon.
``--recent`` keeps only years within three of the loss, the case a recent biosimilar
launch makes.

    ER_TOOL_DB=<copy> python3 work/patents/tools/decline_backtest.py
"""

import math
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import assumptions  # noqa: E402
import db  # noqa: E402
import loe  # noqa: E402

FADE_YEARS = 5


def path(level, rate, k, hold, cap):
    out = []
    for i in range(1, k + 1):
        if hold == "curve":
            r = -cap(i) if cap(i) is not None else rate
        elif hold:
            r = max(rate, -cap(i)) if cap(i) is not None else rate
        else:
            r = rate * max(0.0, 1 - i / FADE_YEARS)
        level *= 1 + r
        out.append(level)
    return out


def main():
    conn = db.get_connection()
    series = {}
    query = ("SELECT asset_id, year AS fiscal_year, SUM(total_spending) AS value"
             " FROM drug_demand WHERE asset_id IS NOT NULL GROUP BY asset_id, year"
             if "--cms" in sys.argv else
             "SELECT asset_id, fiscal_year, value FROM asset_revenue"
             " WHERE period = 'FY' AND value > 0")
    for r in conn.execute(query):
        if r["value"] and r["value"] > 0:
            series.setdefault(r["asset_id"], {})[int(r["fiscal_year"])] = r["value"]
    found = loe.for_assets(conn, list(series), exclude_orphan=True)
    modality = {r["id"]: r["modality"] for r in conn.execute("SELECT id, modality FROM assets")}
    rows = assumptions.erosion_defaults()
    errs = {k: {"fade": [], "hold": [], "curve": []} for k in (1, 2, 3, 4, 5, 6)}
    cases = 0
    for aid, by_year in series.items():
        f = found.get(aid) or {}
        if not f.get("date"):
            continue
        loe_year = int(f["date"][:4])
        row = rows.get(modality.get(aid) or "unknown") or rows.get("unknown")
        for t in sorted(by_year):
            if t - 1 not in by_year or t <= loe_year:
                continue
            rate = by_year[t] / by_year[t - 1] - 1
            if rate >= 0:
                continue
            if "--recent" in sys.argv and t - loe_year > 3:
                continue
            cases += 1
            def cap(i, t=t, loe_year=loe_year, row=row):
                late = row.get("late_decay_pct")
                if late is not None and row.get("late_from_year") and \
                        t + i - loe_year >= row["late_from_year"]:
                    return late
                return row.get("decay_pct")

            for k in errs:
                if t + k not in by_year:
                    continue
                actual = by_year[t + k]
                for name, hold in (("fade", False), ("hold", True), ("curve", "curve")):
                    projected = path(by_year[t], rate, k, hold, cap)[-1]
                    errs[k][name].append(math.log(projected / actual))
    print(f"{cases} product-years falling after their loss")
    for k, e in errs.items():
        if not e["fade"]:
            continue
        def summary(v):
            return (f"median {statistics.median(v):+.3f}, median abs "
                    f"{statistics.median(abs(x) for x in v):.3f}")
        print(f"  {k} years ahead (n {len(e['fade'])}): fade {summary(e['fade'])}; "
              f"hold {summary(e['hold'])}; curve {summary(e['curve'])}")


if __name__ == "__main__":
    main()
