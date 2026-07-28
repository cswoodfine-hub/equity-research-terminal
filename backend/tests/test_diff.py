"""The snapshot diff engine, no network."""

from datetime import date, timedelta

import db
import diff
import seed

_RECENT = (date.today() - timedelta(days=7)).isoformat()
_OLD = "2008-03-14"


def _seed_trial(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
        conn.execute(
            """
            INSERT INTO trials (nct_id, sponsor_company_id, title, phase, overall_status,
                                primary_completion_date)
            VALUES ('NCT001', ?, 'Study X', 'Phase 2', 'Recruiting', '2027-06-30')
            """,
            (cid,),
        )
        conn.execute(
            "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
            " VALUES (?, '8-K', '2026-05-01', 'ACC-1', '8-K', 'http://x/1')",
            (cid,),
        )
        conn.commit()
        return cid
    finally:
        conn.close()


def _changes(db_file):
    conn = db.get_connection(db_file)
    try:
        return [dict(r) for r in conn.execute(
            "SELECT entity_key, field, old_value, new_value, change_type, significance"
            " FROM changes ORDER BY id")]
    finally:
        conn.close()


def _seed_approval(db_file, ticker, application_number, approval_date):
    """Give one company a marketed asset with an FDA approval on the given date."""
    conn = db.get_connection(db_file)
    try:
        cid = conn.execute("SELECT id FROM companies WHERE ticker=?", (ticker,)).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO assets (owner_company_id, generic_name, brand_name, is_marketed)"
            " VALUES (?, ?, ?, 1)",
            (cid, f"generic-{application_number}", f"Brand-{application_number}"),
        )
        conn.execute(
            "INSERT INTO approvals (asset_id, region, agency, approval_date, application_number)"
            " VALUES (?, 'US', 'FDA', ?, ?)",
            (cur.lastrowid, approval_date, application_number),
        )
        conn.commit()
    finally:
        conn.close()


def test_baseline_is_per_company_not_global(tmp_path):
    """A refresh that baselines one company must not turn another's back catalogue into news.

    Regression: the baseline flag was a global count over the entity type, so the first
    single-company refresh flipped it for everyone and the next full run emitted every
    other company's decades-old approvals as new_approval.
    """
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    _seed_approval(db_file, "LLY", "NDA100001", _RECENT)
    _seed_approval(db_file, "AMGN", "BLA125268", _OLD)

    # Baseline LLY only, as a single-company refresh would: AMGN's approval is not yet
    # visible to the diff engine, so nothing about it is snapshotted.
    conn = db.get_connection(db_file)
    conn.execute("DELETE FROM approvals WHERE application_number='BLA125268'")
    conn.commit()
    conn.close()
    assert diff.detect_changes(db_file)["new_approvals"] == 0

    # Now the full-universe run sees AMGN for the first time.
    _seed_approval(db_file, "AMGN", "BLA125268", _OLD)
    assert diff.detect_changes(db_file)["new_approvals"] == 0
    assert _changes(db_file) == []

    # AMGN is baselined, so a genuinely recent approval for it does come through.
    _seed_approval(db_file, "AMGN", "BLA761000", _RECENT)
    assert diff.detect_changes(db_file)["new_approvals"] == 1
    assert [c["entity_key"] for c in _changes(db_file)] == ["BLA761000"]


