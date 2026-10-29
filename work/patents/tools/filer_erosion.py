"""Erosion on the filers' own US lines, beside Part D for the same launches.

A filer's US product line is net of rebates and covers every channel, which is what
Part D gross cost is not. For each launch event (``erosion_study.events``: the
Paragraph IV list plus the Part D entry detector) whose brand the filer reports a US line
for, the US line kept in each year after the launch year, against L-1, and the Part D
brand cost kept in the same years. Their ratio, year by year, is the measured gap between
the two.

Inputs: ``filer_us_lines.csv`` from ``filer_us_lines.py`` and the Part D files and
Orange Book zip ``erosion_study.py`` reads.

    ER_TOOL_DB=<copy> python3 work/patents/tools/filer_erosion.py <filer_us_lines.csv> \\
        <partd dir> <orange book zip> [<ag.pdf>] [--json out]
"""

import collections
import csv
import json
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402
import erosion_study as es  # noqa: E402

HORIZON = 4


def filer_lines(path):
    """{(ticker, PRODUCT NAME): {fiscal year: US value}}."""
    out = collections.defaultdict(dict)
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            out[(row["ticker"], es._name(row["product"]))][int(row["fiscal_year"])] = \
                float(row["us_value"])
    return out


def match(brand, lines):
    """The filer line for a brand: exact name, else the one line whose name starts with
    the brand's first word, else None. Never two."""
    exact = [k for k in lines if k[1] == brand]
    if len(exact) == 1:
        return exact[0]
    first = brand.split()[0] if brand else ""
    near = [k for k in lines if k[1].split()[:1] == [first]]
    return near[0] if len(near) == 1 else None


def biosimilar_events(conn, partd_dir, partb_dir):
    """{BRAND: {launch, route, source, ag}} for reference biologics: the launch year is
    the first year a biosimilar of the molecule (a suffixed generic name in Part D, a Q5
    code in Part B) shows any use. The brand is the book's own asset for the molecule.

    Part D is used for the date only. Its gross cost does not see a biologic's fall:
    Medicare claims for Humira were about 660,000 in 2022 and 650,000 in 2024 while
    AbbVie's US Humira line collapsed through net price."""
    import re
    first = {}
    for path in sorted(pathlib.Path(partd_dir).glob("*.json")):
        year = int(path.stem)
        for row in json.loads(path.read_text()):
            m = re.match(r"^([A-Za-z ]+?)-[A-Za-z]{4}$", (row.get("Gnrc_Name") or "").strip())
            if m and (es._num(row.get("Tot_Clms")) or 0) > 0:
                name = m.group(1).strip().lower()
                first[name] = min(first.get(name, year), year)
    if partb_dir:
        import partb_biosimilar_study as pb
        for path in sorted(pathlib.Path(partb_dir).glob("*.json")):
            year = int(path.stem)
            for row in json.loads(path.read_text()):
                if row["HCPCS_Cd"].startswith("Q5") and pb._spend(row) > 0:
                    name = pb.molecule_of(row["HCPCS_Desc"])
                    if name:
                        first[name] = min(first.get(name, year), year)
    out = {}
    for r in conn.execute("SELECT brand_name, generic_name FROM assets"
                          " WHERE modality = 'biologic' AND brand_name IS NOT NULL"):
        molecule = (r["generic_name"] or "").strip().lower()
        if molecule in first:
            out[es._name(r["brand_name"])] = {"launch": str(first[molecule]),
                                             "route": "biologic", "source": "biosimilar",
                                             "ag": False}
    return out


def measure(found, lines, partd):
    rows = []
    for brand, ev in found.items():
        key = match(brand, lines)
        if not key:
            continue
        series = lines[key]
        launch = int(ev["launch"][:4])
        base = series.get(launch - 1)
        if not base or base <= 0 or launch + 1 not in series:
            continue
        us = {k: series[launch + k] / base for k in range(0, HORIZON + 1)
              if launch + k in series}
        pd_base = partd.get(launch - 1, {}).get(brand)
        pd = ({k: (partd.get(launch + k, {}).get(brand) or (0.0, 0.0, None))[0] / pd_base[0]
               for k in us if launch + k in partd} if pd_base and pd_base[0] else {})
        rows.append({"ticker": key[0], "product": key[1], "brand": brand,
                     "launch": ev["launch"], "route": ev["route"], "source": ev["source"],
                     "ag": ev.get("ag"), "us_base": base, "us": us, "partd": pd})
    return rows


def report(rows):
    print(f"{len(rows)} launches with a filer US line in the year before and the year after")
    for r in sorted(rows, key=lambda r: r["launch"]):
        us = " ".join(f"{r['us'][k]:.2f}" for k in sorted(r["us"]))
        pd = " ".join(f"{r['partd'][k]:.2f}" for k in sorted(r["partd"]))
        print(f"  {r['ticker']:5s} {r['product'][:22]:22s} {r['launch'][:10]:10s} "
              f"{r['route'][:10]:10s} AG {'y' if r['ag'] else 'n'}  US: {us:30s} Part D: {pd}")
    for label, test in (("oral", lambda r: r["route"] == "oral"),
                        ("non-oral small molecule",
                         lambda r: r["route"] not in ("oral", "biologic")),
                        ("biologic", lambda r: r["route"] == "biologic"),
                        ("oral, AG on FDA's list", lambda r: r["route"] == "oral" and r["ag"]),
                        ("oral, no AG listed", lambda r: r["route"] == "oral" and not r["ag"])):
        sample = [r for r in rows if test(r)]
        if not sample:
            continue
        print(f"\n{label}: {len(sample)} launches")
        for k in range(1, HORIZON + 1):
            us = [r["us"][k] for r in sample if k in r["us"]]
            ratio = [r["us"][k] / r["partd"][k] for r in sample
                     if k in r["us"] and r["partd"].get(k)]
            if len(us) >= 3:
                q = sorted(us)
                line = (f"  L+{k}: filer US kept median {statistics.median(us):.3f} "
                        f"(n={len(us)}, interquartile {q[len(q) // 4]:.2f} to "
                        f"{q[3 * len(q) // 4]:.2f})")
                if len(ratio) >= 3:
                    line += (f"; US over Part D on the same launches median "
                             f"{statistics.median(ratio):.2f} (n={len(ratio)})")
                print(line)


def main(argv):
    lines = filer_lines(argv[0])
    partd = es.load_partd(argv[1])
    mols = es.load_molecules(argv[1])
    ob = es.ob_routes(argv[2])
    ag = None
    if len(argv) > 3 and not argv[3].startswith("--"):
        import ag_list
        ag = {es._name(k): v for k, v in ag_list.load(argv[3]).items()}
    conn = db.get_connection()
    found = es.events(conn, partd, mols, ob, ag)
    if "--partb" in argv:
        found.update(biosimilar_events(conn, argv[1], argv[argv.index("--partb") + 1]))
    rows = measure(found, lines, partd)
    report(rows)
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
