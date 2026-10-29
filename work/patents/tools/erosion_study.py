"""Measure brand erosion after a first generic launch, from Medicare Part D.

Events: every reference drug on the FDA Paragraph IV list with a first commercial
marketing date (``paragraph_iv_list``), earliest per brand name. Outcome: the brand's
national Part D gross drug cost and claims, by year, from the CMS series "Medicare Part D
Prescribers - by Geography and Drug" (one dataset a year, 2013 on, National rows),
read from JSON files written by ``--download``.

Each event is measured on the forecast engine's own footing (forecast.erosion_factor):
the launch year L is left untouched and the year-one drop lands in L+1. The ratio for
year k is the brand's figure in L+k over its figure in L-1, the last full year before
any generic. So ``retained[1]`` is 1 - year1_pct and ``retained[k]/retained[k-1]`` is
1 - that year's decay.

Part D cost is gross of rebates and is volume times list price, so it is a proxy for a
brand's US revenue line, not the line. Claims are volume alone. Both are reported.

    ER_TOOL_DB=<copy> python3 work/patents/tools/erosion_study.py --download <dir>
    ER_TOOL_DB=<copy> python3 work/patents/tools/erosion_study.py <dir> [--json out]
"""

import collections
import json
import pathlib
import re
import statistics
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

SERIES = "Medicare Part D Prescribers - by Geography and Drug"
MIN_BASE_COST = 10e6          # a brand under $10m in Part D before launch is noise
HORIZON = 6


def download(folder):
    import cms_catalogue
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for year in cms_catalogue.years(cms_catalogue.load(), SERIES):
        rows, offset = [], 0
        while True:
            query = urllib.parse.urlencode({"filter[Prscrbr_Geo_Lvl]": "National",
                                            "size": 5000, "offset": offset})
            url = (f"https://data.cms.gov/data-api/v1/dataset/{year['uuid']}/data?"
                   f"{query}")
            req = urllib.request.Request(url, headers={"User-Agent": "Novatalis Research"})
            page = json.loads(urllib.request.urlopen(req, timeout=120).read())
            rows += page
            offset += 5000
            if len(page) < 5000:
                break
        (folder / f"{year['year']}.json").write_text(json.dumps(rows))
        print(year["year"], len(rows))


def _name(text):
    text = (text or "").upper().replace("_X000D_", " ")
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\bNDA\s*[\d-]+\b", " ", text)
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", text).split())


def route(form):
    f = (form or "").lower()
    if any(w in f for w in ("inhal", "aerosol", "nebuliz")):
        return "inhaled"
    if any(w in f for w in ("inject", "subcutaneous", "intravenous", "for injection",
                            "infusion", "intramuscular", "vial", "syringe", "pen")):
        return "injectable"
    if "ophthalmic" in f or "otic" in f:
        return "eye or ear"
    if "nasal" in f:
        return "nasal"
    if any(w in f for w in ("topical", "cream", "gel", "ointment", "lotion", "patch",
                            "transdermal", "foam", "shampoo", "film, extended")):
        return "topical or transdermal"
    if any(w in f for w in ("tablet", "capsule", "oral", "granule", "pellet", "powder",
                            "suspension", "solution", "chewable", "sprinkle", "syrup",
                            "elixir")):
        return "oral"
    return "other"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_partd(folder):
    """{year: {brand name: (cost, claims, generic name)}}, brand rows only."""
    out = {}
    for path in sorted(pathlib.Path(folder).glob("*.json")):
        year = int(path.stem)
        brands = {}
        for row in json.loads(path.read_text()):
            brand, generic = _name(row.get("Brnd_Name")), _name(row.get("Gnrc_Name"))
            if not brand or brand == generic:
                continue
            cost, claims = _num(row.get("Tot_Drug_Cst")), _num(row.get("Tot_Clms"))
            if cost is None:
                continue
            prior = brands.get(brand)
            if prior:                                   # two rows, one brand: sum them
                cost += prior[0]
                claims = (claims or 0) + (prior[1] or 0)
            brands[brand] = (cost, claims, generic)
        out[year] = brands
    return out