def test_old_approval_is_not_new_for_a_baselined_company(tmp_path):
    """Recency gate: a back-dated approval surfacing late is coverage, not an event."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    _seed_approval(db_file, "LLY", "NDA100001", _RECENT)
    diff.detect_changes(db_file)  # baseline LLY

    _seed_approval(db_file, "LLY", "NDA020702", _OLD)
    assert diff.detect_changes(db_file)["new_approvals"] == 0
    assert _changes(db_file) == []


def test_baseline_then_detect_then_idempotent(tmp_path):
    db_file = tmp_path / "test.db"
    cid = _seed_trial(db_file)

    # First run: baseline only, nothing emitted.
    assert diff.detect_changes(db_file) == {"trial_changes": 0, "new_filings": 0,
                                            "new_approvals": 0, "restatements": 0,
                                            "label_changes": 0,
                                            "efficacy_supplements": 0,
                                            "filing_text_changes": 0}
    assert _changes(db_file) == []

    # Change the trial and add a new filing.
    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Terminated', "
                 "primary_completion_date='2028-12-31', phase='Phase 3' WHERE nct_id='NCT001'")
    conn.execute("INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
                 " VALUES (?, '8-K', '2026-06-01', 'ACC-2', 'New 8-K', 'http://x/2')", (cid,))
    conn.commit()
    conn.close()

    summary = diff.detect_changes(db_file)
    assert summary["trial_changes"] == 1 and summary["new_filings"] == 1

    changes = _changes(db_file)
    kinds = {c["change_type"]: c for c in changes}
    assert kinds["status_change"]["new_value"] == "Terminated"
    assert kinds["status_change"]["significance"] == "high"
    # The trial is Phase 3 by this update and the slip runs past the materiality
    # threshold, which is exactly the slip an analyst must not miss.
    assert kinds["date_slip"]["significance"] == "high"
    assert kinds["phase_advance"]["new_value"] == "Phase 3"
    assert "ACC-2" in {c["entity_key"] for c in changes}  # new filing
    assert "ACC-1" not in {c["entity_key"] for c in changes}  # pre-existing baselined

    # Re-running detects nothing new.
    diff.detect_changes(db_file)
    assert len(_changes(db_file)) == len(changes)


def _watched_trial(db_file, **fields):
    """One trial of a seeded company, with the fields the diff engine watches."""
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
        cols = {"nct_id": "NCT900", "sponsor_company_id": cid, "title": "A study",
                "phase": "Phase 3", "overall_status": "Recruiting",
                "primary_completion_date": "2027-05",
                "primary_outcome": "Overall survival",
                "design": "Randomized, Double, Treatment", "enrollment": 600}
        cols.update(fields)
        conn.execute(
            f"INSERT INTO trials ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})", list(cols.values()))
        conn.commit()
    finally:
        conn.close()


def _revise(db_file, **fields):
    """The registry updating the trial record, which is what a refresh sees."""
    conn = db.get_connection(db_file)
    try:
        for key, value in fields.items():
            conn.execute(f"UPDATE trials SET {key} = ? WHERE nct_id = 'NCT900'", (value,))
        conn.commit()
    finally:
        conn.close()


def _of_type(db_file, change_type):
    return [c for c in _changes(db_file) if c["change_type"] == change_type]


def test_a_rewritten_endpoint_is_caught(tmp_path):
    """The claim an analyst makes about the field, that endpoints are being changed
    mid-trial, cannot be made from today's data. It needs the previous wording."""
    db_file = tmp_path / "endpoint.db"
    _watched_trial(db_file)
    diff.detect_changes(db_file)                      # baseline is not news
    assert _of_type(db_file, "endpoint_change") == []

    _revise(db_file, primary_outcome="Progression-free survival")
    diff.detect_changes(db_file)
    caught = _of_type(db_file, "endpoint_change")
    assert len(caught) == 1
    assert caught[0]["old_value"] == "Overall survival"
    assert caught[0]["new_value"] == "Progression-free survival"
    assert caught[0]["significance"] == "high"        # on a Phase 3


def test_a_rewritten_endpoint_on_an_early_trial_reads_lower(tmp_path):
    db_file = tmp_path / "endpoint2.db"
    _watched_trial(db_file, phase="Phase 1")
    diff.detect_changes(db_file)
    _revise(db_file, primary_outcome="Safety and tolerability")
    diff.detect_changes(db_file)
    assert _of_type(db_file, "endpoint_change")[0]["significance"] == "medium"


def test_dropping_the_blind_is_a_design_change(tmp_path):
    db_file = tmp_path / "design.db"
    _watched_trial(db_file)
    diff.detect_changes(db_file)
    _revise(db_file, design="Randomized, None, Treatment")
    diff.detect_changes(db_file)
    caught = _of_type(db_file, "design_change")
    assert len(caught) == 1 and "None" in caught[0]["new_value"]


def test_enrolment_drift_is_not_an_event(tmp_path):
    """A recruiting trial's target moves a little all the time. Only a resizing counts."""
    db_file = tmp_path / "enrol.db"
    _watched_trial(db_file)
    diff.detect_changes(db_file)

    _revise(db_file, enrollment=610)                  # under two percent, noise
    diff.detect_changes(db_file)
    assert _of_type(db_file, "enrollment_change") == []

    _revise(db_file, enrollment=300)                  # halved, a decision
    diff.detect_changes(db_file)
    caught = _of_type(db_file, "enrollment_change")
    assert len(caught) == 1 and caught[0]["significance"] == "medium"
