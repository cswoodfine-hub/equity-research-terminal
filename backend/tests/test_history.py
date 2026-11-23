"""History export/rebuild: the round-trip must preserve the proprietary rows, and
the text must be append-friendly so git stores deltas cleanly."""

import json
import shutil

import pytest

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


# --- two books, one set of numbers ----------------------------------------------------
# The scheduled run and a refresh on an analyst's machine both start from the published
# database and both take the next number in every table. From the first refresh each
# runs, the same number is two different rows.

def _a_run(db_file, started, entity, close):
    """One refresh's worth of history: a run, a snapshot, a change, a catalyst, a rate,
    a call and a valuation, each taking the next number its table has."""
    day = started[:10]
    conn = db.get_connection(db_file)
    try:
        run = conn.execute("INSERT INTO refresh_runs (started_at, finished_at, status)"
                           " VALUES (?, ?, 'complete')", (started, started)).lastrowid
        conn.execute("INSERT INTO snapshots (source, entity_type, entity_key, captured_at,"
                     " payload, refresh_run_id) VALUES ('prices', 'company', ?, ?, ?, ?)",
                     (entity, started, json.dumps({"close": close}), run))
        conn.execute("INSERT INTO changes (entity_type, entity_key, field, old_value,"
                     " new_value, detected_at, refresh_run_id) VALUES ('company', ?,"
                     " 'close', NULL, ?, ?, ?)", (entity, str(close), started, run))
        conn.execute("INSERT INTO catalysts (company_id, catalyst_type, title, created_at)"
                     " VALUES ((SELECT id FROM companies WHERE ticker = ?), 'data readout',"
                     " ?, ?)", (entity, f"{entity} readout", started))
        conn.execute("INSERT INTO fx_rates (base, quote, rate, as_of) VALUES"
                     " ('EUR', 'USD', ?, ?)", (close / 100, day))
        conn.execute("INSERT INTO model_calls (as_of, ticker, price, fair_value,"
                     " refresh_run_id) VALUES (?, ?, ?, ?, ?)",
                     (day, entity, close, close * 1.1, run))
        conn.execute("INSERT INTO valuation_snapshots (company_id, as_of, captured_at,"
                     " close, refresh_run_id) VALUES ((SELECT id FROM companies"
                     " WHERE ticker = ?), ?, ?, ?, ?)", (entity, day, started, close, run))
        conn.commit()
    finally:
        conn.close()


def _everything(db_file) -> dict:
    """Every row of every history table, by table: what a merge must not disturb."""
    conn = db.get_connection(db_file)
    try:
        return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")]
                for t in history.HISTORY_TABLES}
    finally:
        conn.close()


def _files(folder) -> dict:
    return {p.name: p.read_bytes() for p in sorted(folder.glob("*.ndjson"))}


def _two_books(tmp_path):
    """The published database at run 2, and the two books that grew from it: the
    scheduled one, whose run 3 is in the committed files, and the analyst's, whose run 3
    is a different refresh on a different day."""
    release = tmp_path / "release.db"
    db.init(release)
    seed.load_companies(release)
    _a_run(release, "2026-11-07 06:00:00", "LLY", 900.0)
    _a_run(release, "2026-11-08 06:00:00", "LLY", 905.0)
    record = tmp_path / "history"
    history.export(release, record)

    scheduled, local = tmp_path / "scheduled.db", tmp_path / "local.db"
    shutil.copy(release, scheduled)
    shutil.copy(release, local)
    _a_run(scheduled, "2026-11-09 06:00:00", "MRK", 80.0)
    history.export(scheduled, record)             # the day's commit
    _a_run(local, "2026-11-23 14:26:03", "BMY", 45.0)
    return release, scheduled, local, record


def test_every_exported_table_says_what_makes_a_row_itself(tmp_path):
    """A table merged by number alone is a table two books can overwrite each other in.
    One added to the export with no entry in SAME_ROW would be merged that way."""
    path = tmp_path / "book.db"
    db.init(path)
    conn = db.get_connection(path)
    try:
        for table in history.HISTORY_TABLES:
            columns = history._columns(conn, table)
            assert columns, f"{table} is exported and is not a table"
            if "id" not in columns:
                continue                              # keyed by what the row is
            assert table in history.SAME_ROW, (
                f"{table} is numbered and exported, and SAME_ROW does not say what "
                "makes one of its rows the same row in two books")
            named, _unique = history.SAME_ROW[table]
            assert named and set(named) <= set(columns), (table, named)
    finally:
        conn.close()


