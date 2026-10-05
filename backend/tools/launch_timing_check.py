"""Every launch-floor flag in the book, laid out for checking by hand.

backend/launch_timing.py flags a seeded forecast_start_year the evidence on file cannot
reach. A flag is only as good as the evidence, and the evidence has two known holes: a
pivotal registered under a sponsor the trial fetch never asks for (abelacimab's
LILAC-TIMI 76 sits under Anthos), and a filing or readout the seed's own source cites but
the database does not hold. So every red row gets read against its own source before
anyone acts on it, and this prints what that reading needs: the seed and its source in
full, the study and the clock that set the floor, the standard-clock year, the last slip,
the gate study, and the floor in the modelled disease.

With --registry it also asks ClinicalTrials.gov (API v2, query.intr on each of the
asset's names as a phrase, Phase 3 only) for studies the trials table does not hold under the asset,
and says where one would move the floor. That is a read of a public registry and nothing
is written: a missing study is reported, never patched in.

Read-only. It opens the database, reads and prints. It is not imported by the app.

    python tools/launch_timing_check.py                 # red and amber flags, every company
    python tools/launch_timing_check.py LLY AMGN        # those companies only
    python tools/launch_timing_check.py --registry      # plus the registry cross-check
    python tools/launch_timing_check.py --all --json    # every status, as JSON
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import env  # noqa: F401,E402  loads .env before any module reads it
import db  # noqa: E402
import launch_timing  # noqa: E402

CTGOV = "https://clinicaltrials.gov/api/v2/studies"
FIELDS = ("NCTId,BriefTitle,OverallStatus,PrimaryCompletionDate,Phase,LeadSponsorName,"
          "Condition")
# The registry's own spelling of the statuses launch_timing leaves out.
NOT_LIVE = {"WITHDRAWN", "TERMINATED", "SUSPENDED"}
FLAGGED = ("before_floor", "before_floor_cited")


def _registry_hits(names: list[str]) -> dict:
    """{nct_id: study} for every Phase 3 the registry lists under any of the names."""
    hits = {}
    for name in names:
        if not name or len(name) < 4:
            continue
        # Quoted, so a descriptive name ("mRNA Seasonal Flu vaccine") is searched as a
        # phrase rather than as any study mentioning mRNA.
        query = urllib.parse.urlencode({
            "query.intr": f'"{name}"', "filter.advanced": "AREA[Phase](PHASE3)",
            "fields": FIELDS, "pageSize": 100})
        request = urllib.request.Request(f"{CTGOV}?{query}",
                                         headers={"User-Agent": "er-tool launch check"})
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.load(response)
        for study in body.get("studies") or []:
            section = study.get("protocolSection") or {}
            nct = (section.get("identificationModule") or {}).get("nctId")
            status = section.get("statusModule") or {}
            hits[nct] = {
                "nct_id": nct,
                "title": (section.get("identificationModule") or {}).get("briefTitle"),
                "status": status.get("overallStatus"),
                "primary_completion": (status.get("primaryCompletionDateStruct")
                                       or {}).get("date"),
                "phases": (section.get("designModule") or {}).get("phases"),
                "sponsor": ((section.get("sponsorCollaboratorsModule") or {})
                            .get("leadSponsor") or {}).get("name"),
                "conditions": (section.get("conditionsModule") or {}).get("conditions"),
                "matched_on": name}
        time.sleep(0.3)
    return hits


def _registry_gaps(conn, row: dict) -> list[dict]:
    """Registry Phase 3s missing from the asset's studies, and the floor each would give."""
    asset = conn.execute("SELECT generic_name, brand_name, internal_code FROM assets"
                         " WHERE id = ?", (row["asset_id"],)).fetchone()
    names = list(dict.fromkeys(n for n in (asset["generic_name"], asset["brand_name"],
                                           asset["internal_code"]) if n))
    hits = _registry_hits(names)
    held = {}
    if hits:
        marks = ",".join("?" * len(hits))
        held = {r["nct_id"]: r["asset_id"] for r in conn.execute(
            f"SELECT nct_id, asset_id FROM trials WHERE nct_id IN ({marks})", list(hits))}
    clock = row.get("clock") or {}
    out = []
    for nct, study in sorted(hits.items()):
        if held.get(nct) == row["asset_id"]:
            continue
        day = launch_timing.parse_date(study["primary_completion"])
        floor = (launch_timing.review_ends(day, clock).year
                 if (day and clock.get("months") and study["status"] not in NOT_LIVE)
                 else None)
        out.append({**study, "in_trials_table": nct in held,
                    "mapped_to_asset": held.get(nct),
                    "floor_year": floor,
                    "lowers_floor": bool(floor and row.get("first_possible_year")
                                         and floor < row["first_possible_year"])})
    return out


