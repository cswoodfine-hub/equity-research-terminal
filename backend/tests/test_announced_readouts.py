"""An announced result the book did not read is entered by hand and closes its study."""

from __future__ import annotations

import csv
import datetime as dt

import announced_readouts as A
import catalyst_outcomes as CO
import db

TODAY = dt.date(2026, 11, 22)
COLUMNS = ["ticker", "asset", "nct_id", "outcome", "event_date", "quote", "source_url"]
ROW = {"ticker": "CAPR", "asset": "Deramiocel (CAP-1002)", "nct_id": "NCT00000001",
       "outcome": "met", "event_date": "2025-12-03",
       "quote": "The trial met its primary endpoint.", "source_url": "https://sec.gov/x"}


def _book(tmp_path):
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'CAPR', 'Capricor')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'NVO', 'Novo Nordisk')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (10, 1, 'Deramiocel (CAP-1002)', 0)")
    conn.commit()
    return path, conn


def _readout(conn, cid, nct, status="unknown", company_id=1, due="2025-06-18"):
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type, expected_date,"
                 " date_confidence, title, description, is_curated, status)"
                 " VALUES (?, ?, 10, 'data readout', ?, 'estimated', 'Phase 3, a study', ?, 0, ?)",
                 (cid, company_id, due, nct, status))
    conn.commit()


def _file(tmp_path, *rows):
    path = tmp_path / "announced.csv"
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_a_result_announced_outside_the_window_closes_its_study_on_the_announcement_day(tmp_path):
    """Capricor's HOPE-3 completed in June 2025 and its topline came in December, past
    the 45 days the resolver waits, so the row closed unknown with the result on file."""
    path, conn = _book(tmp_path)
    _readout(conn, 1, "NCT00000001", "unknown")
    _readout(conn, 2, "NCT00000002", "pending")
    got = A.load(conn, _file(tmp_path, ROW), today=TODAY)
    assert got == {"resolved": 1, "held": 0, "skipped": []}
    row = conn.execute("SELECT status, updated_at FROM catalysts WHERE id = 1").fetchone()
    assert (row["status"], row["updated_at"]) == ("met", "2025-12-03")
    assert conn.execute("SELECT status FROM catalysts WHERE id = 2").fetchone()[0] == "pending"
    led = conn.execute("SELECT outcome, event_date, source, automated, evidence"
                       " FROM catalyst_resolutions").fetchall()
    assert [(r["outcome"], r["event_date"], r["source"], r["automated"]) for r in led] == [
        ("met", "2025-12-03", "hand", 0)]
    assert ROW["quote"] in led[0]["evidence"] and ROW["source_url"] in led[0]["evidence"]


def test_a_second_load_writes_nothing_and_the_resolver_leaves_the_row_alone(tmp_path):
    path, conn = _book(tmp_path)
    _readout(conn, 1, "NCT00000001", "pending")
    file = _file(tmp_path, ROW)
    A.load(conn, file, today=TODAY)
    conn.commit()
    assert A.load(conn, file, today=TODAY) == {"resolved": 0, "held": 1, "skipped": []}
    conn.commit()
    CO.resolve(path, today=TODAY, fetch=False)
    assert conn.execute("SELECT status, updated_at FROM catalysts WHERE id = 1"
                        ).fetchone()[:] == ("met", "2025-12-03")
    assert conn.execute("SELECT COUNT(*) FROM catalyst_resolutions").fetchone()[0] == 1


def test_a_result_the_book_already_holds_the_other_way_is_left_and_said(tmp_path):
    """A resolution on file is the book's own: the file never overturns one."""
    path, conn = _book(tmp_path)
    _readout(conn, 1, "NCT00000001", "missed")
    got = A.load(conn, _file(tmp_path, ROW), today=TODAY)
    assert got["resolved"] == 0
    assert got["skipped"] == [{"nct_id": "NCT00000001",
                               "why": "the book already holds NCT00000001 as missed"}]
    assert conn.execute("SELECT status FROM catalysts WHERE id = 1").fetchone()[0] == "missed"


def test_a_row_without_its_sentence_its_source_or_its_study_is_skipped_and_said(tmp_path):
    path, conn = _book(tmp_path)
    _readout(conn, 1, "NCT00000001", "unknown")
    _readout(conn, 3, "NCT00000003", "unknown", company_id=2)
    bad = [{**ROW, "quote": ""}, {**ROW, "source_url": ""}, {**ROW, "nct_id": "HOPE-3"},
           {**ROW, "outcome": "mixed"}, {**ROW, "event_date": "2026-12"},
           {**ROW, "event_date": "2026-12-01"}, {**ROW, "nct_id": "NCT00000009"},
           {**ROW, "nct_id": "NCT00000003"}, {**ROW, "ticker": "ZZZ"}]
    got = A.load(conn, _file(tmp_path, *bad), today=TODAY)
    assert got["resolved"] == 0
    assert [s["why"] for s in got["skipped"]] == [
        "a result must carry the sentence that states it and its source",
        "a result must carry the sentence that states it and its source",
        "a result must name its study by registry number",
        "the outcome must be met or missed",
        "the announcement must carry its day",
        "the announcement is dated ahead of today",
        "no readout on the calendar for NCT00000009",
        "the readout for NCT00000003 is not CAPR's",
        "no company ZZZ"]
    assert conn.execute("SELECT COUNT(*) FROM catalyst_resolutions").fetchone()[0] == 0


def test_every_committed_row_is_a_sourced_result_and_names_its_study_once():
    seen = set()
    for row in A.rows():
        assert A.problem(row) is None, row
        assert row["ticker"] and row["asset"], row
        assert "—" not in row["quote"], row
        assert row["nct_id"] not in seen, row["nct_id"]
        seen.add(row["nct_id"])
