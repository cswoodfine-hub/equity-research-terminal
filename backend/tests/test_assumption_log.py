"""The ledger of changes to the model's own inputs.

The rules under test are the governance ones: a number cannot move without the ledger
moving with it, a judgement cannot move without saying why, and a date reaches the value
that stood on it rather than the value that stands now.
"""

import pytest

import assumption_log as L
import assumptions as A
import db


def _seed(tmp_path):
    path = str(tmp_path / "a.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
                 " modality, is_marketed) VALUES"
                 " (1, 1, 'Verzenio', 'Abemaciclib', 'small molecule', 1)")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Prostatic Neoplasms')")
    conn.commit()
    return path, conn


def _edits(conn, **where):
    sql = "SELECT * FROM assumption_edits"
    if where:
        sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
    sql += " ORDER BY id"
    return [dict(r) for r in conn.execute(sql, tuple(where.values()))]


# --- the ledger records every write ------------------------------------------

def test_a_new_row_is_recorded_as_a_create(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    conn.commit()
    rows = _edits(conn)
    assert len(rows) == 1
    assert rows[0]["op"] == "create"
    assert rows[0]["old_value"] is None
    assert rows[0]["new_value"] == 0.25
    assert rows[0]["new_evidence"] == "judgement"
    conn.close()


def test_an_update_keeps_the_value_it_replaced(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "indication_id": 1,
                      "source": "CYCLONE 3 met its primary endpoint"}],
           reason="readout", trigger_ref="NCT05288166")
    conn.commit()
    update = _edits(conn, op="update")[0]
    assert update["old_value"] == 0.25
    assert update["new_value"] == 0.92
    assert update["reason"] == "readout"
    assert update["trigger_ref"] == "NCT05288166"
    # The table itself still holds one row: the ledger is beside it, not instead of it.
    assert len(A.rows(conn, 1)) == 1
    conn.close()


def test_a_delete_is_recorded_with_nothing_after_it(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "the 10-K"}])
    A.save(conn, 1, [{"key": "sga_pct", "value": None}])
    conn.commit()
    deleted = _edits(conn, op="delete")[0]
    assert deleted["old_value"] == 0.2
    assert deleted["new_value"] is None
    assert A.rows(conn, 1) == []
    conn.close()


def test_one_save_is_one_batch(tmp_path):
    path, conn = _seed(tmp_path)
    batch = L.new_batch()
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "the 10-K"},
                     {"key": "cogs_pct", "value": 0.21, "source": "the 10-K"}],
           batch_id=batch)
    conn.commit()
    rows = _edits(conn)
    assert {r["batch_id"] for r in rows} == {batch}
    conn.close()


def test_the_ledger_names_who_changed_it(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "the 10-K"}],
           changed_by="charles@fairmilepartners.co.uk")
    conn.commit()
    assert _edits(conn)[0]["changed_by"] == "charles@fairmilepartners.co.uk"
    conn.close()


# --- a judgement cannot move without saying why ------------------------------

def test_moving_a_judgement_without_a_reason_is_refused(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    with pytest.raises(L.ReasonRequired):
        A.save(conn, 1, [{"key": "pos", "value": 0.92, "indication_id": 1,
                          "source": "a judgement"}])
    conn.close()


def test_moving_a_convention_without_a_reason_is_refused(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "terminal_growth_pct", "value": 0.02,
                      "source": "the engine's terminal value convention"}])
    with pytest.raises(L.ReasonRequired):
        A.save(conn, 1, [{"key": "terminal_growth_pct", "value": 0.015,
                          "source": "the engine's terminal value convention"}])
    conn.close()


def test_removing_a_judgement_without_a_reason_is_refused(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    with pytest.raises(L.ReasonRequired):
        A.save(conn, 1, [{"key": "pos", "value": None, "indication_id": 1}])
    conn.close()


def test_a_number_the_filing_states_needs_no_reason(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "base_revenue", "value": 5723.0,
                      "source": "LLY FY2025 reported product revenue, the 10-K"}])
    A.save(conn, 1, [{"key": "base_revenue", "value": 5810.0,
                      "source": "LLY FY2026 reported product revenue, the 10-K"}])
    conn.commit()
    assert A.rows(conn, 1)[0]["value"] == 5810.0
    conn.close()


