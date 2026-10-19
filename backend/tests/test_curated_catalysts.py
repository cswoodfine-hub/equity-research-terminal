"""Hand-entered catalysts live in the repo, so every book that runs the refresh has them."""

from __future__ import annotations

import csv

import applications
import curated_catalysts as C
import db

COLUMNS = ["ticker", "asset", "indication", "catalyst_type", "expected_date",
           "date_confidence", "title", "description", "source_url"]
ROW = {"ticker": "NVO", "asset": "Cagrilintide", "indication": "Obesity",
       "catalyst_type": "regulatory decision", "expected_date": "2026-12-31",
       "date_confidence": "quarter", "title": "CagriSema (cagrilintide) decision, obesity",
       "description": "Q4 2026 US decision, H1 2026 report.", "source_url": "https://sec.gov/x"}


def _book(tmp_path):
    path = str(tmp_path / "book.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'NVO', 'Novo Nordisk')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (7, 2, 'Cagrilintide', 0)")
    conn.execute("INSERT INTO indications (id, name) VALUES (3, 'Obesity')")
    conn.execute("INSERT INTO asset_indications (id, asset_id, indication_id, phase, is_lead,"
                 " region) VALUES (40, 7, 3, 'Phase 3', 1, 'US')")
    conn.commit()
    return conn


def _file(tmp_path, *rows):
    path = tmp_path / "curated.csv"
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _catalysts(conn):
    return [dict(r) for r in conn.execute(
        "SELECT asset_id, asset_indication_id, expected_date, date_confidence, title,"
        "       is_curated, status FROM catalysts")]


def test_a_book_without_the_row_gets_it_joined_to_its_asset_and_indication(tmp_path):
    conn = _book(tmp_path)
    got = C.load(conn, _file(tmp_path, ROW))
    assert got == {"written": 1, "updated": 0, "withdrawn": 0, "skipped": []}
    assert _catalysts(conn) == [{"asset_id": 7, "asset_indication_id": 40,
                                 "expected_date": "2026-12-31", "date_confidence": "quarter",
                                 "title": ROW["title"], "is_curated": 1, "status": "pending"}]
    assert C.load(conn, _file(tmp_path, ROW)) == {"written": 0, "updated": 0, "withdrawn": 0,
                                                  "skipped": []}


def test_a_pending_row_moves_with_the_file_and_a_resolved_one_does_not(tmp_path):
    conn = _book(tmp_path)
    C.load(conn, _file(tmp_path, ROW))
    dated = {**ROW, "expected_date": "2026-11-20", "date_confidence": "confirmed"}
    assert C.load(conn, _file(tmp_path, dated))["updated"] == 1
    assert _catalysts(conn)[0]["expected_date"] == "2026-11-20"
    conn.execute("UPDATE catalysts SET status = 'met'")
    assert C.load(conn, _file(tmp_path, ROW))["updated"] == 0
    assert _catalysts(conn)[0]["expected_date"] == "2026-11-20"


def test_an_asset_the_book_does_not_hold_is_skipped_and_said(tmp_path):
    conn = _book(tmp_path)
    got = C.load(conn, _file(tmp_path, {**ROW, "asset": "Amycretin"}))
    assert got["written"] == 0
    assert got["skipped"] == [{"title": ROW["title"], "why": "no single asset named Amycretin"}]


def test_the_link_survives_the_nightly_release(tmp_path):
    """The indication rebuild clears every catalyst's link each run and
    applications.resolve re-joins it from the title."""
    conn = _book(tmp_path)
    C.load(conn, _file(tmp_path, ROW))
    conn.execute("UPDATE catalysts SET asset_indication_id = NULL")
    applications.resolve(conn)
    assert _catalysts(conn)[0]["asset_indication_id"] == 40


def test_every_committed_title_names_its_product_and_indication():
    """A title resolve cannot parse loses its indication link overnight: 'FDA decision on
    the denecimig BLA, haemophilia A' read as product FDA and matched no indication.
    A readout is not a decision resolve reads, so it names its asset and study instead."""
    for row in C.rows():
        assert "—" not in row["description"] + row["title"]
        if row["catalyst_type"] == "data readout":
            assert row["asset"] and C.names_study(row), row["title"]
            continue
        product, indication = applications.parse_title(row["title"])
        assert product and indication, row["title"]
        if row["indication"]:
            assert applications._words(indication) & applications._words(row["indication"]), (
                row["title"])


def test_a_row_naming_no_asset_is_written_unjoined_for_resolve(tmp_path):
    """Intellia's lonvo-z PDUFA arrived before the book had an asset for it."""
    conn = _book(tmp_path)
    row = {**ROW, "asset": "", "indication": "", "catalyst_type": "PDUFA",
           "title": "Cagrilintide PDUFA, obesity"}
    assert C.load(conn, _file(tmp_path, row))["written"] == 1
    assert _catalysts(conn)[0]["asset_id"] is None
    applications.resolve(conn)
    got = _catalysts(conn)[0]
    assert (got["asset_id"], got["asset_indication_id"]) == (7, 40)


