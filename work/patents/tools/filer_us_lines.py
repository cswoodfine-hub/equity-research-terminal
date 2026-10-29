"""Every universe filer's US product revenue, by year, from the SEC data sets since 2010.

The SEC's quarterly Financial Statement Data Sets keep each XBRL fact's dimensions in a
``segments`` column, so a product's US line is a row like

    SalesRevenueGoodsNet  20151231  4  USD  Geographical=US;ProductOrService=Januvia  ...

This reads the first two quarters of every year (when 10-Ks and 20-Fs are filed), keeps
the annual filings of the universe's companies, and writes one row per filer, product
and fiscal year with the US figure. A product's figure is taken at its shallowest tagged
level, and only when that level is one row; a later filing's figure for a year replaces
an earlier one's, since a restatement is the filer's correction. Tags: anything
beginning "Revenue" or "SalesRevenue" (the pre-2018 taxonomy), net of nothing.

Each quarter's file (50 to 100mb) is downloaded, read and deleted in turn.

    ER_TOOL_DB=<copy> python3 work/patents/tools/filer_us_lines.py <scratch dir> <out.csv>
"""

import csv
import io
import os
import pathlib
import sys
import time
import urllib.request
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402
from fetchers import product_revenue_sec as prs  # noqa: E402

URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip"
UA = os.getenv("SEC_USER_AGENT") or "Novatalis Research research@example.com"
FIRST_YEAR, LAST_YEAR = 2010, 2026


def _tag_ok(tag):
    return tag.startswith("Revenue") or tag.startswith("SalesRevenue")


def us_lines(rows, adsh):
    """{(period end, product member): (value, unit, tag)} for one filing's US rows."""
    by = {}
    for row in rows:
        if row.get("adsh") != adsh or row.get("coreg") or row.get("qtrs") != "4":
            continue
        if not _tag_ok(row.get("tag") or ""):
            continue
        axes = prs.parse_segments(row.get("segments"))
        product = next((axes[a] for a in prs.PRODUCT_AXES if a in axes), None)
        geography = next((axes[a] for a in prs.GEOGRAPHY_AXES if a in axes), None)
        if not product or not geography or prs.region_code(geography) != "US":
            continue
        if prs.is_aggregate(product):
            continue
        extras = tuple(sorted((k, v) for k, v in axes.items()
                              if k not in prs.PRODUCT_AXES and k not in prs.GEOGRAPHY_AXES))
        try:
            value = float(row["value"])
        except (TypeError, ValueError):
            continue
        by.setdefault((row["ddate"], product), {}).setdefault(extras, []).append(
            (value, row.get("uom") or "", row["tag"]))
    out = {}
    for key, levels in by.items():
        shallow = min(len(e) for e in levels)
        top = [v for e, v in levels.items() if len(e) == shallow]
        if len(top) != 1:
            continue
        values = top[0]
        # One tag per figure: a filer that tags both SalesRevenueGoodsNet and Revenues for
        # the same product and year states one number twice, not two numbers.
        distinct = {(round(v, -3), u) for v, u, _ in values}
        if len(distinct) != 1:
            continue
        value, unit, tag = values[0]
        out[key] = (value, unit, tag)
    return out


def main(scratch, out_csv):
    scratch = pathlib.Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    conn = db.get_connection()
    ciks = {str(r["cik"]).lstrip("0"): r["ticker"] for r in conn.execute(
        "SELECT ticker, cik FROM companies WHERE cik IS NOT NULL")}
    conn.close()
    best = {}            # (ticker, member, fy) -> (filed, value, unit, tag, adsh)
    for year in range(FIRST_YEAR, LAST_YEAR + 1):
        for quarter in (1, 2):
            name = f"{year}q{quarter}"
            path = scratch / f"{name}.zip"
            try:
                req = urllib.request.Request(URL.format(q=name), headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=600) as resp, open(path, "wb") as fh:
                    while chunk := resp.read(1 << 20):
                        fh.write(chunk)
            except Exception as exc:                       # noqa: BLE001
                print(f"{name}: not read ({exc})", flush=True)
                path.unlink(missing_ok=True)
                continue
            found = 0
            with zipfile.ZipFile(path) as archive:
                filings = {}
                with archive.open("sub.txt") as handle:
                    for row in csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                              delimiter="\t"):
                        ticker = ciks.get(str(row.get("cik") or "").lstrip("0"))
                        if ticker and row.get("form") in ("10-K", "20-F", "10-K/A", "20-F/A"):
                            filings[row["adsh"]] = (ticker, row.get("filed") or "")
                rows = {a: [] for a in filings}
                with archive.open("num.txt") as handle:
                    for row in csv.DictReader(io.TextIOWrapper(handle, "latin-1"),
                                              delimiter="\t"):
                        bucket = rows.get(row.get("adsh"))
                        if bucket is not None and row.get("segments"):
                            bucket.append(row)
            for adsh, (ticker, filed) in filings.items():
                for (ddate, member), (value, unit, tag) in us_lines(rows[adsh], adsh).items():
                    key = (ticker, member, int(ddate[:4]))
                    if key not in best or filed >= best[key][0]:
                        best[key] = (filed, value, unit, tag, adsh)
                        found += 1
            path.unlink(missing_ok=True)
            print(f"{name}: {len(filings)} annual filings, {found} US product-years",
                  flush=True)
            time.sleep(0.5)
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ticker", "member", "product", "fiscal_year", "us_value", "unit",
                    "tag", "accession", "filed"])
        for (ticker, member, fy), (filed, value, unit, tag, adsh) in sorted(best.items()):
            w.writerow([ticker, member, prs.display_name(member), fy, value, unit, tag,
                        adsh, filed])
    print(f"{len(best)} rows written to {out_csv}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
