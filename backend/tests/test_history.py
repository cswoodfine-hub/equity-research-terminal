"""History export/rebuild: the round-trip must preserve the proprietary rows, and
the text must be append-friendly so git stores deltas cleanly."""

import json

import db
import diff
import history
import seed


def _seed_history(db_file):
    """A database with a snapshot, a detected change, and a curated catalyst."""
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO trials (nct_id, sponsor_company_id, title, phase,"
        " overall_status, primary_completion_date) VALUES ('NCT1', ?, 'T',"
        " 'Phase 3', 'Recruiting', '2027-06-30')", (cid,))
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)                       # baseline snapshot
    conn = db.get_connection(db_file)
    conn.execute("UPDATE trials SET overall_status='Terminated' WHERE nct_id='NCT1'")
    conn.commit()
    conn.close()
    diff.detect_changes(db_file)                       # a change + new snapshot


def _counts(db_file, tables):
    conn = db.get_connection(db_file)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in tables}
    finally:
        conn.close()


def test_export_then_rebuild_preserves_the_history(tmp_path):
    src = tmp_path / "src.db"
    _seed_history(src)
    before = _counts(src, ["snapshots", "changes"])
    assert before["snapshots"] > 0 and before["changes"] == 1

    out = tmp_path / "history"
    written = history.export(src, out)
    assert written["snapshots"] == before["snapshots"]
    assert (out / "snapshots.ndjson").exists()

    dest = tmp_path / "dest.db"
    seed.load_companies.__wrapped__ if False else None   # dest starts empty
    loaded = history.rebuild(dest, out)
    assert loaded["changes"] == 1
    after = _counts(dest, ["snapshots", "changes"])
    assert after == before                              # every row round-tripped


def test_rebuilt_history_lets_the_diff_continue_without_replaying(tmp_path):
    """The rebuilt snapshots are the diff engine's memory: a refresh against them
    must not re-emit the whole back catalogue as new."""
    src = tmp_path / "src.db"
    _seed_history(src)
    out = tmp_path / "history"
    history.export(src, out)

    dest = tmp_path / "dest.db"
    history.rebuild(dest, out)
    # The trial current-state table is empty in dest (not exported), so re-detecting
    # finds nothing new; crucially it does not re-flag the terminated trial.
    summary = diff.detect_changes(dest)
    assert summary["trial_changes"] == 0
    conn = db.get_connection(dest)
    try:
        assert conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 1
    finally:
        conn.close()


def test_export_is_ordered_and_stable(tmp_path):
    src = tmp_path / "src.db"
    _seed_history(src)
    out = tmp_path / "history"
    history.export(src, out)
    lines = (out / "snapshots.ndjson").read_text().strip().splitlines()
    ids = [json.loads(line)["id"] for line in lines]
    assert ids == sorted(ids)                          # ascending, so appends go last
    # keys sorted per line, so re-exporting unchanged data yields identical text
    first = json.loads(lines[0])
    assert list(first.keys()) == sorted(first.keys())


def test_rebuild_is_idempotent(tmp_path):
    src = tmp_path / "src.db"
    _seed_history(src)
    out = tmp_path / "history"
    history.export(src, out)
    dest = tmp_path / "dest.db"
    history.rebuild(dest, out)
    history.rebuild(dest, out)                          # twice
    assert _counts(dest, ["snapshots"]) == _counts(src, ["snapshots"])
