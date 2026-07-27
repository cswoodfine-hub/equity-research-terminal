"""Pipeline heatmap builder.

Counts active lead-sponsored trials per company and phase from the trials table,
and lists the trials behind a cell for drill-down. These are trial counts, not
deduplicated assets; asset_indications population waits for a curated asset universe.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import db
import therapeutic_areas
from fetchers.trials_ctgov import PHASES

_PLACEHOLDERS = ",".join("?" * len(PHASES))

# Post-approval phase, kept out of the development pipeline the way the Pipeline tab does.
POST_APPROVAL = "Phase 4"

# Long-term follow-up, extension and rollover studies carry a development phase in the
# registry (Casgevy's follow-up is filed as Phase 3), so they sit inside the pipeline
# counts though they are lifecycle work on a product already in or past development, not
# new development. They are recognised by the standard titling the registry uses. This is
# a title heuristic, not a registry field: it errs toward the unmistakable phrasings.
_FOLLOW_UP_RE = re.compile(
    r"long[- ]term follow[- ]?up"
    r"|long[- ]term extension"
    r"|open[- ]label extension"
    r"|\bextension (study|trial|phase|of)\b"
    r"|\broll[- ]?over\b"
    r"|follow[- ]up (study|trial|of|gene|safety)"
    r"|safety follow[- ]up",
    re.I,
)


def is_follow_up(title: str | None) -> bool:
    """True when a trial title marks it as a long-term follow-up, extension or rollover
    study. Pure, so the same rule serves the per-trial flag and the pipeline counts."""
    return bool(title and _FOLLOW_UP_RE.search(title))


def build_pipeline(db_path=None) -> list[dict]:
    """Compounds in development per company and phase, for the cross-company grid.

    Counted in compounds, not studies, and each compound once at the furthest phase it
    has reached, so a row sums to the number of candidates a company has rather than the
    number of protocols it has registered. Trial counts measured how finely a programme
    was split: AstraZeneca ran 160 Phase 3 trials against Lilly's 92 while the gap in
    candidates is far smaller, and a company running one large registrational trial per
    asset read as half the size of one running six.

    A trial whose intervention names nothing on file has no compound to attribute, so it
    is counted nowhere here; ``unattributed`` per company says how many, which keeps a
    thin mapping visible instead of reading as a small pipeline.
    """
    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker, name FROM companies ORDER BY ticker"
        ).fetchall()
        # Both units, because they answer different questions and one view each reads
        # them: the grid compares pipelines and wants compounds, while the screen's
        # revenue-per-late-trial divides by protocols and wants trials. Returning only
        # one would have silently changed the meaning of the other's column.
        counts: dict[tuple, int] = {}
        furthest: dict[tuple, str] = {}
        unattributed: dict[int, int] = {}
        for row in conn.execute(
            f"""
            SELECT sponsor_company_id AS cid, asset_id, phase
              FROM trials
             WHERE phase IN ({_PLACEHOLDERS}) AND sponsor_company_id IS NOT NULL
            """,
            PHASES,
        ):
            counts[(row["cid"], row["phase"])] = counts.get(
                (row["cid"], row["phase"]), 0) + 1
            if row["asset_id"] is None:
                unattributed[row["cid"]] = unattributed.get(row["cid"], 0) + 1
                continue
            key = (row["cid"], row["asset_id"])
            if key not in furthest or PHASES.index(row["phase"]) > PHASES.index(
                    furthest[key]):
                furthest[key] = row["phase"]

        compound_counts: dict[tuple, int] = {}
        for (cid, _asset), phase in furthest.items():
            compound_counts[(cid, phase)] = compound_counts.get((cid, phase), 0) + 1

        # Follow-up studies carry a development phase, so they are counted from the title
        # here and reported per company; the strip subtracts them from in-development so
        # the two tabs agree. Phase 4 follow-ups stay in the post-approval count.
        follow: dict[int, int] = {}
        for row in conn.execute(
            f"""
            SELECT sponsor_company_id AS cid, title
              FROM trials
             WHERE phase IN ({_PLACEHOLDERS}) AND phase != ?
            """,
            (*PHASES, POST_APPROVAL),
        ):
            if is_follow_up(row["title"]):
                follow[row["cid"]] = follow.get(row["cid"], 0) + 1

        out = []
        for company in companies:
            phases = {p: counts.get((company["id"], p), 0) for p in PHASES}
            compounds = {p: compound_counts.get((company["id"], p), 0) for p in PHASES}
            out.append(
                {
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "phases": phases,
                    "compounds": compounds,
                    "follow_up": follow.get(company["id"], 0),
                    "unattributed": unattributed.get(company["id"], 0),
                    "total": sum(phases.values()),
                    "compound_total": sum(compounds.values()),
                }
            )
        return out
    finally:
        conn.close()


def programmes(db_path, ticker: str) -> list[dict] | None:
    """One row per compound the company is trialling but does not yet sell.

    The pipeline read as a list of studies until trials were bound to assets; this reads
    it as the programmes an analyst actually tracks, each with how many studies sit
    behind it, the furthest phase any of them has reached, and when the next one is due
    to read out. Sorted by phase reached, so the closest to market leads.
    """
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)).fetchone()
        if company is None:
            return None
        # Every study of every unapproved compound, in one pass. Grouping in Python
        # rather than a query per compound keeps this one round trip whatever the size
        # of the pipeline, which for a large sponsor is eighty programmes or more.
        rows = conn.execute(
            """
            SELECT a.id AS asset_id, a.generic_name AS name, a.modality,
                   t.nct_id, t.title, t.phase, t.overall_status,
                   t.primary_completion_date AS due, t.enrollment, t.conditions
              FROM assets a JOIN trials t ON t.asset_id = a.id
             WHERE a.owner_company_id = ? AND a.is_marketed = 0
             ORDER BY (t.primary_completion_date IS NULL), t.primary_completion_date
            """, (company["id"],)).fetchall()

        today = dt.date.today().isoformat()
        by_asset: dict = {}
        for row in rows:
            entry = by_asset.setdefault(row["asset_id"], {
                "asset_id": row["asset_id"], "name": row["name"],
                "modality": row["modality"], "trials": 0, "next_readout": None,
                "phases": set(), "areas": {}, "studies": []})
            entry["trials"] += 1
            entry["phases"].add(row["phase"])
            if row["due"] and row["due"] >= today and (
                    entry["next_readout"] is None or row["due"] < entry["next_readout"]):
                entry["next_readout"] = row["due"]
            # The registry spells one disease many ways, so a study is placed by
            # therapeutic area, the same axis the rest of the pipeline is browsed on.
            conditions = json.loads(row["conditions"]) if row["conditions"] else []
            area = therapeutic_areas.classify(conditions)
            entry["areas"][area] = entry["areas"].get(area, 0) + 1
            entry["studies"].append(
                {"nct_id": row["nct_id"], "title": row["title"], "phase": row["phase"],
                 "status": row["overall_status"], "due": row["due"],
                 "enrollment": row["enrollment"], "area": area})

        out = []
        for entry in by_asset.values():
            phases = [p for p in entry.pop("phases") if p]
            # The furthest phase reached, on the app-wide phase order.
            entry["phase"] = max((p for p in phases if p in PHASES),
                                 key=PHASES.index, default=None)
            entry["phases"] = sorted(phases, key=lambda p: PHASES.index(p)
                                     if p in PHASES else -1)
            # A compound can be studied across areas, so it carries all of them and is
            # led by the one most of its studies sit in. Filtering on any of them keeps
            # a compound visible in every area it is actually being developed for.
            counted = entry.pop("areas")
            entry["areas"] = sorted(counted, key=lambda a: (-counted[a], a))
            entry["area"] = entry["areas"][0] if entry["areas"] else None
            out.append(entry)
        out.sort(key=lambda i: (PHASES.index(i["phase"]) if i["phase"] in PHASES else -1,
                                i["trials"]), reverse=True)
        return out
    finally:
        conn.close()


def trials_for(db_path, ticker: str, phase: str | None = None) -> list[dict] | None:
    """Trials behind a heatmap cell. Returns None if the ticker is unknown."""
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if company is None:
            return None
        # asset_id and its name ride along so a view can count compounds rather than
        # studies: a pipeline is a set of programmes, and ten trials of one molecule is
        # one bet, not ten. Null where the intervention named nothing we hold.
        query = f"""
            SELECT t.nct_id, t.title, t.phase, t.overall_status,
                   t.primary_completion_date, t.primary_completion_type,
                   t.last_update_posted, t.enrollment, t.conditions,
                   t.asset_id,
                   COALESCE(a.brand_name, a.generic_name, a.internal_code) AS asset_name,
                   a.is_marketed AS asset_is_marketed
              FROM trials t LEFT JOIN assets a ON a.id = t.asset_id
             WHERE t.sponsor_company_id = ? AND t.phase IN ({_PLACEHOLDERS})
        """
        params = [company["id"], *PHASES]
        if phase:
            query += " AND t.phase = ?"
            params.append(phase)
        query += " ORDER BY t.phase, t.primary_completion_date"
        rows = []
        for row in conn.execute(query, params):
            item = dict(row)
            item["conditions"] = json.loads(item["conditions"]) if item["conditions"] else []
            # The registry spells one disease several ways, so the browsable axis is
            # the therapeutic area rather than the raw condition string.
            item["area"] = therapeutic_areas.classify(item["conditions"])
            # A long-term follow-up, extension or rollover study carries a development
            # phase but is lifecycle work; flagged so the tab can tag it apart.
            item["follow_up"] = is_follow_up(item.get("title"))
            rows.append(item)
        return rows
    finally:
        conn.close()
