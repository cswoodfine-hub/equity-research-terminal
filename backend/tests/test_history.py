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


def test_the_valuation_calls_travel_in_git_and_not_only_in_the_release(tmp_path):
    """A valuation call is scored against a forward return twelve months out, so it has
    to survive twelve months of runs. It lived only inside the published database, which
    no source can hand back: if that asset were lost, or a restore fell through to the
    rebuild path, the whole call history went with it and the clock started again.

    A refusal round-trips with its reason, because a book that kept only its answers
    would flatter itself.
    """
    src = tmp_path / "src.db"
    db.init(src)
    seed.load_companies(src)
    conn = db.get_connection(src)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    conn.execute(
        "INSERT INTO valuation_snapshots (company_id, as_of, captured_at, close,"
        " equity_per_share, upside) VALUES (?, '2026-11-06', '2026-11-06 06:00:00',"
        " 1415.64, 975.0, -0.311)", (cid,))
    conn.execute(
        "INSERT INTO valuation_snapshots (company_id, as_of, captured_at, close,"
        " refused) VALUES ((SELECT id FROM companies WHERE ticker='BMRN'),"
        " '2026-11-06', '2026-11-06 06:00:00', 57.49,"
        " 'marketed products: none of what the company reports selling is modelled')")
    conn.commit()
    conn.close()

    out = tmp_path / "history"
    assert history.export(src, out)["valuation_snapshots"] == 2
    assert (out / "valuation_snapshots.ndjson").exists()

    dest = tmp_path / "dest.db"
    assert history.rebuild(dest, out)["valuation_snapshots"] == 2
    conn = db.get_connection(dest)
    try:
        rows = {r["upside"]: r["refused"] for r in conn.execute(
            "SELECT upside, refused FROM valuation_snapshots")}
        assert rows[-0.311] is None
        assert "none of what the company reports selling is modelled" in rows[None]
    finally:
        conn.close()


def test_a_second_run_in_a_day_replaces_its_call_rather_than_doubling_it(tmp_path):
    """The table is keyed on (company, price date) and the export is loaded with INSERT
    OR REPLACE, so a rebuild onto a database that already holds the day cannot leave two
    calls for one company on one date. The workflow does exactly that every morning: it
    restores yesterday's published database and then rebuilds the committed history onto
    it."""
    src = tmp_path / "src.db"
    db.init(src)
    seed.load_companies(src)
    conn = db.get_connection(src)
    conn.execute(
        "INSERT INTO valuation_snapshots (company_id, as_of, captured_at, close, upside)"
        " VALUES ((SELECT id FROM companies WHERE ticker='LLY'), '2026-11-06',"
        " '2026-11-06 06:00:00', 1415.64, -0.311)")
    conn.commit()
    conn.close()

    out = tmp_path / "history"
    history.export(src, out)
    history.rebuild(src, out)                      # onto the database it came from
    conn = db.get_connection(src)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM valuation_snapshots").fetchone()[0] == 1
    finally:
        conn.close()


def test_catalyst_resolutions_travel_in_git_like_the_valuation_calls(tmp_path):
    """A resolution is dated by an approval or an announcement and no source hands the
    calendar's own record back."""
    assert "catalyst_resolutions" in history.HISTORY_TABLES
    src = tmp_path / "src.db"
    db.init(src)
    seed.load_companies(src)
    conn = db.get_connection(src)
    conn.execute("INSERT INTO catalysts (id, company_id, catalyst_type, expected_date, title, status)"
                 " VALUES (7, 1, 'PDUFA', '2026-09-22', 'X', 'met')")
    conn.execute("INSERT INTO catalyst_resolutions (catalyst_id, outcome, event_date, source, evidence, basis, dedupe)"
                 " VALUES (7, 'met', '2026-09-03', 'approvals', 'FDA approval NDA220210', 'rule', 'FDA approval NDA220210')")
    conn.commit()
    conn.close()
    out = tmp_path / "history"
    assert history.export(src, out)["catalyst_resolutions"] == 1
    dest = tmp_path / "dest.db"
    assert history.rebuild(dest, out)["catalyst_resolutions"] == 1


def test_what_the_model_read_travels_in_git(tmp_path):
    """A filing can be fetched again; the reading of it costs a model call. These lived
    only inside the published database, and a restore from it on 2026-11-09 arrived with
    every one empty, taking 1,359 readouts and 1,728 PDUFA reads out of the book.

    Two of them carry no id column, so the round trip is checked rather than assumed."""
    for table in ("trial_readouts", "pdufa_reads", "guidance_scans", "consensus_estimates"):
        assert table in history.HISTORY_TABLES, table
    src = tmp_path / "src.db"
    db.init(src)
    seed.load_companies(src)
    conn = db.get_connection(src)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date, quote) VALUES ('0001-26-1', 1, 'tirzepatide', 3, 'positive',"
                 " '2026-10-03', 'met its primary endpoint')")
    conn.execute("INSERT INTO pdufa_reads (accession, url, form_type, filed_date, outcome)"
                 " VALUES ('0001-26-2', 'https://x', '8-K', '2026-10-03', 'none')")
    conn.execute("INSERT INTO guidance_scans (accession, section, found)"
                 " VALUES ('0001-26-3', 'exhibit', 1)")
    conn.execute("INSERT INTO consensus_estimates (company_id, metric, period, value,"
                 " currency, source, as_of, note) VALUES (1, 'Revenue', 'FY2026',"
                 " 1.3e9, 'USD', 'guidance', '2026-05-06', 'Total net product revenues')")
    conn.commit()
    conn.close()

    out = tmp_path / "history"
    got = history.export(src, out)
    assert all(got[t] == 1 for t in ("trial_readouts", "pdufa_reads", "guidance_scans",
                                     "consensus_estimates"))

    # Into a database that never held them, and then again, which must not duplicate the
    # rows whose table has no id to replace on.
    fresh = tmp_path / "fresh.db"
    db.init(fresh)
    history.rebuild(fresh, out)
    history.rebuild(fresh, out)
    conn = db.get_connection(fresh)
    try:
        for table in ("trial_readouts", "pdufa_reads", "guidance_scans",
                      "consensus_estimates"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 1, table
        assert conn.execute("SELECT outcome FROM trial_readouts").fetchone()[0] == "positive"
    finally:
        conn.close()


def test_the_guidance_reader_is_not_held_to_twenty_sections_a_run():
    """At twenty a 1,267-section backlog takes sixty-four runs, and the ledger that
    remembers the progress was not carried in history, so it never finished."""
    import guidance
    assert guidance.MAX_PER_RUN >= 400
    assert guidance.extract.__defaults__[1] == guidance.MAX_PER_RUN
