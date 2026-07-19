"""Catalysts, hand entered and derived.

No free PDUFA calendar exists, so PDUFA dates stay hand entered (is_curated=1). Data
readouts do not need one: a Phase 3 trial with a primary completion date a few months
out is a readout, and those dates are already fetched into ``trials`` on every refresh.
``derive_readouts`` turns them into catalysts marked is_curated=0, which the UI shows as
derived and unreviewed. Nothing is invented; every derived row points back at its trial.

Auto-extraction of PDUFA dates from 8-K/6-K needs the filing bodies, which are not
fetched yet, and remains a later add.
"""

from __future__ import annotations

import db

CATALYST_TYPES = ["PDUFA", "data readout", "EMA decision", "AdCom", "conference", "other"]

CTGOV_URL = "https://clinicaltrials.gov/study/{nct_id}"

# Phase 3 only by default. Phase 2 roughly triples the volume for a much weaker signal,
# and a catalyst tab nobody can scan is worse than one that is thin.
READOUT_PHASES = ("Phase 3",)

# A trial that has stopped enrolling is still going to read out; one that was terminated
# or withdrawn is not.
READOUT_STATUSES = ("Recruiting", "Active not recruiting", "Enrolling by invitation",
                    "Not yet recruiting")


def add_catalyst(db_path, ticker, catalyst_type, expected_date, title,
                 description=None, date_confidence="estimated", source_url=None,
                 is_curated=1):
    """Write a catalyst. ``is_curated=0`` marks a row a machine produced, which is what
    lets a later refresh revise or withdraw it and tells the UI to show its evidence."""
    conn = db.get_connection(db_path)
    try:
        company = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if company is None:
            raise ValueError(f"unknown ticker {ticker.upper()}")
        cur = conn.execute(
            """
            INSERT INTO catalysts
                (company_id, catalyst_type, expected_date, date_confidence, title,
                 description, is_curated, source_url, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (company["id"], catalyst_type, expected_date, date_confidence, title,
             description, int(is_curated), source_url),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_catalysts(db_path=None, within_days=90, ticker=None):
    """Upcoming catalysts (expected_date from today to +within_days), soonest first."""
    conn = db.get_connection(db_path)
    try:
        query = """
            SELECT cat.id, c.ticker, c.name, cat.catalyst_type, cat.expected_date,
                   cat.date_confidence, cat.title, cat.description, cat.status,
                   cat.is_curated, cat.source_url
              FROM catalysts cat JOIN companies c ON cat.company_id = c.id
             WHERE cat.expected_date >= date('now')
               AND cat.expected_date <= date('now', ?)
        """
        params = [f"+{int(within_days)} days"]
        if ticker:
            query += " AND c.ticker = ?"
            params.append(ticker.upper())
        query += " ORDER BY cat.expected_date"
        return [dict(r) for r in conn.execute(query, params)]
    finally:
        conn.close()


def delete_catalyst(db_path, catalyst_id) -> bool:
    conn = db.get_connection(db_path)
    try:
        cur = conn.execute("DELETE FROM catalysts WHERE id = ?", (catalyst_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_status(db_path, catalyst_id, status) -> bool:
    conn = db.get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE catalysts SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, catalyst_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def accept_catalyst(db_path, catalyst_id) -> bool:
    """Promote a derived row to curated, which takes it out of the review queue."""
    conn = db.get_connection(db_path)
    try:
        cur = conn.execute(
            "UPDATE catalysts SET is_curated = 1, updated_at = datetime('now')"
            " WHERE id = ? AND is_curated = 0",
            (catalyst_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _readout_title(phase, brand, title) -> str:
    """Lead with the asset when the trial is mapped to one, else with the study.

    No "readout" here. catalyst_type already carries it, and the feed renders
    "{ticker} {type}: {title}", which read as "data readout: Phase 3 readout".
    """
    subject = brand or (title or "").strip()[:70]
    return f"{phase}, {subject}" if subject else phase


def _date_confidence(expected_date) -> str:
    """A month-only date is coarser than an estimated day, and says so."""
    return "estimated" if len(str(expected_date or "")) >= 10 else "month"


def derive_readouts(db_path=None, within_days=365, phases=READOUT_PHASES) -> dict:
    """Turn near-term trial primary completion dates into derived readout catalysts.

    Every future primary completion date on ClinicalTrials.gov is an estimate, so these
    land as date_confidence='estimated'. They slip, and that is the point: the diff
    engine already reports a primary completion slip, so a moving readout shows up in
    the what-changed feed on its own.

    Idempotent. The trial's registry URL is the identity of the row, so a re-run updates
    the date in place rather than adding a second copy. A row the analyst has accepted
    (is_curated=1) is left alone; their judgement outranks the derivation.
    """
    conn = db.get_connection(db_path)
    try:
        marks = ",".join("?" * len(phases))
        status_marks = ",".join("?" * len(READOUT_STATUSES))
        rows = conn.execute(
            f"""
            SELECT t.nct_id, t.phase, t.title, t.primary_completion_date AS due,
                   t.sponsor_company_id AS company_id, t.asset_id, a.brand_name
              FROM trials t
              LEFT JOIN assets a ON t.asset_id = a.id
             WHERE t.sponsor_company_id IS NOT NULL
               AND t.phase IN ({marks})
               AND t.overall_status IN ({status_marks})
               AND t.primary_completion_date BETWEEN date('now') AND date('now', ?)
            """,
            (*phases, *READOUT_STATUSES, f"+{int(within_days)} days"),
        ).fetchall()

        added = updated = 0
        for row in rows:
            url = CTGOV_URL.format(nct_id=row["nct_id"])
            existing = conn.execute(
                "SELECT id, expected_date, is_curated FROM catalysts WHERE source_url = ?",
                (url,),
            ).fetchone()
            title = _readout_title(row["phase"], row["brand_name"], row["title"])
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO catalysts
                        (company_id, asset_id, catalyst_type, expected_date,
                         date_confidence, title, description, is_curated, source_url,
                         status)
                    VALUES (?, ?, 'data readout', ?, ?, ?, ?, 0, ?, 'pending')
                    """,
                    (row["company_id"], row["asset_id"], row["due"],
                     _date_confidence(row["due"]), title, row["nct_id"], url),
                )
                added += 1
            elif not existing["is_curated"] and existing["expected_date"] != row["due"]:
                conn.execute(
                    "UPDATE catalysts SET expected_date = ?, date_confidence = ?,"
                    " title = ?, updated_at = datetime('now') WHERE id = ?",
                    (row["due"], _date_confidence(row["due"]), title, existing["id"]),
                )
                updated += 1

        # A trial that left the window, stopped, or read out should not linger as a
        # pending catalyst. Only derived rows are withdrawn; curated ones are the
        # analyst's and are never removed here.
        live = {CTGOV_URL.format(nct_id=r["nct_id"]) for r in rows}
        stale = [
            r["id"] for r in conn.execute(
                "SELECT id, source_url FROM catalysts"
                " WHERE is_curated = 0 AND catalyst_type = 'data readout'")
            if r["source_url"] not in live
        ]
        for catalyst_id in stale:
            conn.execute("DELETE FROM catalysts WHERE id = ?", (catalyst_id,))
        conn.commit()
        return {"added": added, "updated": updated, "withdrawn": len(stale),
                "total": len(rows)}
    finally:
        conn.close()