def test_restating_the_note_alone_is_not_a_move(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement", "note": "the row to argue with"}])
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement", "note": "argue with this one"}])
    conn.commit()
    assert A.rows(conn, 1)[0]["note"] == "argue with this one"
    conn.close()


def test_a_reason_outside_the_vocabulary_is_refused(tmp_path):
    path, conn = _seed(tmp_path)
    with pytest.raises(ValueError):
        A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}],
               reason="felt right")
    conn.close()


def test_every_reason_in_the_vocabulary_is_accepted(tmp_path):
    path, conn = _seed(tmp_path)
    for n, reason in enumerate(L.REASONS):
        A.save(conn, 1, [{"key": f"pos_{n}", "value": 0.5, "source": "a judgement"}],
               reason=reason)
    conn.commit()
    assert {r["reason"] for r in _edits(conn)} == set(L.REASONS)
    conn.close()


# --- a review lapses when what was reviewed has moved ------------------------

def test_a_confirmed_grade_lapses_when_the_number_and_the_source_both_move(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement", "evidence": "judgement"}])
    assert A.rows(conn, 1)[0]["evidence_reviewed"] == 1
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "indication_id": 1,
                      "source": "CYCLONE 3 met its primary endpoint"}],
           reason="readout")
    conn.commit()
    row = A.rows(conn, 1)[0]
    assert row["evidence_reviewed"] == 0, "the confirmation was of the row as it was"
    conn.close()


def test_a_confirmed_grade_holds_when_only_the_note_moves(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "list_price_per_patient", "value": 1200.0,
                      "source": "WAC Disclosure", "evidence": "filed"}])
    A.save(conn, 1, [{"key": "list_price_per_patient", "value": 1200.0,
                      "source": "WAC Disclosure", "note": "monthly"}])
    conn.commit()
    row = A.rows(conn, 1)[0]
    assert row["evidence"] == "filed" and row["evidence_reviewed"] == 1
    conn.close()


def test_a_stated_grade_is_kept_and_marked_reviewed(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "prevalence", "value": 313780, "indication_id": 1,
                      "source": "a judgement", "evidence": "published"}],
           reason="epidemiology_update")
    conn.commit()
    row = A.rows(conn, 1)[0]
    assert row["evidence"] == "published" and row["evidence_reviewed"] == 1
    conn.close()


# --- reading a date ----------------------------------------------------------

def test_a_date_reaches_the_number_that_stood_on_it(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    # The clock has one-second grain, so the first edit is dated by hand rather than by
    # waiting: the query is what is under test, not the clock.
    conn.execute("UPDATE assumption_edits SET changed_at = '2026-09-01 09:00:00'")
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "indication_id": 1,
                      "source": "CYCLONE 3 met its primary endpoint"}],
           reason="readout")
    conn.execute("UPDATE assumption_edits SET changed_at = '2026-11-14 09:00:00'"
                 " WHERE op = 'update'")
    conn.commit()
    then = L.value_at(conn, 1, "pos", "2026-10-01", indication_id=1)
    now = L.value_at(conn, 1, "pos", "2026-12-01", indication_id=1)
    assert then["value"] == 0.25
    assert now["value"] == 0.92 and now["reason"] == "readout"
    conn.close()


def test_a_date_before_the_ledger_has_no_state_to_give(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    conn.commit()
    assert L.value_at(conn, 1, "pos", "2020-01-01", indication_id=1) is None
    conn.close()


def test_a_removed_row_reads_as_gone_rather_than_as_its_last_value(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "the 10-K"}])
    A.save(conn, 1, [{"key": "sga_pct", "value": None}])
    conn.commit()
    assert L.value_at(conn, 1, "sga_pct", "2099-01-01") is None
    conn.close()


# --- the changelog -----------------------------------------------------------

def test_the_log_reads_newest_first_and_names_the_indication(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "indication_id": 1,
                      "source": "CYCLONE 3 met its primary endpoint"}],
           reason="readout")
    conn.commit()
    entries = L.log(conn, asset_id=1)
    assert entries[0]["op"] == "update" and entries[-1]["op"] == "create"
    assert entries[0]["indication"] == "Prostatic Neoplasms"
    assert entries[0]["brand_name"] == "Verzenio"
    conn.close()


