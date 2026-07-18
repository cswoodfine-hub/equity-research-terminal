"""The snapshot diff engine, no network."""

import db
import diff
import seed


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


def test_baseline_then_detect_then_idempotent(tmp_path):
    db_file = tmp_path / "test.db"
    cid = _seed_trial(db_file)

    # First run: baseline only, nothing emitted.
    assert diff.detect_changes(db_file) == {"trial_changes": 0, "new_filings": 0,
                                            "new_approvals": 0}
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
    assert kinds["date_slip"]["significance"] == "medium"
    assert kinds["phase_advance"]["new_value"] == "Phase 3"
    assert "ACC-2" in {c["entity_key"] for c in changes}  # new filing
    assert "ACC-1" not in {c["entity_key"] for c in changes}  # pre-existing baselined

    # Re-running detects nothing new.
    diff.detect_changes(db_file)
    assert len(_changes(db_file)) == len(changes)
