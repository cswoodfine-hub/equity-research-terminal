"""A balance sheet the filer has published that EDGAR's structured data does not carry."""

import pytest

import balance_updates
import db

HEADER = "ticker,period_end,metric,value_musd,unit,accession,caption,quote\n"


def _file(tmp_path, body):
    path = tmp_path / "updates.csv"
    path.write_text("# a comment\n" + HEADER + body, encoding="utf-8")
    return path


def _db(tmp_path):
    path = str(tmp_path / "b.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'BIIB', 'Biogen')")
    conn.commit()
    return conn


def test_a_published_line_is_written_in_units(tmp_path):
    conn = _db(tmp_path)
    path = _file(tmp_path, "BIIB,2026-06-30,TotalDebt,8090.3,USD,0000875045-26-000075,Total borrowings,\"quote\"\n")
    assert balance_updates.load(conn, path) == {"written": 1, "skipped": 0}
    row = conn.execute("SELECT * FROM financials WHERE metric = 'TotalDebt'").fetchone()
    assert row["value"] == pytest.approx(8090.3e6)
    assert (row["period_type"], row["fiscal_year"], row["source"]) == ("instant", 2026, "filing")
    assert row["accession"] == "0000875045-26-000075"
    conn.close()


def test_the_filers_own_tagged_data_is_never_overwritten(tmp_path):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO financials (company_id, period_end, period_type, metric, value,"
                 " unit, fiscal_year, source) VALUES (1, '2026-06-30', 'instant', 'TotalDebt',"
                 " 1.0, 'USD', 2026, 'edgar_companyfacts')")
    conn.commit()
    path = _file(tmp_path, "BIIB,2026-06-30,TotalDebt,8090.3,USD,0000875045-26-000075,Total borrowings,\"quote\"\n")
    assert balance_updates.load(conn, path) == {"written": 0, "skipped": 1}
    assert conn.execute("SELECT value FROM financials").fetchone()["value"] == 1.0
    conn.close()


def test_an_unknown_ticker_and_an_empty_row_are_skipped(tmp_path):
    conn = _db(tmp_path)
    path = _file(tmp_path, "ZZZZ,2026-06-30,TotalDebt,1.0,USD,acc,cap,q\n"
                           "BIIB,2026-06-30,TotalDebt,,USD,acc,cap,q\n")
    assert balance_updates.load(conn, path) == {"written": 0, "skipped": 1}
    assert conn.execute("SELECT COUNT(*) FROM financials").fetchone()[0] == 0
    conn.close()


def test_no_file_is_no_rows(tmp_path):
    assert balance_updates.rows(tmp_path / "missing.csv") == []
