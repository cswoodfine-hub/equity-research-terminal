"""Pipeline heatmap builder.

Counts active lead-sponsored trials per company and phase from the trials table,
and lists the trials behind a cell for drill-down. These are trial counts, not
deduplicated assets; asset_indications population waits for a curated asset universe.
"""

from __future__ import annotations

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
    conn = db.get_connection(db_path)
    try:
        companies = conn.execute(
            "SELECT id, ticker, name FROM companies ORDER BY ticker"
        ).fetchall()
        counts: dict[tuple, int] = {}
        for row in conn.execute(
            f"""
            SELECT sponsor_company_id AS cid, phase, COUNT(*) AS n
              FROM trials
             WHERE phase IN ({_PLACEHOLDERS})
             GROUP BY sponsor_company_id, phase
            """,
            PHASES,
        ):
            counts[(row["cid"], row["phase"])] = row["n"]

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
            out.append(
                {
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "phases": phases,
                    "follow_up": follow.get(company["id"], 0),
                    "total": sum(phases.values()),
                }
            )
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
        query = f"""
            SELECT nct_id, title, phase, overall_status, primary_completion_date,
                   primary_completion_type,
                   last_update_posted, enrollment, conditions
              FROM trials
             WHERE sponsor_company_id = ? AND phase IN ({_PLACEHOLDERS})
        """
        params = [company["id"], *PHASES]
        if phase:
            query += " AND phase = ?"
            params.append(phase)
        query += " ORDER BY phase, primary_completion_date"
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
