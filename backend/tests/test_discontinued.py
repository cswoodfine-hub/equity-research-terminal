"""Programmes a company has stopped: retired from the pipeline, never deleted."""

import csv
import re

import asset_merge
import db
import discontinued as D
import forecast_view as V
import pipeline
import pipeline_sort
import trial_mapping

HEADER = "ticker,name,stopped_on,basis\n"


def _db(tmp_path):
    path = str(tmp_path / "stop.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.executescript("""
        INSERT INTO companies (id, ticker, name) VALUES (1, 'REGN', 'Regeneron'),
                                                         (2, 'PFE', 'Pfizer');
        INSERT INTO indications (id, name) VALUES (1, 'beta-Thalassemia');
        INSERT INTO assets (id, owner_company_id, generic_name, internal_code, brand_name,
                            is_marketed)
        VALUES (1, 1, NULL, 'REGN7999', NULL, 0),     -- stopped, trial still recruiting
               (2, 1, 'Pozelimab', NULL, NULL, 0),    -- live
               (3, 2, 'Fidanacogene', NULL, 'Beqvez', 1);
        INSERT INTO asset_indications (asset_id, indication_id, phase) VALUES
               (1, 1, 'Phase 3'), (2, 1, 'Phase 3');
        INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase, overall_status,
                            primary_completion_date) VALUES
               ('NCT06421636', 1, 1, 'Phase 3', 'Recruiting', '2027-06-01'),
               ('NCT00000002', 2, 1, 'Phase 3', 'Recruiting', '2027-06-01');
    """)
    conn.commit()
    return path, conn


def _file(tmp_path, body):
    path = tmp_path / "stopped.csv"
    path.write_text("# a comment line\n" + HEADER + body)
    return path


REGN = ("REGN,REGN7999,2026-07-30,Regeneron's 10-Q filed 2026-07-30 states it has "
        "discontinued further clinical development of REGN7999\n")


def test_a_named_programme_is_retired_with_its_basis(tmp_path):
    path, conn = _db(tmp_path)
    got = D.apply(path, _file(tmp_path, REGN))
    stopped = D.retired(conn)
    conn.close()
    assert got["retired"] == 1
    assert stopped[1]["stopped_on"] == "2026-07-30"
    assert "10-Q" in stopped[1]["basis"]


def test_retirement_is_snapshotted_once_and_the_asset_is_kept(tmp_path):
    """Never overwrite history: the row, its trials and the record of the change stay."""
    path, conn = _db(tmp_path)
    source = _file(tmp_path, REGN)
    D.apply(path, source)
    D.apply(path, source)
    snaps = conn.execute("SELECT entity_key, payload FROM snapshots"
                         " WHERE source = 'discontinued_programmes'").fetchall()
    kept = conn.execute("SELECT COUNT(*) FROM assets WHERE id = 1").fetchone()[0]
    trials = conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = 1").fetchone()[0]
    conn.close()
    assert [s["entity_key"] for s in snaps] == ["REGN:REGN7999"], "a second run changes nothing"
    assert kept == 1 and trials == 1


def test_a_row_taken_out_of_the_file_brings_the_programme_back(tmp_path):
    path, conn = _db(tmp_path)
    D.apply(path, _file(tmp_path, REGN))
    got = D.apply(path, _file(tmp_path, ""))
    last = conn.execute("SELECT payload FROM snapshots WHERE source = 'discontinued_programmes'"
                        " ORDER BY id DESC LIMIT 1").fetchone()[0]
    conn.close()
    assert got["retired"] == 0
    assert '"retired": false' in last


def test_a_product_still_on_sale_is_refused_and_an_unknown_name_reported(tmp_path):
    """Withdrawal from sale is withdrawn_products.csv's job, not this file's."""
    path, conn = _db(tmp_path)
    got = D.apply(path, _file(tmp_path, "PFE,Beqvez,2025-02,withdrawn\n"
                                        "REGN,REGN0000,,no such asset\n"))
    conn.close()
    assert got == {"retired": 0, "unmatched": ["REGN REGN0000"], "marketed": ["PFE Beqvez"]}


def test_the_pipeline_views_and_the_coverage_count_skip_it(tmp_path):
    path, conn = _db(tmp_path)
    before = {r["ticker"]: r for r in pipeline.build_pipeline(path)}["REGN"]
    D.apply(path, _file(tmp_path, REGN))
    after = {r["ticker"]: r for r in pipeline.build_pipeline(path)}["REGN"]
    listed = [p["asset_id"] for p in pipeline.programmes(path, "REGN")]
    population = [r["asset_id"] for r in pipeline_sort.population(conn)]
    conn.close()
    assert before["compounds"]["Phase 3"] == 2 and after["compounds"]["Phase 3"] == 1
    assert after["phases"]["Phase 3"] == 1, "its recruiting trial is not a live study"
    assert listed == [2]
    assert population == [2]


def test_a_retired_programme_with_a_model_is_refused_with_the_reason(tmp_path, monkeypatch):
    """Worth nothing whatever its rows say, and named rather than silently dropped."""
    path, conn = _db(tmp_path)
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, key, value)"
                 " VALUES (1, 1, 'prevalence', 1.0)")
    conn.commit()
    conn.close()
    monkeypatch.setattr(V, "asset_forecast", lambda db_path, ticker, asset_id: {
        "ok": False, "name": "REGN7999", "missing": ["some input"]})
    D.apply(path, _file(tmp_path, REGN))
    got = V.company_rollup(path, "REGN")
    assert got["refused"] == [{"asset_id": 1, "name": "REGN7999", "missing": [
        "programme discontinued (2026-07-30): Regeneron's 10-Q filed 2026-07-30 states "
        "it has discontinued further clinical development of REGN7999"]}]


def test_a_retirement_does_not_follow_a_duplicate_onto_a_live_product(tmp_path):
    """The merge moves everything keyed to the row it folds. Rebuilt from the file, the
    retirement goes with the name it was written for, not with the trials."""
    path, conn = _db(tmp_path)
    source = _file(tmp_path, REGN)
    D.apply(path, source)
    asset_merge._absorb(conn, 2, 1)
    conn.commit()
    got = D.apply(path, source)
    stopped = D.retired(conn)
    conn.close()
    assert stopped == {} and got["unmatched"] == ["REGN REGN7999"]


def test_arm_pruning_deletes_the_row_rather_than_nulling_it(tmp_path):
    """prune_arms nulls any asset_id it reads as nullable, and an INTEGER PRIMARY KEY
    reads as nullable, where NULL assigns a fresh id: the retirement would have moved to
    whichever asset held it."""
    path, conn = _db(tmp_path)
    tables = dict(trial_mapping._arm_tables(conn))
    conn.close()
    assert tables["retired_programmes"] is False


def test_the_shipped_file_names_a_basis_and_a_real_date_for_every_row():
    rows = D.load()
    assert rows, "the register is empty"
    for row in rows:
        assert len(row["basis"]) > 40, row["name"]
        assert re.search(r"https?://|\d{10}-\d{2}-\d{6}", row["basis"]), row["name"]
        stated = row["stopped_on"]
        assert stated == "" or re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", stated), row["name"]


def test_every_row_is_a_dead_row_of_the_sort():
    """Seeded from the sort's DEAD rows; a row here the sort calls live is a conflict."""
    with open(pipeline_sort.SORT_CSV, newline="", encoding="utf-8") as handle:
        sort = {(r["ticker"], r["name"]): r["class"] for r in csv.DictReader(
            line for line in handle if not line.lstrip().startswith("#"))}
    for row in D.load():
        assert sort.get((row["ticker"], row["name"]), "DEAD") == "DEAD", row["name"]
