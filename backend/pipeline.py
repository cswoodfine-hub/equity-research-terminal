"""Pipeline heatmap builder.

Counts active lead-sponsored trials per company and phase from the trials table,
and lists the trials behind a cell for drill-down. These are trial counts, not
deduplicated assets; asset_indications population waits for a curated asset universe.
"""

from __future__ import annotations

import json

import db
import therapeutic_areas
from fetchers.trials_ctgov import PHASES

_PLACEHOLDERS = ",".join("?" * len(PHASES))


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

        out = []
        for company in companies:
            phases = {p: counts.get((company["id"], p), 0) for p in PHASES}
            out.append(
                {
                    "ticker": company["ticker"],
                    "name": company["name"],
                    "phases": phases,
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
            rows.append(item)
        return rows
    finally:
        conn.close()
