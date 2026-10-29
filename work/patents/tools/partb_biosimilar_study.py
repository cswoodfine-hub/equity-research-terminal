"""Biologic erosion after a biosimilar launch, from Medicare Part B, 2013 to 2024.

Source: CMS "Medicare Physician & Other Practitioners - by Geography and Service", one
dataset a year, National rows with the drug flag set (files written by ``--download``).
Part B pays for a physician-given drug from its average sales price, which is net of
the discounts and rebates manufacturers give purchasers, so the allowed amount is
closer to net revenue than Part D's gross cost.

A biosimilar bills on its own Q5 code ("Injection, filgrastim-sndz, biosimilar,
(zarxio)"), so the reference product's codes carry the reference product alone. For
each molecule: the reference spending (services times average allowed amount, every
place of service) and the biosimilars' spending, by year. The launch year L is the
first year a biosimilar takes over 0.5% of the molecule's spending, and the reference
product is measured against L-1, the engine's footing. The first infliximab biosimilar
code carried no suffix ("Injection, infliximab, biosimilar, 10 mg"), so a Q5 code names
its molecule either way.

Covers the physician office and other practitioner claims only: a drug given in a
hospital outpatient department is billed by the hospital and is not in this file.

    python3 work/patents/tools/partb_biosimilar_study.py --download <dir>
    python3 work/patents/tools/partb_biosimilar_study.py <dir> [--json out]
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

SERIES = "Medicare Physician & Other Practitioners - by Geography and Service"
MIN_BASE = 10e6
# The launch year is the first year a biosimilar shows at all. A launch late in the year
# can take 2% to 5% of it (Herceptin's in 2019), and a rule that wanted 5% in a year after
# one under 2% never found it.
ENTRY_SHARE = 0.005
HORIZON = 6

# "Injection, filgrastim-sndz, biosimilar", and the early spellings: no suffix
# ("Injection, infliximab, biosimilar"), a note before it ("filgrastim (g-csf),
# biosimilar"), and no comma after "Injection" (2014 to 2016).
_BIOSIMILAR = re.compile(
    r"^injection,?\s*([a-z][a-z ]*?)(?:-[a-z]{4}\b|\s*\([^)]*\))?,\s*(?:biosimilar|\()",
    re.I)


def download(folder):
    import cms_catalogue
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for year in cms_catalogue.years(cms_catalogue.load(), SERIES):
        rows, offset = [], 0
        while True:
            query = urllib.parse.urlencode({"filter[Rndrng_Prvdr_Geo_Lvl]": "National",
                                            "filter[HCPCS_Drug_Ind]": "Y",
                                            "size": 5000, "offset": offset})
            url = f"https://data.cms.gov/data-api/v1/dataset/{year['uuid']}/data?{query}"
            req = urllib.request.Request(url, headers={"User-Agent": "Novatalis Research"})
            page = json.loads(urllib.request.urlopen(req, timeout=120).read())
            rows += page
            offset += 5000
            if len(page) < 5000:
                break
        (folder / f"{year['year']}.json").write_text(json.dumps(rows))
        print(year["year"], len(rows))


def _spend(row):
    try:
        return float(row["Tot_Srvcs"]) * float(row["Avg_Mdcr_Alowd_Amt"])
    except (TypeError, ValueError, KeyError):
        return 0.0


def molecule_of(desc):
    """The molecule a biosimilar Q code names ("filgrastim-sndz" -> "filgrastim")."""
    m = _BIOSIMILAR.match((desc or "").strip())
    return m.group(1).strip().lower() if m else None


def load(folder):
    """{year: {molecule: {"reference": $, "biosimilar": $, "codes": {...}}}}."""
    years = {}
    files = sorted(pathlib.Path(folder).glob("*.json"))
    raw = {int(p.stem): json.loads(p.read_text()) for p in files}
    molecules = set()
    for rows in raw.values():
        for row in rows:
            if row["HCPCS_Cd"].startswith("Q5"):
                name = molecule_of(row["HCPCS_Desc"])
                if name:
                    molecules.add(name)
    for year, rows in raw.items():
        out = collections.defaultdict(lambda: {"reference": 0.0, "biosimilar": 0.0,
                                               "codes": set()})
        for row in rows:
            desc = (row["HCPCS_Desc"] or "").strip().lower()
            if row["HCPCS_Cd"].startswith("Q5"):
                name = molecule_of(desc)
                if name:
                    out[name]["biosimilar"] += _spend(row)
                continue
            if "biosimilar" in desc and "excludes biosimilar" not in desc:
                continue                   # a biosimilar billed on a code of another series
            for name in molecules:
                # The reference product's code: "injection, filgrastim (g-csf)", not
                # "injection, pegfilgrastim" and not another biosimilar.
                if re.match(rf"^injection,?\s*{re.escape(name)}(\b(?!-)|\s|,|\()", desc):
                    out[name]["reference"] += _spend(row)
                    out[name]["codes"].add(row["HCPCS_Cd"])
        years[year] = dict(out)
    return years


def measure(years):
    found = []
    ordered = sorted(years)
    for name in sorted({m for y in years.values() for m in y}):
        for year in ordered:
            prev, cur = years.get(year - 1, {}).get(name), years[year].get(name)
            if not prev or not cur:
                continue
            t0 = prev["reference"] + prev["biosimilar"]
            t1 = cur["reference"] + cur["biosimilar"]
            if not t0 or not t1 or prev["reference"] < MIN_BASE:
                continue
            if prev["biosimilar"] / t0 < ENTRY_SHARE and cur["biosimilar"] / t1 >= ENTRY_SHARE:
                base = prev["reference"]
                retained = {k: years[year + k][name]["reference"] / base
                            for k in range(0, HORIZON + 1)
                            if year + k in years and name in years[year + k]}
                share = {k: years[year + k][name]["biosimilar"]
                         / (years[year + k][name]["reference"]
                            + years[year + k][name]["biosimilar"])
                         for k in retained}
                found.append({"molecule": name, "launch_year": year, "base": base,
                              "codes": sorted(cur["codes"]), "retained": retained,
                              "biosimilar_share": share})
                break
    return found


def main(argv):
    if argv and argv[0] == "--download":
        download(argv[1])
        return
    events = measure(load(argv[0]))
    print(f"{len(events)} biosimilar launches measurable in Part B (base over "
          f"${MIN_BASE / 1e6:.0f}m in the year before)")
    for e in events:
        path = " ".join(f"{e['retained'][k]:.2f}" for k in sorted(e["retained"]))
        print(f"  {e['molecule']:22s} L={e['launch_year']}  base ${e['base'] / 1e6:,.0f}m"
              f"  reference retained L+0..: {path}")
    for k in range(0, HORIZON + 1):
        v = [e["retained"][k] for e in events if k in e["retained"]]
        if len(v) >= 3:
            q = sorted(v)
            print(f"L+{k}: median retained {statistics.median(v):.3f} (n={len(v)}, "
                  f"interquartile {q[len(q) // 4]:.2f} to {q[3 * len(q) // 4]:.2f})")
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps(events, indent=1, default=list))


if __name__ == "__main__":
    main(sys.argv[1:])
