"""Compare two gate.py runs: totals, by company, and every asset moving over 10%.

    python3 work/patents/tools/gate_report.py main.json branch.json [--md out.md]

For each mover it names what changed in the valuation's inputs: the LOE year and its
basis, whether the loss sits in the base, and the erosion row.
"""

import json
import sys
from collections import defaultdict


def erosion_row(text):
    if not text:
        return None
    return text.split(")")[0].replace("curated default (", "") if "curated default" in text else text[:30]


def main(a_path, b_path):
    a, b = json.load(open(a_path)), json.load(open(b_path))
    keys = sorted(set(a) | set(b), key=int)
    tot = {"main": 0.0, "branch": 0.0}
    by_co = defaultdict(lambda: [0.0, 0.0])
    movers, errors = [], []
    for k in keys:
        x, y = a.get(k, {}), b.get(k, {})
        if "error" in x or "error" in y or x.get("rnpv") is None or y.get("rnpv") is None:
            if x.get("error") != y.get("error"):
                errors.append((k, x.get("name") or y.get("name"), x.get("error"), y.get("error")))
            continue
        tot["main"] += x["rnpv"]; tot["branch"] += y["rnpv"]
        by_co[x["ticker"]][0] += x["rnpv"]; by_co[x["ticker"]][1] += y["rnpv"]
        d = y["rnpv"] - x["rnpv"]
        if abs(d) >= 1 and (abs(x["rnpv"]) < 1 or abs(d) / abs(x["rnpv"]) > 0.10):
            why = []
            if x.get("loe_year") != y.get("loe_year"):
                why.append(f"LOE {x.get('loe_year')} to {y.get('loe_year')}")
            if bool(x.get("in_base")) != bool(y.get("in_base")):
                why.append("loss now in base" if y.get("in_base") else "loss no longer in base")
            if (x.get("loe_basis") or "")[:40] != (y.get("loe_basis") or "")[:40]:
                why.append(f"basis: {(y.get('loe_basis') or '')[:60]}")
            if erosion_row(x.get("erosion")) != erosion_row(y.get("erosion")):
                why.append(f"erosion {erosion_row(x.get('erosion'))} to {erosion_row(y.get('erosion'))}")
            elif x.get("erosion_shape") != y.get("erosion_shape") and y.get("erosion_shape"):
                a1, a2 = x.get("erosion_shape") or [None, None]
                b1, b2 = y["erosion_shape"]
                why.append(f"{erosion_row(y.get('erosion'))} row refit "
                           f"({a1}/{a2} to {b1}/{b2})")
            if x.get("regions") != y.get("regions"):
                changed = [f"{r[0]} {r[1]}" for r in y.get("regions") or []
                           if r not in (x.get("regions") or [])]
                if changed:
                    why.append("region " + ", ".join(changed))
            movers.append((d, k, x, y, "; ".join(why) or "no input named here changed"))
    movers.sort(key=lambda m: m[0])
    return tot, by_co, movers, errors


def render(tot, by_co, movers, errors):
    lines = [f"Risk-adjusted value, all {len(by_co)} companies: main {tot['main']:,.0f}mm, "
             f"branch {tot['branch']:,.0f}mm, change {tot['branch'] - tot['main']:+,.0f}mm "
             f"({(tot['branch'] / tot['main'] - 1) * 100:+.2f}%)", "",
             "| company | main | branch | change |", "|---|---|---|---|"]
    for t, (m, br) in sorted(by_co.items(), key=lambda kv: kv[1][1] - kv[1][0]):
        if abs(br - m) >= 1:
            lines.append(f"| {t} | {m:,.0f} | {br:,.0f} | {br - m:+,.0f} ({(br / m - 1) * 100 if m else 0:+.1f}%) |")
    lines += ["", f"{len(movers)} assets move more than 10%:", "",
              "| asset | main | branch | change | what changed |", "|---|---|---|---|---|"]
    for d, k, x, y, why in movers:
        pct = f"{d / x['rnpv'] * 100:+.0f}%" if abs(x["rnpv"]) >= 1 else "new"
        lines.append(f"| {x['ticker']} {x['name']} | {x['rnpv']:,.0f} | {y['rnpv']:,.0f} | "
                     f"{d:+,.0f} ({pct}) | {why} |")
    if errors:
        lines += ["", "Assets whose build fails on one side:", ""]
        lines += [f"- {n} ({k}): main {e1}, branch {e2}" for k, n, e1, e2 in errors]
    return "\n".join(lines)


if __name__ == "__main__":
    text = render(*main(sys.argv[1], sys.argv[2]))
    if "--md" in sys.argv:
        open(sys.argv[sys.argv.index("--md") + 1], "w").write(text + "\n")
    print(text)
