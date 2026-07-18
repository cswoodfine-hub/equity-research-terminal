"""Retiring poisoned change rows, no network."""

import json
from datetime import date, timedelta
from pathlib import Path

import cleanup
import db
import seed

_DETECTED = "2026-07-18 10:30:56"
_OLD = "2008-03-14"                                        # long before detection
_RECENT = (date.fromisoformat("2026-07-18") - timedelta(days=9)).isoformat()


def _seed(db_file):
    """One old approval, one recent approval, one unrelated trial change."""
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    try:
        for key, approval_date in (("NDA020702", _OLD), ("BLA761000", _RECENT)):
            conn.execute(
                "INSERT INTO snapshots (source, entity_type, entity_key, payload)"
                " VALUES ('approvals','approval',?,?)",
                (key, json.dumps({"approval_date": approval_date, "ticker": "AMGN"})),
            )
            conn.execute(
                "INSERT INTO changes (entity_type, entity_key, field, new_value,"
                " change_type, significance, detected_at)"
                " VALUES ('approval',?,'approval',?,'new_approval','high',?)",
                (key, f"AMGN FDA approval: ({key})", _DETECTED),
            )
        conn.execute(
            "INSERT INTO changes (entity_type, entity_key, field, old_value, new_value,"
            " change_type, significance, detected_at)"
            " VALUES ('trial','NCT001','overall_status','Recruiting','Terminated',"
            "'status_change','high',?)",
            (_DETECTED,),
        )
        old_id, recent_id = [r[0] for r in conn.execute(
            "SELECT id FROM changes WHERE change_type='new_approval' ORDER BY id")]
        cid = conn.execute("SELECT id FROM companies WHERE ticker='AMGN'").fetchone()[0]
        conn.execute(
            "INSERT INTO insights (company_id, horizon, body, source_change_ids, model)"
            " VALUES (?,'daily','Cites a poisoned change.',?,'rules')",
            (cid, json.dumps([old_id, recent_id])),
        )
        conn.execute(
            "INSERT INTO insights (company_id, horizon, body, source_change_ids, model)"
            " VALUES (?,'daily','Cites only clean evidence.',?,'rules')",
            (cid, json.dumps([recent_id])),
        )
        conn.commit()
        return old_id, recent_id
    finally:
        conn.close()


def _change_ids(db_file):
    conn = db.get_connection(db_file)
    try:
        return [r[0] for r in conn.execute("SELECT id FROM changes ORDER BY id")]
    finally:
        conn.close()


def test_dry_run_reports_without_deleting(tmp_path):
    db_file = tmp_path / "test.db"
    old_id, _ = _seed(db_file)
    before = _change_ids(db_file)

    report = cleanup.clean(db_file)

    assert [r["id"] for r in report["poisoned_changes"]] == [old_id]
    assert report["applied"] is False and report["backup"] is None
    assert _change_ids(db_file) == before  # nothing written


def test_apply_deletes_only_the_poisoned_rows(tmp_path):
    """The recent approval and the trial change survive; only the back-dated row goes."""
    db_file = tmp_path / "test.db"
    old_id, recent_id = _seed(db_file)

    report = cleanup.clean(db_file, apply=True)

    assert report["applied"] is True
    assert old_id not in _change_ids(db_file)
    assert recent_id in _change_ids(db_file)
    conn = db.get_connection(db_file)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM changes WHERE change_type='status_change'").fetchone()[0] == 1
        # The note built over poisoned evidence goes, the clean one stays.
        bodies = [r[0] for r in conn.execute("SELECT body FROM insights ORDER BY id")]
        assert bodies == ["Cites only clean evidence."]
    finally:
        conn.close()
    assert Path(report["backup"]).exists()


def test_undeterminable_rows_are_kept(tmp_path):
    """No snapshot and no current-state row means no proof, so the change stays."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    conn = db.get_connection(db_file)
    conn.execute(
        "INSERT INTO changes (entity_type, entity_key, field, new_value, change_type,"
        " significance, detected_at) VALUES ('approval','NDA999999','approval','x',"
        "'new_approval','high',?)", (_DETECTED,))
    conn.commit()
    conn.close()

    report = cleanup.clean(db_file, apply=True)

    assert report["poisoned_changes"] == []
    assert len(report["undeterminable_changes"]) == 1
    assert len(_change_ids(db_file)) == 1


def test_clean_database_is_a_no_op(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    report = cleanup.clean(db_file, apply=True)
    assert report["poisoned_changes"] == [] and report["backup"] is None
