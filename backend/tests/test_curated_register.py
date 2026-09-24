"""The analyst's corrections to the marketed register: additions and withdrawals."""

import csv

import curated_register as R
import db


def _write(path, header, rows):
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def _db(tmp_path):
    path = str(tmp_path / "reg.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.executescript("""
        INSERT INTO companies (id, ticker, name) VALUES (1, 'ABBV', 'AbbVie'), (2, 'PFE', 'Pfizer');
        INSERT INTO assets (id, owner_company_id, brand_name, internal_code, is_marketed)
        VALUES (10, 2, 'BEQVEZ', 'BLA125786', 1);
    """)
    conn.commit()
    conn.close()
    return path


def _files(tmp_path):
    adds = _write(tmp_path / "adds.csv",
                  ["ticker", "brand", "generic", "internal_code", "modality", "licensed_on", "source"],
                  [["ABBV", "Elahere", "mirvetuximab soravtansine-gynx", "BLA761310", "biologic",
                    "2022-11-14", "FDA approval letter"]])
    gone = _write(tmp_path / "gone.csv",
                  ["ticker", "brand", "internal_code", "withdrawn_on", "source"],
                  [["PFE", "BEQVEZ", "BLA125786", "2025-02", "Pfizer statement"]])
    return adds, gone


def test_an_addition_is_marketed_with_its_statutory_floor(tmp_path):
    path = _db(tmp_path)
    adds, gone = _files(tmp_path)
    got = R.apply(path, adds, gone)
    conn = db.get_connection(path)
    row = conn.execute("SELECT a.is_marketed, e.expiry_date, e.source FROM assets a"
                       " JOIN exclusivities e ON e.asset_id = a.id"
                       " WHERE a.internal_code = 'BLA761310'").fetchone()
    conn.close()
    assert got == {"added": 1, "retired": 1}
    assert row["is_marketed"] == 1
    assert row["expiry_date"] == "2034-11-14" and row["source"] == "curated_register"


def test_a_withdrawn_product_is_unmarketed_and_the_change_is_snapshotted(tmp_path):
    path = _db(tmp_path)
    adds, gone = _files(tmp_path)
    R.apply(path, adds, gone)
    conn = db.get_connection(path)
    marketed = conn.execute("SELECT is_marketed FROM assets WHERE id = 10").fetchone()[0]
    snaps = conn.execute("SELECT COUNT(*) FROM snapshots WHERE source = 'curated_register'"
                         " AND entity_key = 'BLA125786'").fetchone()[0]
    conn.close()
    assert marketed == 0 and snaps == 1


def test_a_second_run_changes_nothing(tmp_path):
    path = _db(tmp_path)
    adds, gone = _files(tmp_path)
    R.apply(path, adds, gone)
    assert R.apply(path, adds, gone) == {"added": 0, "retired": 0}
    conn = db.get_connection(path)
    floors = conn.execute("SELECT COUNT(*) FROM exclusivities").fetchone()[0]
    conn.close()
    assert floors == 1


def test_the_committed_files_cite_a_source_on_every_row():
    for path in (R.ADDITIONS, R.WITHDRAWN):
        rows = R._rows(path)
        assert rows, path
        assert all(r["source"].strip() for r in rows), path