def test_a_restated_date_under_one_title_leaves_the_earlier_row_alone(tmp_path):
    """Capricor's deramiocel PDUFA was 22 August, then extended to 22 November under
    the same title: the November row is the file's, and August stays as filed."""
    conn = _book(tmp_path)
    for day in ("2026-08-22", "2026-11-22"):
        conn.execute("INSERT INTO catalysts (company_id, asset_id, catalyst_type,"
                     " expected_date, title, is_curated, status) VALUES"
                     " (2, 7, 'regulatory decision', ?, ?, 0, 'pending')", (day, ROW["title"]))
    got = C.load(conn, _file(tmp_path, {**ROW, "expected_date": "2026-11-22"}))
    assert got["written"] == 0
    assert sorted(r["expected_date"] for r in _catalysts(conn)) == ["2026-08-22", "2026-11-22"]


READOUT = {"ticker": "NVO", "asset": "Cagrilintide", "indication": "",
           "catalyst_type": "data readout", "expected_date": "2027-03-31",
           "date_confidence": "quarter",
           "title": "Cagrilintide registrational cohort topline, obesity",
           "description": "Topline in Q1 2027 from the cohort of NCT01234567.",
           "source_url": "https://sec.gov/x"}


def test_a_readout_the_registry_does_not_date_is_written_to_its_asset(tmp_path):
    """Dyne's ACHIEVE cohort reads out in Q1 2027 inside a study the registry dates to
    2029; the row keeps its asset through the nightly release of indication links."""
    conn = _book(tmp_path)
    assert C.load(conn, _file(tmp_path, READOUT)) == {"written": 1, "updated": 0,
                                                      "withdrawn": 0, "skipped": []}
    conn.execute("UPDATE catalysts SET asset_indication_id = NULL")
    applications.resolve(conn)
    got = conn.execute("SELECT asset_id, catalyst_type, description FROM catalysts"
                       ).fetchone()
    assert (got["asset_id"], got["catalyst_type"]) == (7, "data readout")
    assert "NCT01234567" in got["description"]


def test_a_readout_naming_no_study_or_no_asset_is_skipped_and_said(tmp_path):
    conn = _book(tmp_path)
    no_study = {**READOUT, "description": "Topline in Q1 2027."}
    no_asset = {**READOUT, "asset": ""}
    got = C.load(conn, _file(tmp_path, no_study, no_asset))
    assert got["written"] == 0
    assert [s["why"] for s in got["skipped"]] == ["a readout must name its asset and its study"] * 2


def _extracted(conn, day, title, asset_id=None):
    conn.execute("INSERT INTO catalysts (company_id, asset_id, catalyst_type, expected_date,"
                 " title, is_curated, status) VALUES (2, ?, 'PDUFA', ?, ?, 0, 'pending')",
                 (asset_id, day, title))


def test_a_decision_read_from_two_filings_ends_as_the_files_one_row(tmp_path):
    """Summit's ivonescimab PDUFA of 2026-11-14 was read from the January acceptance 8-K
    and again from the September AstraZeneca 8-K, two rows for one decision. The file's
    row adopts one, and the other machine-read copy of the same product and date goes."""
    conn = _book(tmp_path)
    row = {**ROW, "catalyst_type": "PDUFA", "expected_date": "2026-11-14",
           "date_confidence": "confirmed", "title": "Cagrilintide PDUFA, obesity"}
    _extracted(conn, "2026-11-14", "cagrilintide PDUFA, adults with obesity")
    _extracted(conn, "2026-11-14", row["title"], 7)
    _extracted(conn, "2026-12-01", "cagrilintide PDUFA, obesity in adolescents")
    got = C.load(conn, _file(tmp_path, row))
    assert (got["written"], got["withdrawn"]) == (0, 1)
    assert sorted((r["expected_date"], r["title"]) for r in _catalysts(conn)) == [
        ("2026-11-14", row["title"]),
        ("2026-12-01", "cagrilintide PDUFA, obesity in adolescents")]
    assert C.load(conn, _file(tmp_path, row))["withdrawn"] == 0


def test_a_copy_is_withdrawn_only_if_it_is_machine_read_pending_and_the_same_product(
        tmp_path):
    """A curated row, a resolved row and another product's decision on the same day are
    each a record of their own."""
    conn = _book(tmp_path)
    row = {**ROW, "catalyst_type": "PDUFA", "expected_date": "2026-11-14",
           "title": "Cagrilintide PDUFA, obesity"}
    _extracted(conn, "2026-11-14", "Semaglutide PDUFA, heart failure")
    _extracted(conn, "2026-11-14", "cagrilintide PDUFA, adults with obesity")
    conn.execute("UPDATE catalysts SET status = 'met' WHERE title LIKE 'cagri%'")
    conn.execute("INSERT INTO catalysts (company_id, catalyst_type, expected_date, title,"
                 " is_curated, status) VALUES (2, 'PDUFA', '2026-11-14',"
                 " 'Cagrilintide PDUFA, obesity (hand entered)', 1, 'pending')")
    got = C.load(conn, _file(tmp_path, row))
    assert (got["written"], got["withdrawn"]) == (1, 0)
    assert len(_catalysts(conn)) == 4