def _print(row: dict, gaps: list | None) -> None:
    evidence = row.get("evidence") or {}
    clock = row.get("clock") or {}
    print(f"\n{row['ticker']} {row['name']} (asset {row['asset_id']}): {row['status']}")
    print(f"  seed {row['seed_year']} ({row['seed_scenario']}): {row['seed_source']}")
    if row["seed_basis"]["cites"]:
        print(f"  seed cites a {row['seed_basis']['cites']}: '{row['seed_basis']['match']}'")
    print(f"  {row['message']}")
    print(f"  evidence: {evidence.get('kind')} {evidence.get('nct_id') or evidence.get('catalyst_id') or ''}"
          f" {evidence.get('date')} ({evidence.get('date_type') or ''})"
          f"{' STALE' if evidence.get('stale') else ''}")
    print(f"  clock: {clock.get('pathway')} {clock.get('review')} {clock.get('months')}"
          f" months after {clock.get('filing_period_days') or 0} filing days"
          f" ({clock.get('pathway_how')})")
    print(f"  decision {row['decision_date']}, first full year {row['first_full_year']};"
          f" standard clock {(row.get('standard') or {}).get('decision_date')},"
          f" first full year {(row.get('standard') or {}).get('first_full_year')}")
    if row.get("slip"):
        s = row["slip"]
        print(f"  last slip {s['detected_at']}: {s['old']} to {s['new']},"
              f" floor {s['floor_before']} to {s['floor_after']}")
    if row.get("gate"):
        g = row["gate"]
        print(f"  gate: {g['label']} {g.get('nct_id') or ''} {g.get('date') or ''}"
              f" earliest approval {g.get('decision_date') or g.get('why')}")
    if row.get("modelled_floor"):
        print(f"  modelled disease: {row['modelled_floor']}")
    for gap in gaps or []:
        print(f"  registry: {gap['nct_id']} {gap['status']} pcd {gap['primary_completion']}"
              f" sponsor {gap['sponsor']} in_table={gap['in_trials_table']}"
              f" mapped_to={gap['mapped_to_asset']} floor {gap['floor_year']}"
              f"{' LOWERS THE FLOOR' if gap['lowers_floor'] else ''}: {gap['title']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--all", action="store_true", help="every status, not only flags")
    parser.add_argument("--registry", action="store_true",
                        help="ask ClinicalTrials.gov for Phase 3s missing from the book")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    conn = db.get_connection()
    try:
        companies = conn.execute("SELECT id, ticker FROM companies ORDER BY ticker").fetchall()
        wanted = {t.upper() for t in args.tickers}
        rows = []
        for company in companies:
            if wanted and company["ticker"] not in wanted:
                continue
            for found in launch_timing.for_company(conn, company["id"]):
                rows.append({"ticker": company["ticker"], **found})
        counts = collections.Counter(r["status"] for r in rows)
        shown = rows if args.all else [r for r in rows if r["status"] in FLAGGED]
        for row in shown:
            row["registry"] = (_registry_gaps(conn, row)
                               if args.registry and row["status"] in FLAGGED else None)
    finally:
        conn.close()
    if args.json:
        json.dump({"as_of": dt.date.today().isoformat(), "counts": counts,
                   "assets": shown}, sys.stdout, indent=1, default=str)
        print()
        return 0
    print(f"{len(rows)} unmarketed assets with a seeded start year: "
          + ", ".join(f"{status} {counts[status]}" for status in launch_timing.STATUSES
                      if counts[status]))
    for row in shown:
        _print(row, row.get("registry"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
