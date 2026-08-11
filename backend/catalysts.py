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

# A late-stage readout is a market event whatever the trial's size, so every Phase 3
# primary completion qualifies.
LATE_READOUT_PHASES = ("Phase 3",)

# Phase 2 (and the combined 2/3) roughly triples the volume for a weaker signal, so it is
# admitted only when the study is large enough to be a real efficacy readout rather than
# exploratory dose-finding. 150 is the median enrolment of the eligible Phase 2 trials in
# the universe, which keeps the better-powered half and drops the small-study tail.
NOTABLE_READOUT_PHASES = ("Phase 2", "Phase 2/3")
NOTABLE_MIN_ENROLLMENT = 150

# How far ahead a readout is worth recording. Two years rather than one, because the
# question this feeds is whether a company's money lasts until its next readout, and the
# clinical-stage cohort runs a median runway of about twenty months. A one-year window
# left thirteen of those thirty companies with no catalyst at all, since their primary
# completion dates sit in 2028 and 2029. Past two years the return falls away: a third
# year reaches one more company for another four hundred trials.
#
# Nothing downstream is flooded by the wider window. The catalyst calendar, the sixty-day
# feed and the runway view all filter by date, so a distant row is stored and simply not
# shown until it is near.
READOUT_HORIZON_DAYS = 730

# The pipeline in order, so "the most advanced thing this company is running" is a
# computable idea rather than a list of phases.
PHASE_RANK = {"Phase 1": 1, "Phase 1/2": 2, "Phase 2": 3, "Phase 2/3": 4,
              "Phase 3": 5, "Phase 4": 6}

# Below this, a company has nothing late-stage and the rules above would give it no
# catalysts at all. Phase 3 is the line because the absolute rule already covers it.
LEAD_PHASE_CEILING = PHASE_RANK["Phase 3"]

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
    """Upcoming catalysts (expected_date from today to +within_days), soonest first.

    Pending only: a catalyst resolved met or missed has become history, and history
    already has a home in the snapshots the resolve wrote. ``asset_id`` rides along
    because the stakes view needs a handle on the asset; before it was added, the
    payload's only route to one was the NCT id in ``description``.
    """
    conn = db.get_connection(db_path)
    try:
        query = """
            SELECT cat.id, c.ticker, c.name, cat.catalyst_type, cat.expected_date,
                   cat.date_confidence, cat.title, cat.description, cat.status,
                   cat.is_curated, cat.source_url, cat.asset_id
              FROM catalysts cat JOIN companies c ON cat.company_id = c.id
             WHERE cat.expected_date >= date('now')
               AND cat.expected_date <= date('now', ?)
               AND cat.status = 'pending'
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

    Stored whole. A registry title runs past 180 characters and the part that
    distinguishes one study from another is at the end: two Retatrutide readouts are
    identical until the comparator. Truncating here put that loss in the database,
    where no view could undo it. Each view now cuts it to the width it has.
    """
    subject = brand or (title or "").strip()
    return f"{phase}, {subject}" if subject else phase


def _date_confidence(expected_date) -> str:
    """A month-only date is coarser than an estimated day, and says so."""
    return "estimated" if len(str(expected_date or "")) >= 10 else "month"