def test_two_books_that_parted_are_never_merged_by_number(tmp_path):
    """The case found on 2026-11-23: run 131 was 23 November in the book and 11 November
    in the record. Both directions are refused and neither side loses a row."""
    _release, _scheduled, local, record = _two_books(tmp_path)
    found = history.parted(local, record)
    assert found["refresh_runs"]["different"] == 1 and found["refresh_runs"]["first"] == 3
    assert found["refresh_runs"]["example"] == {
        "id": 3, "book": {"started_at": "2026-11-23 14:26:03"},
        "file": {"started_at": "2026-11-09 06:00:00"}}
    assert {"snapshots", "changes", "catalysts", "fx_rates", "model_calls",
            "valuation_snapshots"} <= set(found)

    book_before, files_before = _everything(local), _files(record)
    # The record into the book: run 3 of the record would have taken the place of the
    # book's run 3, and so on down every table.
    with pytest.raises(history.Parted) as refused:
        history.rebuild(local, record)
    assert "refresh_runs: 1 from number 3 are different rows" in str(refused.value)
    assert "Nothing was written" in str(refused.value)
    assert _everything(local) == book_before
    # The book into the record: the files are written whole, so the record's run 3
    # would have gone and the book's would have been committed in its place.
    with pytest.raises(history.Parted):
        history.export(local, record)
    assert _files(record) == files_before
    assert _everything(local) == book_before


def test_the_records_own_book_still_merges_and_loses_nothing(tmp_path):
    """The other half: the guard must not stop the scheduled run. Yesterday's release
    takes today's commit, every row it held is still there, and the result is the
    scheduled book row for row. So is a database built from the files alone."""
    release, scheduled, _local, record = _two_books(tmp_path)
    assert history.parted(release, record) == {}
    before = _everything(release)
    loaded = history.rebuild(release, record)
    assert loaded["refresh_runs"] == 3
    after = _everything(release)
    for table, rows in before.items():
        assert set(rows) <= set(after[table]), f"{table} lost a row in the merge"
    assert after == _everything(scheduled)

    fresh = tmp_path / "fresh.db"
    history.rebuild(fresh, record)
    assert _everything(fresh) == after
    # And the scheduled book writes the files back unchanged.
    files = _files(record)
    history.export(scheduled, record)
    assert _files(record) == files


def test_a_row_edited_in_place_is_still_the_same_row(tmp_path):
    """A catalyst renamed, a run that finished: the columns SAME_ROW leaves out are free
    to change, and the file's version of the same row replaces the book's as it did."""
    release, _scheduled, _local, record = _two_books(tmp_path)
    path = record / "catalysts.ndjson"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["title"] = "LLY readout, renamed"
    rows[0]["status"] = "met"
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    history.rebuild(release, record)
    conn = db.get_connection(release)
    try:
        got = conn.execute("SELECT title, status FROM catalysts WHERE id = ?",
                           (rows[0]["id"],)).fetchone()
    finally:
        conn.close()
    assert tuple(got) == ("LLY readout, renamed", "met")


def test_a_book_the_record_has_left_behind_cannot_be_exported_over_it(tmp_path):
    """No number is shared for two rows here: the book simply stops at run 2 and the
    files go on to run 3. The export writes each file whole, so it would take run 3 out
    of the record."""
    release, _scheduled, _local, record = _two_books(tmp_path)
    assert history.parted(release, record) == {}
    files = _files(record)
    with pytest.raises(history.Parted) as refused:
        history.export(release, record)
    assert refused.value.found["refresh_runs"] == {"missing": 1}
    assert "1 the files hold are not in the book" in str(refused.value)
    assert _files(record) == files