def events(conn):
    """{brand name: {launch, form, route, anda_count, status_180}}, earliest launch."""
    out = {}
    for r in conn.execute(
            "SELECT rld_name, dosage_form, first_marketing, anda_count, status_180"
            "  FROM paragraph_iv_list WHERE first_marketing IS NOT NULL"):
        name = _name(r["rld_name"])
        if not name:
            continue
        if name not in out or r["first_marketing"] < out[name]["launch"]:
            out[name] = {"launch": r["first_marketing"], "form": r["dosage_form"],
                         "route": route(r["dosage_form"]), "anda_count": r["anda_count"],
                         "status_180": r["status_180"]}
    return out


def measure(partd, found):
    years = sorted(partd)
    rows = []
    for brand, ev in found.items():
        launch = int(ev["launch"][:4])
        base = partd.get(launch - 1, {}).get(brand)
        if not base or base[0] < MIN_BASE_COST or launch + 1 > years[-1]:
            continue
        before = partd.get(launch - 2, {}).get(brand)
        cost = {k: (partd.get(launch + k, {}).get(brand) or (0.0, 0.0, None))[0] / base[0]
                for k in range(0, HORIZON + 1) if launch + k <= years[-1]}
        claims = ({k: (partd.get(launch + k, {}).get(brand) or (0.0, 0.0, None))[1]
                   / base[1] for k in cost} if base[1] else {})
        rows.append({"brand": brand, "launch": ev["launch"], "route": ev["route"],
                     "anda_count": ev["anda_count"], "base_cost": base[0],
                     "pre_trend": (base[0] / before[0] - 1) if before and before[0] else None,
                     "cost": cost, "claims": claims})
    return rows


def _curve(sample, key):
    """Median retained share at each year, and the implied year-one drop and decay."""
    out = {}
    for k in range(0, HORIZON + 1):
        values = [r[key][k] for r in sample if k in r[key]]
        if len(values) >= 5:
            out[k] = (round(statistics.median(values), 3), len(values))
    return out


def summarise(rows):
    def block(sample, label):
        cost, claims = _curve(sample, "cost"), _curve(sample, "claims")
        y1 = [1 - r["cost"][1] for r in sample if 1 in r["cost"]]
        q = sorted(y1)
        spread = (f"{q[len(q) // 4]:.2f} to {q[3 * len(q) // 4]:.2f}" if len(q) >= 4
                  else "n/a")
        print(f"\n{label}: {len(sample)} events; year-one cost drop median "
              f"{statistics.median(y1):.2f} (interquartile {spread})" if y1 else
              f"\n{label}: {len(sample)} events")
        print("   year  cost retained (n)   claims retained (n)")
        for k in sorted(cost):
            c = claims.get(k, ("", ""))
            print(f"   L+{k}   {cost[k][0]:.3f} ({cost[k][1]})        {c[0]} ({c[1]})")
        return {"n": len(sample), "cost": cost, "claims": claims}

    report = {"all": block(rows, "all routes")}
    by_route = collections.defaultdict(list)
    for r in rows:
        by_route[r["route"]].append(r)
    for name, sample in sorted(by_route.items(), key=lambda kv: -len(kv[1])):
        report[name] = block(sample, name)
    for name, test in (("one filer", lambda n: n == 1), ("2 to 5 filers", lambda n: 2 <= n <= 5),
                       ("6 or more filers", lambda n: n >= 6)):
        sample = [r for r in rows if r["route"] == "oral" and r["anda_count"]
                  and test(r["anda_count"])]
        report[f"oral, {name}"] = block(sample, f"oral, {name} (Paragraph IV ANDAs)")
    steady = [r for r in rows if r["pre_trend"] is not None and r["pre_trend"] > -0.15]
    report["oral, brand not already falling"] = block(
        [r for r in steady if r["route"] == "oral"],
        "oral, brand cost fell under 15% in the year before launch")
    return report


def main(argv):
    if argv and argv[0] == "--download":
        download(argv[1])
        return
    conn = db.get_connection()
    partd = load_partd(argv[0])
    found = events(conn)
    rows = measure(partd, found)
    joined = sum(1 for b in found if any(b in partd[y] for y in partd))
    print(f"launch events {len(found)}; joined to a Part D brand {joined}; measurable "
          f"(launch {min(partd) + 1} to {max(partd) - 1}, base cost over "
          f"${MIN_BASE_COST / 1e6:.0f}m) {len(rows)}")
    report = summarise(rows)
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        pathlib.Path(path).write_text(json.dumps({"events": rows, "report": report},
                                                 indent=1, default=str))


if __name__ == "__main__":
    main(sys.argv[1:])