def _lead_phase_readouts(conn, within_days: int, already: set) -> list:
    """Readouts for companies that have nothing at Phase 3, on their own lead phase.

    The thresholds above are calibrated on large pharma and say nothing about a
    clinical-stage biotech. Phase 3 or a 150-patient Phase 2 describes Lilly's pipeline;
    it does not describe Beam's, whose most advanced work is Phase 1/2 in thirty
    patients. Across the clinical-stage cohort the largest bucket of dated trials is
    Phase 1/2, which the absolute rule excludes entirely, and their Phase 2 studies
    average 85 patients against 222 at the commercial names. So those companies had
    almost no catalysts at all, which is exactly backwards: a single readout matters far
    more to a company with three programmes than to one with a hundred.

    The rule here is relative and self-calibrating rather than another constant. A trial
    qualifies when it sits at the most advanced phase its sponsor is running, and only
    for sponsors whose most advanced phase is below Phase 3. A company with Phase 3 work
    is already served by the absolute rule and is left alone, so nothing about the
    commercial names changes.
    """
    status_marks = ",".join("?" * len(READOUT_STATUSES))
    rows = conn.execute(
        f"""
        SELECT t.nct_id, t.phase, t.title, t.primary_completion_date AS due,
               t.sponsor_company_id AS company_id, t.asset_id, a.brand_name
          FROM trials t
          LEFT JOIN assets a ON t.asset_id = a.id
         WHERE t.sponsor_company_id IS NOT NULL
           AND t.overall_status IN ({status_marks})
           AND t.primary_completion_date BETWEEN date('now') AND date('now', ?)
        """,
        (*READOUT_STATUSES, f"+{int(within_days)} days"),
    ).fetchall()

    # The sponsor's most advanced active phase, across its whole live pipeline rather
    # than only the trials inside this window. Stage is a property of the company, not
    # of what happens to read out in the next two years: a sponsor whose Phase 3 study
    # completes in year three still runs Phase 3 work, and reading only the window made
    # it look clinical-stage and handed it catalysts for small Phase 2 studies.
    best: dict = {}
    for row in conn.execute(
        f"""
        SELECT sponsor_company_id AS company_id, phase FROM trials
         WHERE sponsor_company_id IS NOT NULL AND overall_status IN ({status_marks})
        """, READOUT_STATUSES):
        rank = PHASE_RANK.get(row["phase"] or "", 0)
        if rank > best.get(row["company_id"], 0):
            best[row["company_id"]] = rank

    lead = []
    for row in rows:
        if row["nct_id"] in already:
            continue
        top = best.get(row["company_id"], 0)
        if top == 0 or top >= LEAD_PHASE_CEILING:
            continue                     # has late-stage work, or no phase on file
        if PHASE_RANK.get(row["phase"] or "", 0) == top:
            lead.append(row)
    return lead


def derive_readouts(db_path=None, within_days=READOUT_HORIZON_DAYS,
                    late_phases=LATE_READOUT_PHASES,
                    notable_phases=NOTABLE_READOUT_PHASES,
                    min_enrollment=NOTABLE_MIN_ENROLLMENT) -> dict:
    """Turn near-term trial primary completion dates into derived readout catalysts.

    Late-stage phases qualify on the date alone. Earlier phases qualify only when their
    enrolment clears ``min_enrollment``, so a large Phase 2 efficacy study is a catalyst
    but a small dose-finding one is not.

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
        late_marks = ",".join("?" * len(late_phases))
        notable_marks = ",".join("?" * len(notable_phases))
        status_marks = ",".join("?" * len(READOUT_STATUSES))
        rows = conn.execute(
            f"""
            SELECT t.nct_id, t.phase, t.title, t.primary_completion_date AS due,
                   t.sponsor_company_id AS company_id, t.asset_id, a.brand_name
              FROM trials t
              LEFT JOIN assets a ON t.asset_id = a.id
             WHERE t.sponsor_company_id IS NOT NULL
               AND t.overall_status IN ({status_marks})
               AND t.primary_completion_date BETWEEN date('now') AND date('now', ?)
               AND (
                     t.phase IN ({late_marks})
                     OR (t.phase IN ({notable_marks})
                         AND COALESCE(t.enrollment, 0) >= ?)
                   )
            """,
            (*READOUT_STATUSES, f"+{int(within_days)} days",
             *late_phases, *notable_phases, min_enrollment),
        ).fetchall()

        rows = list(rows) + _lead_phase_readouts(conn, within_days,
                                                 {r["nct_id"] for r in rows})

        added = updated = 0
        for row in rows:
            url = CTGOV_URL.format(nct_id=row["nct_id"])
            existing = conn.execute(
                "SELECT id, expected_date, title, is_curated FROM catalysts"
                " WHERE source_url = ?",
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
            elif not existing["is_curated"] and (
                    existing["expected_date"] != row["due"]
                    or existing["title"] != title):
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
