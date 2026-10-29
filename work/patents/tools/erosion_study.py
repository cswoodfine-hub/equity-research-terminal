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
    """The route from a dose form: the Orange Book's "FORM;ROUTE" (the route part is
    read), or the Paragraph IV list's "Oral Suspension", "Injection", "Tablets".

    Words, not substrings: "pen" inside "suspension" once read every oral suspension as
    an injectable (Exjade, Megace ES, CellCept, Zyvox)."""
    text = (form or "").lower()
    part = text.partition(";")[2] if ";" in text else text
    words = set(re.findall(r"[a-z]+", part))
    if words & {"ophthalmic", "otic", "intravitreal"}:
        return "eye or ear"
    if words & {"inhalation", "inhaled", "inhaler", "aerosol", "nebulizer", "nebulization"} \
            or "inhal" in part:
        return "inhaled"
    if "nasal" in words:
        return "nasal"
    if words & {"topical", "transdermal", "cream", "gel", "ointment", "lotion", "patch",
                "foam", "shampoo", "cutaneous", "dermal"}:
        return "topical or transdermal"
    if words & {"oral", "tablet", "tablets", "capsule", "capsules", "chewable",
                "sublingual", "buccal", "granules", "pellets", "syrup", "elixir"}:
        return "oral"
    if words & {"injection", "injectable", "intravenous", "subcutaneous", "intramuscular",
                "infusion", "vial", "vials", "syringe", "pen", "injector", "intrathecal",
                "implant"}:
        return "injectable"
    if words & {"suspension", "solution", "powder", "sprinkle"}:
        return "oral"                  # a list row with no route word is taken by mouth
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


def load_molecules(folder):
    """{year: {generic name: (unbranded generic claims, all claims)}}.

    A Part D row whose brand name is its generic name is an unbranded generic (or an
    authorised generic sold under the molecule's name); every row under the generic name
    is the molecule."""
    out = {}
    for path in sorted(pathlib.Path(folder).glob("*.json")):
        mols = {}
        for row in json.loads(path.read_text()):
            brand, generic = _name(row.get("Brnd_Name")), _name(row.get("Gnrc_Name"))
            claims = _num(row.get("Tot_Clms")) or 0.0
            if not generic:
                continue
            g, t = mols.get(generic, (0.0, 0.0))
            mols[generic] = (g + (claims if brand == generic else 0.0), t + claims)
        out[int(path.stem)] = mols
    return out


ENTRY_SHARE, PRIOR_SHARE = 0.05, 0.02
OWNS_MOLECULE = 0.5


def _is_generic_name(brand, generic):
    """A Part D "brand" that is the molecule's own name ("SILDENAFIL" under
    "SILDENAFIL CITRATE", "AMPHETAMINE SALT COMBO")."""
    first = (brand or "").split()[:1]
    return bool(first) and first[0] in (generic or "").split()


def detect_entries(partd, mols):
    """{brand: entry year}: the first year unbranded generics pass ENTRY_SHARE of the
    molecule's Part D claims, having been under PRIOR_SHARE the year before. Reads
    launches the Paragraph IV list never recorded because no patent was challenged."""
    out = {}
    for year in sorted(partd):
        if year - 1 not in partd:
            continue
        for brand, (cost, _, generic) in partd[year - 1].items():
            if brand in out or cost < MIN_BASE_COST or not generic:
                continue
            if _is_generic_name(brand, generic):
                continue
            g0, t0 = mols.get(year - 1, {}).get(generic, (0.0, 0.0))
            g1, t1 = mols.get(year, {}).get(generic, (0.0, 0.0))
            # The brand must own its molecule: Abilify Maintena shares "aripiprazole"
            # with oral Abilify, whose generics are not its competition.
            brand_claims = partd[year - 1][brand][1] or 0.0
            if not t0 or brand_claims / t0 < OWNS_MOLECULE:
                continue
            if t1 and g0 / t0 < PRIOR_SHARE and g1 / t1 >= ENTRY_SHARE:
                out[brand] = year
    return out


def ob_routes(zip_path):
    """{trade name: route} from the Orange Book's products file, the route most of a
    trade name's rows carry."""
    import zipfile
    counts = collections.defaultdict(collections.Counter)
    with zipfile.ZipFile(zip_path) as archive:
        lines = archive.read("products.txt").decode("latin-1").splitlines()
    head = lines[0].split("~")
    i_name, i_form = head.index("Trade_Name"), head.index("DF;Route")
    for line in lines[1:]:
        parts = line.split("~")
        if len(parts) > max(i_name, i_form):
            counts[_name(parts[i_name])][route(parts[i_form])] += 1
    return {name: c.most_common(1)[0][0] for name, c in counts.items() if name}


def events(conn, partd=None, mols=None, ob=None, ag=None):
    """{brand name: {launch, form, route, anda_count, status_180, source, ag}}.

    Paragraph IV launches first, with their dates; then, where Part D data is given,
    entries its own rows show for brands the list does not carry, dated to the year."""
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
                         "status_180": r["status_180"], "source": "paragraph_iv"}
    if partd is not None and mols is not None:
        for brand, year in detect_entries(partd, mols).items():
            if brand not in out and (ob or {}).get(brand):
                # A brand the Orange Book does not carry has no route on file and is
                # left out rather than guessed (insulin, devices, biologics in Part D).
                out[brand] = {"launch": f"{year}", "form": None,
                              "route": ob[brand],
                              "anda_count": None, "status_180": None, "source": "part_d"}
    for brand, ev in out.items():
        ev["ag"] = brand in (ag or {})
    return out


def validate_detector(conn, partd, mols):
    """How often the Part D detector names the Paragraph IV launch year."""
    detected = detect_entries(partd, mols)
    listed = events(conn)
    offsets = collections.Counter()
    for brand, ev in listed.items():
        if brand in detected and int(ev["launch"][:4]) - 1 in partd:
            offsets[detected[brand] - int(ev["launch"][:4])] += 1
    return offsets


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
                     "source": ev.get("source"), "ag": ev.get("ag"),
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
    for source in ("paragraph_iv", "part_d"):
        sample = [r for r in rows if r.get("source") == source and r["route"] == "oral"]
        if sample:
            report[f"oral, {source}"] = block(sample, f"oral, events from {source}")
    for flag in (True, False):
        sample = [r for r in rows if r["route"] == "oral" and r.get("ag") is flag]
        if sample:
            report[f"oral, AG listed {flag}"] = block(
                sample, f"oral, authorised generic on FDA's list: {flag}")
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
    wide = "--wide" in argv
    mols = load_molecules(argv[0]) if wide else None
    ob = ob_routes(argv[argv.index("--ob") + 1]) if "--ob" in argv else None
    ag = None
    if "--ag" in argv:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import ag_list
        ag = {_name(k): v for k, v in ag_list.load(argv[argv.index("--ag") + 1]).items()}
    if wide:
        offsets = validate_detector(conn, partd, mols)
        n = sum(offsets.values())
        print(f"detector against {n} Paragraph IV launches: detected year minus launch "
              f"year {dict(sorted(offsets.items()))}; same year "
              f"{offsets.get(0, 0) / n:.0%}, within one {sum(v for k, v in offsets.items() if abs(k) <= 1) / n:.0%}")
    found = events(conn, partd if wide else None, mols, ob, ag)
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
