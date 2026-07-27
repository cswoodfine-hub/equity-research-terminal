"""Folding a derived compound into the marketed product it turns out to be."""

import asset_merge
import db
from fetchers.approvals_openfda import parse_drugsfda


def _seed(tmp_path):
    path = str(tmp_path / "merge.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('MRK', 'Merck')")
    conn.commit()
    return path, conn


def _asset(conn, ticker, brand=None, generic=None, marketed=0, code=None):
    cid = conn.execute("SELECT id FROM companies WHERE ticker = ?",
                       (ticker,)).fetchone()["id"]
    cur = conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, generic_name,"
        "                    internal_code, is_marketed) VALUES (?, ?, ?, ?, ?)",
        (cid, brand, generic, code, marketed))
    conn.commit()
    return cur.lastrowid


def _trial(conn, asset_id, nct):
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, phase)"
                 " VALUES (?, ?, 'A study', 'Phase 4')", (nct, asset_id))
    conn.commit()


def test_reads_the_generic_name_off_the_payload():
    payload = {"results": [{
        "application_number": "NDA216059",
        "products": [{"brand_name": "JAYPIRCA", "marketing_status": "Prescription",
                      "active_ingredients": [{"name": "PIRTOBRUTINIB",
                                              "strength": "50MG"}]}],
        "submissions": [{"submission_type": "ORIG", "submission_status": "AP",
                         "submission_status_date": "20230127"}],
    }]}
    row = parse_drugsfda(payload, "LLY")[0]
    assert row["brand"] == "Jaypirca"
    assert row["generic"] == "Pirtobrutinib"


def test_falls_back_to_the_openfda_block():
    payload = {"results": [{
        "application_number": "BLA125469",
        "openfda": {"generic_name": ["DULAGLUTIDE"]},
        "products": [{"brand_name": "TRULICITY"}],
        "submissions": [{"submission_type": "ORIG", "submission_status": "AP",
                         "submission_status_date": "20140918"}],
    }]}
    assert parse_drugsfda(payload, "LLY")[0]["generic"] == "Dulaglutide"


def test_states_no_generic_when_the_payload_gives_none():
    payload = {"results": [{
        "application_number": "NDA000001",
        "products": [{"brand_name": "SOMETHING"}],
        "submissions": [{"submission_type": "ORIG", "submission_status": "AP",
                         "submission_status_date": "20200101"}],
    }]}
    assert parse_drugsfda(payload, "LLY")[0]["generic"] is None


def test_merges_the_derived_row_into_the_marketed_one(tmp_path):
    path, conn = _seed(tmp_path)
    marketed = _asset(conn, "LLY", brand="Jaypirca", generic="Pirtobrutinib",
                      marketed=1, code="NDA216059")
    derived = _asset(conn, "LLY", generic="Pirtobrutinib")
    _trial(conn, derived, "NCT0001")
    _trial(conn, derived, "NCT0002")
    conn.close()

    assert asset_merge.merge(path) == {"merged": 1, "trials_moved": 2}

    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM assets WHERE id = ?",
                        (derived,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM trials WHERE asset_id = ?",
                        (marketed,)).fetchone()[0] == 2
    conn.close()

    # A second run has nothing left to do.
    assert asset_merge.merge(path) == {"merged": 0, "trials_moved": 0}


def test_never_merges_across_companies(tmp_path):
    path, conn = _seed(tmp_path)
    _asset(conn, "MRK", brand="Keytruda", generic="Pembrolizumab", marketed=1)
    derived = _asset(conn, "LLY", generic="Pembrolizumab")
    _trial(conn, derived, "NCT0003")
    conn.close()

    # Two firms can name the same molecule; a merge across owners would invent a
    # relationship the data does not state.
    assert asset_merge.merge(path)["merged"] == 0


def test_leaves_an_ambiguous_name_alone(tmp_path):
    path, conn = _seed(tmp_path)
    _asset(conn, "LLY", brand="Brand one", generic="Shared", marketed=1)
    _asset(conn, "LLY", brand="Brand two", generic="Shared", marketed=1)
    derived = _asset(conn, "LLY", generic="Shared")
    _trial(conn, derived, "NCT0004")
    conn.close()

    # A name held by two marketed rows identifies neither.
    assert asset_merge.merge(path)["merged"] == 0


def test_moves_the_rows_that_hang_off_the_derived_asset(tmp_path):
    path, conn = _seed(tmp_path)
    marketed = _asset(conn, "LLY", brand="Jaypirca", generic="Pirtobrutinib",
                      marketed=1)
    derived = _asset(conn, "LLY", generic="Pirtobrutinib")
    _trial(conn, derived, "NCT0005")
    conn.execute("INSERT INTO product_notes (asset_id, thesis) VALUES (?, 'mine')",
                 (derived,))
    conn.execute("INSERT INTO trial_asset_map (nct_id, asset_id) VALUES ('NCT0005', ?)",
                 (derived,))
    conn.commit()
    conn.close()

    assert asset_merge.merge(path)["merged"] == 1

    conn = db.get_connection(path)
    note = conn.execute("SELECT asset_id, thesis FROM product_notes").fetchone()
    mapped = conn.execute("SELECT asset_id FROM trial_asset_map").fetchone()
    conn.close()
    assert note["asset_id"] == marketed and note["thesis"] == "mine"
    assert mapped["asset_id"] == marketed
