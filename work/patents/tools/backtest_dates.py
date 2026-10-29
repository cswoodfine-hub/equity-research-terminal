"""Backtest LOE date rules against generic launches that happened.

Ground truth: the first commercial marketing date of the first Paragraph IV filer, per
reference drug, from ``paragraph_iv_list`` (the FDA list). The molecule patent's date:
the USPTO certificate's original expiry plus the extension granted, from
``patent_term_extensions``, matched on the trade name's first word(s). The later end:
the list's own "expiration date of last qualifying patent".

Both inputs are historical (the extension list goes back to the 1980s; the Paragraph IV
list keeps launched drugs), so the test needs no archived Orange Book. What it cannot
test is the current rule, the latest drug substance patent, because expired patents
leave the Orange Book; that is said, not worked around.

Biases, stated: the list holds only drugs a generic challenged, and the first filer's
launch can trail a generic that entered without a challenge, so the ground truth leans
late. The trade name join misses renamed and combination products.

    ER_TOOL_DB=<copy> python3 work/patents/tools/backtest_dates.py [--seed 7]
"""

import collections
import datetime as dt
import pathlib
import random
import re
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

D = dt.date.fromisoformat


def _key(name):
    name = (name or "").upper().split("(")[0]
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", name).split())


def _years(a, b):
    return (a - b).days / 365.25


def observations(conn):
    launched = {}
    for r in conn.execute(
            "SELECT rld_name, application_number, first_marketing, last_patent_expiry"
            "  FROM paragraph_iv_list WHERE first_marketing IS NOT NULL"):
        k = r["application_number"] or _key(r["rld_name"])
        if k not in launched or r["first_marketing"] < launched[k]["first_marketing"]:
            launched[k] = dict(r)
    extended = collections.defaultdict(list)
    for r in conn.execute(
            "SELECT trade_name, extended_expiry FROM patent_term_extensions"
            " WHERE kind = 'certificate' AND extended_expiry IS NOT NULL"):
        extended[_key(r["trade_name"])].append(r["extended_expiry"])
    out = []
    for row in launched.values():
        name = _key(row["rld_name"])
        if name in extended and row["last_patent_expiry"]:
            molecule = D(max(extended[name]))
            last = max(D(row["last_patent_expiry"]), molecule)
            out.append((molecule, last, D(row["first_marketing"]), row["rld_name"]))
    return out, len(launched)


def predict(molecule, last, fraction, ped_years=0.5):
    start = molecule + dt.timedelta(days=int(ped_years * 365.25))
    return start + dt.timedelta(days=int(fraction * max(0, (last - start).days)))


def score(sample, fraction, ped_years=0.5):
    errors = [_years(launch, predict(m, q, fraction, ped_years)) for m, q, launch, _ in sample]
    absolute = [abs(e) for e in errors]
    return {"n": len(sample), "bias_years": round(statistics.median(errors), 2),
            "median_abs_error_years": round(statistics.median(absolute), 2),
            "within_6_months": round(sum(a <= 0.5 for a in absolute) / len(absolute), 2),
            "within_1_year": round(sum(a <= 1 for a in absolute) / len(absolute), 2)}


def main(seed=7):
    conn = db.get_connection()
    obs, launched = observations(conn)
    print(f"reference drugs with a recorded launch: {launched}; joined to an extension: "
          f"{len(obs)}")
    rules = {"molecule patent, no PED": (0.0, 0.0),
             "molecule patent + 6 months PED": (0.0, 0.5),
             "last qualifying patent": (1.0, 0.0)}
    for name, (fraction, ped) in rules.items():
        print(f"  {name}: {score(obs, fraction, ped)}")

    gaps = sorted((launch - m).days / (q - m).days for m, q, launch, _ in obs
                  if q > m + dt.timedelta(days=365))
    print(f"launch position between molecule patent (0) and last patent (1), on {len(gaps)}"
          f" drugs with a gap over a year: median {statistics.median(gaps):.2f}")
    for lo, hi in ((-99, 0), (0, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1),
                   (1, 99)):
        print(f"    [{lo}, {hi}): {sum(lo <= g < hi for g in gaps)}")

    rng = random.Random(seed)
    grid = [i / 100 for i in range(101)]
    fitted, held = [], []
    for _ in range(200):
        rng.shuffle(obs)
        train, test = obs[:len(obs) // 2], obs[len(obs) // 2:]
        best = min(grid, key=lambda f: statistics.median(
            [abs(_years(launch, predict(m, q, f))) for m, q, launch, _ in train]))
        fitted.append(best)
        held.append(score(test, best))
    fitted.sort()
    print(f"fitted fraction of the gap, 200 half splits: median {statistics.median(fitted)},"
          f" interquartile {fitted[50]} to {fitted[150]}")
    for k in ("bias_years", "median_abs_error_years", "within_6_months", "within_1_year"):
        print(f"    held out {k}: {statistics.median(h[k] for h in held):.2f}")
    conn.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    main(int(args[args.index("--seed") + 1]) if "--seed" in args else 7)