def test_the_same_row_under_another_number_is_not_loaded_over_the_books(tmp_path):
    """Where the table keeps a key unique, INSERT OR REPLACE makes room for the file's
    row by deleting whichever of the book's rows holds that key, under any number. The
    book's rate for the day is under 7 and the file's is under 9: loading it would
    delete the book's row without a number in common to show for it."""
    path = tmp_path / "book.db"
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO fx_rates (id, base, quote, rate, as_of) VALUES"
                 " (7, 'EUR', 'USD', 1.08, '2026-11-20')")
    conn.commit()
    conn.close()
    folder = tmp_path / "history"
    folder.mkdir()
    (folder / "fx_rates.ndjson").write_text(json.dumps(
        {"id": 9, "base": "EUR", "quote": "USD", "rate": 1.09, "as_of": "2026-11-20"}) + "\n")
    assert history.parted(path, folder) == {"fx_rates": {"different": 0, "renumbered": 1}}
    before = _everything(path)
    with pytest.raises(history.Parted) as refused:
        history.rebuild(path, folder)
    assert "1 are the same rows under other numbers" in str(refused.value)
    assert _everything(path) == before


def test_a_restored_database_that_is_another_books_is_turned_away(tmp_path):
    """The run number alone passed it: the analyst's book is at run 3 and so is the
    committed history. They are not the same run 3."""
    _release, scheduled, local, record = _two_books(tmp_path)
    assert history.restore_check(scheduled, record)["restored"] is True
    # Asked without removal, as the command line does off a runner: the verdict, and the
    # file left where it was.
    got = history.restore_check(local, record, remove=False)
    assert got["restored"] is False and got["removed"] is False
    assert "not the committed history's own" in got["why"]
    assert local.exists()
    # On a runner the download is removed, so the rebuild starts clean.
    download = tmp_path / "download.db"
    shutil.copy(local, download)
    assert history.restore_check(download, record)["restored"] is False
    assert not download.exists()


def test_a_number_given_out_twice_by_one_book_is_not_another_book(tmp_path):
    """SQLite gives a new row one more than the highest number in its table, so a book
    that removes its newest catalyst and makes another has two rows that held one number.
    A release whose history push failed can be exactly there against the files, and a
    guard that called it another book would discard the release and the unpushed day
    with it. The book has seen everything the files hold, so its row stands."""
    _release, scheduled, _local, record = _two_books(tmp_path)
    conn = db.get_connection(scheduled)
    conn.execute("DELETE FROM catalysts WHERE id = 3")
    again = conn.execute(
        "INSERT INTO catalysts (company_id, catalyst_type, title, created_at) VALUES"
        " ((SELECT id FROM companies WHERE ticker = 'MRK'), 'PDUFA', 'made after',"
        " '2026-11-09 06:20:00')").lastrowid
    conn.commit()
    conn.close()
    assert again == 3                                  # the number, given out again
    got = history.standing(scheduled, record)
    assert got["another_book"] is False and got["runs_behind"] == 0
    assert got["parted"]["catalysts"]["different"] == 1
    assert history.restore_check(scheduled, record)["restored"] is True

    before = _everything(scheduled)
    history.rebuild(scheduled, record)
    assert _everything(scheduled) == before            # the file's older row did not land
    history.export(scheduled, record)
    rows = [json.loads(line) for line in
            (record / "catalysts.ndjson").read_text().splitlines()]
    assert [r["title"] for r in rows if r["id"] == 3] == ["made after"]


def test_a_book_behind_the_record_with_a_row_of_its_own_is_not_loaded_over(tmp_path):
    """Restored at run 2 and given a catalyst by hand, with no refresh: no run and no
    snapshot disagrees. The record has since made its own catalyst 3. The book has not
    seen the files' run 3, so its catalyst 3 cannot be something it made after them."""
    release, _scheduled, _local, record = _two_books(tmp_path)
    conn = db.get_connection(release)
    conn.execute("INSERT INTO catalysts (company_id, catalyst_type, title, created_at)"
                 " VALUES ((SELECT id FROM companies WHERE ticker = 'BMY'), 'AdCom',"
                 " 'entered by hand', '2026-11-08 17:00:00')")
    conn.commit()
    conn.close()
    got = history.standing(release, record)
    assert got == {"another_book": False, "runs_behind": 1, "parted": got["parted"]}
    assert set(got["parted"]) == {"catalysts"}
    before = _everything(release)
    with pytest.raises(history.Parted) as refused:
        history.rebuild(release, record)
    assert "catalysts: 1 from number 3 are different rows" in str(refused.value)
    assert _everything(release) == before
