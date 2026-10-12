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
    assert got == {"written": 1, "updated": 0, "skipped": []}
    assert _catalysts(conn) == [{"asset_id": 7, "asset_indication_id": 40,
                                 "expected_date": "2026-12-31", "date_confidence": "quarter",
                                 "title": ROW["title"], "is_curated": 1, "status": "pending"}]
    assert C.load(conn, _file(tmp_path, ROW)) == {"written": 0, "updated": 0, "skipped": []}


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
    the denecimig BLA, haemophilia A' read as product FDA and matched no indication."""
    for row in C.rows():
        product, indication = applications.parse_title(row["title"])
        assert product and indication, row["title"]
        if row["indication"]:
            assert applications._words(indication) & applications._words(row["indication"]), (
                row["title"])
        assert "—" not in row["description"] + row["title"]
