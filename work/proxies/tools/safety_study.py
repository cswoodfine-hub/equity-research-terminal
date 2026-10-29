"""Step 8d: does a safety imbalance in a completed study predict the programme stopping?

**Studies.** Completed Phase 2 studies with posted results (``trial_result_safety``) that
compare a drug arm with a placebo or standard-of-care arm, matched to a book asset
(``completed_trials.asset_id``).

**Imbalance.** Serious adverse events, and deaths, as the share of patients at risk:
the drug arms pooled, less the comparator arm. Arms are told apart by their titles; a
study whose arms cannot be told apart is left out rather than guessed.

**Outcome.** Whether the asset went on, within three years of the Phase 2's completion:
a Phase 3 study (active in ``trials`` with a later start, or completed in
``completed_trials`` with a later completion) or an approval in ``approvals``. Studies
completed within the last three years are left out, since their outcome is not yet
known.

    ER_TOOL_DB=<copy> python3 work/proxies/tools/safety_study.py [--json out]
"""

import collections
import datetime as dt
import json
import pathlib
import re
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

import db  # noqa: E402

COMPARATOR = re.compile(r"placebo|vehicle|standard of care|\bsoc\b|best supportive|"
                        r"observation|control", re.I)
HORIZON_DAYS = 3 * 365


def _d(text):
    try:
        return dt.date.fromisoformat((text or "")[:10]) if len(text or "") >= 10 else \
            dt.date(int(text[:4]), int(text[5:7]), 15)
    except (ValueError, TypeError):
        return None


def main(argv):
    conn = db.get_connection()
    today = dt.date.today()
    arms = collections.defaultdict(list)
    for r in conn.execute("SELECT * FROM trial_result_safety"):
        arms[r["nct_id"]].append(dict(r))
    phase2 = {r["nct_id"]: dict(r) for r in conn.execute(
        "SELECT nct_id, asset_id, phase, completion_date FROM completed_trials"
        " WHERE asset_id IS NOT NULL AND phase LIKE '%2%' AND phase NOT LIKE '%3%'")}
    later = collections.defaultdict(list)          # asset -> dates of later Phase 3 / approval
    for r in conn.execute("SELECT asset_id, start_date AS d FROM trials"
                          " WHERE asset_id IS NOT NULL AND phase LIKE '%3%'"):
        later[r["asset_id"]].append(_d(r["d"]))
    for r in conn.execute("SELECT asset_id, completion_date AS d FROM completed_trials"
                          " WHERE asset_id IS NOT NULL AND phase LIKE '%3%'"):
        later[r["asset_id"]].append(_d(r["d"]))
    for r in conn.execute("SELECT asset_id, approval_date AS d FROM approvals"
                          " WHERE asset_id IS NOT NULL"):
        later[r["asset_id"]].append(_d(r["d"]))

    rows = []
    for nct, st in phase2.items():
        done = _d(st["completion_date"])
        if not done or (today - done).days < HORIZON_DAYS or nct not in arms:
            continue
        comp = [a for a in arms[nct] if COMPARATOR.search(a["group_title"] or "")]
        drug = [a for a in arms[nct] if not COMPARATOR.search(a["group_title"] or "")]
        if len(comp) != 1 or not drug:
            continue
        c = comp[0]

        def rate(group, key):
            hit = sum(a[f"{key}_affected"] or 0 for a in group)
            risk = sum(a[f"{key}_at_risk"] or 0 for a in group)
            return hit / risk if risk else None
        sae_d, sae_c = rate(drug, "serious"), rate([c], "serious")
        dth_d, dth_c = rate(drug, "deaths"), rate([c], "deaths")
        if sae_d is None or sae_c is None:
            continue
        went_on = any(d and done < d <= done + dt.timedelta(days=HORIZON_DAYS)
                      for d in later.get(st["asset_id"], []))
        rows.append({"nct": nct, "asset_id": st["asset_id"], "completed": str(done),
                     "sae_excess": sae_d - sae_c,
                     "death_excess": (dth_d - dth_c) if dth_d is not None and dth_c is not None else None,
                     "n_drug": sum(a["serious_at_risk"] or 0 for a in drug),
                     "went_on": went_on})
    print(f"{len(rows)} completed, comparator-controlled Phase 2 studies with an outcome")
    if not rows:
        return
    base = sum(r["went_on"] for r in rows) / len(rows)
    print(f"went on to Phase 3 or approval within 3 years: {base:.0%}")
    bands = ((-1, -0.05, "drug arm lower by over 5 points"), (-0.05, 0.0, "lower by up to 5"),
             (0.0, 0.05, "higher by up to 5"), (0.05, 0.10, "higher by 5 to 10"),
             (0.10, 1.0, "higher by over 10"))
    report = []
    print("serious adverse events, drug arm less comparator | n | went on")
    for lo, hi, name in bands:
        b = [r for r in rows if lo <= r["sae_excess"] < hi]
        if b:
            share = sum(r["went_on"] for r in b) / len(b)
            report.append({"band": name, "n": len(b), "went_on": share})
            print(f"  {name:32s} | {len(b):3d} | {share:.0%}")
    deaths = [r for r in rows if r["death_excess"] is not None]
    for name, test in (("deaths higher in the drug arm", lambda r: r["death_excess"] > 0),
                       ("deaths not higher", lambda r: r["death_excess"] <= 0)):
        b = [r for r in deaths if test(r)]
        if b:
            print(f"  {name:32s} | {len(b):3d} | {sum(r['went_on'] for r in b) / len(b):.0%}")
    if "--json" in argv:
        pathlib.Path(argv[argv.index("--json") + 1]).write_text(
            json.dumps({"rows": rows, "report": report}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
