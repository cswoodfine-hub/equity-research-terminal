"""Has large-cap pharma revenue, in real terms, exceeded its own prior peak?

The working behind docs/perpetuity.md, kept so the figures in it can be re-run rather
than taken on trust. Reads the book's own `financials` and the US CPI from FRED, writes
nothing, and prints every number the document quotes.

    backend/.venv/bin/python work/perpetuity/measure.py

The one judgement in it is the classification below. A step in revenue does not say what
caused it, and the size of a step does not either: Gilead's 31% in 2015 and Lilly's 41%
in 2025 are launch ramps, which is exactly what the future pipeline line models, while
Merck's 65% in 2010 is Schering-Plough, which it does not. Classifying on size alone
throws out the organic breakouts and biases the answer toward the cap.
"""

import collections
import csv
import io
import json
import statistics
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import db                                                          # noqa: E402

BASE = 2025
FLOOR = 25e9              # the size the question is about
CPI_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL"

# Each step year named by what caused it, with the deal and its date where it was bought.
BOUGHT = {("MRK", 2010): "Schering-Plough, $41bn, closed Nov 2009",
          ("BMY", 2020): "Celgene, $74bn, closed Nov 2019",
          ("ABBV", 2020): "Allergan, $63bn, closed May 2020",
          ("AZN", 2021): "Alexion, $39bn, closed Jul 2021"}
LAUNCHED = {("GILD", 2015): "Harvoni and Sovaldi, the hepatitis C ramp",
            ("LLY", 2024): "Mounjaro and Zepbound",
            ("LLY", 2025): "Mounjaro and Zepbound"}


def cpi() -> dict:
    """{year: annual average}. A partial year is averaged over the months it has."""
    raw = urllib.request.urlopen(CPI_URL, timeout=60).read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(raw)))
    field = [k for k in rows[0] if k.lower() not in ("observation_date", "date")][0]
    months = collections.defaultdict(list)
    for row in rows:
        value = row[field]
        if value in ("", "."):
            continue
        months[int((row.get("observation_date") or row["DATE"])[:4])].append(float(value))
    return {y: sum(v) / len(v) for y, v in months.items()}


def real_revenue(index: dict) -> tuple[dict, dict]:
    """{ticker: {year: revenue in BASE-year money}}, and the reporting currency.

    Each company stays in its own currency: no exchange rate belongs in a growth rate
    measured within one filer.
    """
    conn = db.get_connection()
    try:
        series, units = collections.defaultdict(dict), {}
        for row in conn.execute(
                """SELECT c.ticker t, f.fiscal_year y, f.value v, f.unit u
                     FROM financials f JOIN companies c ON c.id = f.company_id
                    WHERE f.metric = 'Revenues' AND f.period_type = 'FY'
                      AND f.value IS NOT NULL"""):
            if row["y"] in index:
                series[row["t"]][row["y"]] = row["v"] * index[BASE] / index[row["y"]]
                units[row["t"]] = row["u"]
    finally:
        conn.close()
    return series, units


def growth_windows(real, units, horizon, floor, drop_bought):
    """{ticker: [real CAGR]} over every `horizon`-year window starting above `floor`."""
    out = collections.defaultdict(list)
    for ticker, s in real.items():
        if units[ticker] != "USD":          # a foreign filer needs its own deflator
            continue
        for year in sorted(s):
            if not (s[year] >= floor and (year + horizon) in s):
                continue
            if drop_bought and any((ticker, k) in BOUGHT
                                   for k in range(year + 1, year + horizon + 1)):
                continue
            out[ticker].append((s[year + horizon] / s[year]) ** (1.0 / horizon) - 1)
    return out


def main() -> None:
    index = cpi()
    real, units = real_revenue(index)
    span = (index[BASE] / index[2007]) ** (1 / (BASE - 2007)) - 1
    print(f"US CPI 2007 to {BASE}: {span:.2%} a year, against the 2.35% the book assumes\n")

    print(f"Ten-year real revenue growth, start above ${FLOOR/1e9:.0f}bn")
    for drop, label in ((False, "every window"), (True, "purchases held out")):
        per = growth_windows(real, units, 10, FLOOR, drop)
        pooled = sorted(v for vs in per.values() for v in vs)
        print(f"  {label:20} companies={len(per):>2} windows={len(pooled):>3}  "
              f"median {statistics.median(pooled):>6.2%}  "
              f"p25 {pooled[len(pooled)//4]:>6.2%}  p75 {pooled[3*len(pooled)//4]:>6.2%}  "
              f"one per company {statistics.median(sorted(statistics.median(v) for v in per.values())):>6.2%}")

    print("\nConditioned on a peak: real peak reached by 2015, against real 2025")
    ratios = []
    for ticker in sorted(real):
        s = real[ticker]
        early = {y: v for y, v in s.items() if y <= 2015}
        if units[ticker] != "USD" or 2025 not in s or len(early) < 6:
            continue
        peak_year = max(early, key=lambda y: early[y])
        if early[peak_year] < 10e9:
            continue
        ratio = s[2025] / early[peak_year]
        ratios.append(ratio)
        print(f"  {ticker:6} peak {early[peak_year]/1e9:>6.1f}bn in {peak_year}  "
              f"2025 {s[2025]/1e9:>6.1f}bn  x{ratio:.2f}")
    print(f"  {'':6} {len([r for r in ratios if r > 1])} of {len(ratios)} exceeded, "
          f"median x{statistics.median(ratios):.2f}")

    print("\nThe breakout that did not hold")
    for ticker in ("GILD", "BIIB"):
        s = real[ticker]
        peak_year = max(s, key=lambda y: s[y])
        print(f"  {ticker:6} peak {s[peak_year]/1e9:>5.1f}bn in {peak_year}, "
              f"2025 {s[2025]/1e9:>5.1f}bn = x{s[2025]/s[peak_year]:.2f}, "
              f"{(s[2025]/s[peak_year])**(1/(2025-peak_year))-1:+.1%} a year since")

    print("\nStep years, classified by cause")
    for (ticker, year), why in sorted({**BOUGHT, **LAUNCHED}.items()):
        kind = "bought  " if (ticker, year) in BOUGHT else "launched"
        step = real[ticker][year] / real[ticker][year - 1] - 1
        print(f"  {ticker:5} {year}  {step:>+5.0%}  {kind}  {why}")


if __name__ == "__main__":
    main()