def test_the_log_narrows_to_one_reason(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"}])
    A.save(conn, 1, [{"key": "pos", "value": 0.92, "source": "a judgement"}],
           reason="readout")
    conn.commit()
    assert len(L.log(conn, asset_id=1, reason="readout")) == 1
    conn.close()


def test_the_review_queue_holds_the_unconfirmed_judgements(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"},
                     {"key": "base_revenue", "value": 5723.0, "source": "the 10-K"}])
    conn.commit()
    queue = L.unreviewed_judgements(conn, asset_id=1)
    assert [r["key"] for r in queue] == ["pos"]
    conn.close()


def test_the_classes_count_what_the_model_rests_on(tmp_path):
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "source": "a judgement"},
                     {"key": "base_revenue", "value": 5723.0, "source": "the 10-K"},
                     {"key": "list_price_per_patient", "value": 1.0,
                      "source": "reused from another seed"}])
    conn.commit()
    got = L.classes(conn, 1)
    assert got == {"evidence": 1, "partial evidence": 1, "assumption": 1}
    conn.close()


# --- the seed loader -----------------------------------------------------------

def test_the_seed_loader_names_its_own_writes(tmp_path):
    path, conn = _seed(tmp_path)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "lly_verzenio.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,"
        "source,note\n"
        "LLY,Verzenio,,US,base,base_revenue,,5723.0,,mm USD,the 10-K,the anchor\n")
    A.load_seeds(conn, directory=str(seeds))
    rows = _edits(conn)
    assert len(rows) == 1
    assert rows[0]["reason"] == "initial_seed" and rows[0]["op"] == "create"
    conn.close()


def test_a_bare_date_means_the_close_of_that_day(tmp_path):
    """Timestamps compare as text, so a date asked for without a time would sort below
    every edit made during it and report the day before."""
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "pos", "value": 0.25, "indication_id": 1,
                      "source": "a judgement"}])
    conn.execute("UPDATE assumption_edits SET changed_at = '2026-10-24 13:24:46'")
    conn.commit()
    assert L.value_at(conn, 1, "pos", "2026-10-24", indication_id=1)["value"] == 0.25
    assert L.value_at(conn, 1, "pos", "2026-10-23", indication_id=1) is None
    conn.close()


def test_the_log_narrows_to_one_company(tmp_path):
    path, conn = _seed(tmp_path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'AMGN', 'Amgen')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, modality,"
                 " is_marketed) VALUES (2, 2, 'Repatha', 'biologic', 1)")
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "the 10-K"}])
    A.save(conn, 2, [{"key": "sga_pct", "value": 0.3, "source": "the 10-K"}])
    conn.commit()
    assert [r["brand_name"] for r in L.log(conn, ticker="LLY")] == ["Verzenio"]
    assert [r["ticker"] for r in L.log(conn, ticker="AMGN")] == ["AMGN"]
    conn.close()


def test_a_reseed_does_not_log_a_row_s_first_write_twice(tmp_path):
    """history.py rebuild restores the ledger but not the assumptions table, so the seed
    loader finds it empty and writes every row again. The cloud book went from 11,575
    ledger rows to 23,150 in one run before this was caught (090)."""
    path, conn = _seed(tmp_path)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "lly_verzenio.csv").write_text(
        "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,"
        "source,note\n"
        "LLY,Verzenio,,US,base,base_revenue,,5723.0,,mm USD,the 10-K,the anchor\n")
    A.load_seeds(conn, directory=str(seeds))
    conn.execute("DELETE FROM assumptions")          # what a rebuild leaves behind
    conn.commit()
    A.load_seeds(conn, directory=str(seeds))
    rows = _edits(conn, reason="initial_seed")
    assert len(rows) == 1, "one row, one first write, however many rebuilds"
    conn.close()


def test_an_analyst_may_create_delete_and_create_again(tmp_path):
    """Three events, not one. The seed index must not collapse real history."""
    path, conn = _seed(tmp_path)
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.2, "source": "the 10-K"}])
    A.save(conn, 1, [{"key": "sga_pct", "value": None}])
    A.save(conn, 1, [{"key": "sga_pct", "value": 0.25, "source": "the 10-K"}])
    conn.commit()
    assert [r["op"] for r in _edits(conn)] == ["create", "delete", "create"]
    conn.close()
