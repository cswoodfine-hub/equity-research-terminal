"""CMS removing a drug from price negotiation, read as a dated loss of exclusivity."""

from __future__ import annotations

import csv

import pytest

import db
import loe


@pytest.fixture(autouse=True)
def _no_real_curated_files(tmp_path, monkeypatch):
    """These fixtures reuse real brand names, so each test starts with no curated file
    but the one it writes."""
    monkeypatch.setattr(loe, "CURATED_DISCLOSED", tmp_path / "none.csv")
    monkeypatch.setattr(loe, "CMS_DESELECTIONS", tmp_path / "none-cms.csv")


def _db(tmp_path):
    path = str(tmp_path / "desel.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'JNJ', 'J&J'),"
                 " (2, 'NVO', 'Novo Nordisk')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (10, 1, 'Xarelto', 1), (11, 2, 'Fiasp', 1),"
                 "        (12, 1, 'Stelara', 1), (13, 1, 'Tremfya', 1)")
    conn.execute("INSERT INTO exclusivities (asset_id, region, protection_type,"
                 " identifier, expiry_date, patent_kind, source) VALUES"
                 " (10, 'US', 'patent', '1', '2034-08-17', 'substance', 't'),"
                 " (13, 'US', 'patent', '3', '2031-01-01', 'substance', 't')")
    conn.commit()
    return conn


def _write(monkeypatch, tmp_path, body: str):
    path = tmp_path / "cms.csv"
    path.write_text("# a comment line\nticker,brand,determination,removal,note\n" + body)
    monkeypatch.setattr(loe, "CMS_DESELECTIONS", path)


def test_a_deselection_dates_a_loss_the_patent_listing_put_years_later(tmp_path,
                                                                      monkeypatch):
    """The Orange Book ran Xarelto to 2034; CMS found generics marketed in October 2025,
    and the payer's finding is the date."""
    conn = _db(tmp_path)
    _write(monkeypatch, tmp_path, "JNJ,Xarelto,2025-10,2027-01-01,generics marketed\n")
    got = loe.for_assets(conn, [10])
    assert got[10]["date"] == "2025-10-31"
    assert got[10]["basis"] == ("CMS deselection, generic or biosimilar marketed "
                                "(2025-10)")
    assert got[10]["past"] is True


def test_a_deselection_dates_a_product_that_had_no_date_at_all(tmp_path, monkeypatch):
    """Novo's insulin aspart franchise carried no end date and ran into a perpetuity."""
    conn = _db(tmp_path)
    _write(monkeypatch, tmp_path, "NVO,Fiasp,2026-03,2027-01-01,biosimilar marketed\n")
    assert loe.for_assets(conn, [11]).get(11, {}).get("date") == "2026-03-31"


def test_a_deselection_never_pushes_a_date_later(tmp_path, monkeypatch):
    """A determination that lands after the date the model already holds changes
    nothing: a deselection proves the market opened by then, not that it stayed shut
    until then."""
    conn = _db(tmp_path)
    _write(monkeypatch, tmp_path, "JNJ,Tremfya,2033-06,2035-01-01,hypothetical\n")
    assert loe.for_assets(conn, [13])[13]["date"] == "2031-01-01"


def test_a_loss_already_known_past_with_no_date_is_left_alone(tmp_path, monkeypatch):
    """J&J says Stelara's biosimilars are already on its market without saying since
    when. That is carried as a past loss with no year, and a deselection month does not
    invent one over it."""
    conn = _db(tmp_path)
    disclosed = tmp_path / "d.csv"
    disclosed.write_text("ticker,brand,loe,basis,note\n"
                         "JNJ,Stelara,expired,J&J 10-K biosimilar competition,\n")
    monkeypatch.setattr(loe, "CURATED_DISCLOSED", disclosed)
    _write(monkeypatch, tmp_path, "JNJ,Stelara,2025-10,2027-01-01,biosimilars marketed\n")
    got = loe.for_assets(conn, [12])[12]
    assert got["date"] is None and got["past"] is True
    assert "10-K" in got["basis"]


def test_a_brand_no_company_in_the_book_holds_is_skipped(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    _write(monkeypatch, tmp_path,
           "JNJ,Xarelto,2025-10,2027-01-01,held\nPFE,Xeljanz,2026-06,2029-01-01,not held\n")
    assert set(loe.cms_deselections(conn)) == {10}


def _listed():
    """The committed file's rows, read the way cms_deselections reads them."""
    with loe.CMS_DESELECTIONS.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(
            [line for line in handle if not line.lstrip().startswith("#")]))


def test_the_real_file_reads_and_every_row_names_a_month(tmp_path, monkeypatch):
    """The committed file parses, and each determination is a month CMS published.
    The database holds the file's own brands, so every row has an asset to land on."""
    monkeypatch.undo()
    listed = _listed()
    assert listed, "the curated CMS deselection file has no rows"
    path = str(tmp_path / "real.db")
    db.init(path)
    conn = db.get_connection(path)
    tickers = sorted({r["ticker"].strip().upper() for r in listed})
    for company_id, ticker in enumerate(tickers, 1):
        conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                     (company_id, ticker, ticker))
    for row in listed:
        owner = tickers.index(row["ticker"].strip().upper()) + 1
        conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                     " VALUES (?, ?, 1)", (owner, row["brand"].strip()))
    conn.commit()
    rows = loe.cms_deselections(conn)
    conn.close()
    assert len(rows) == len(listed), "a row in the curated CMS file did not parse"
    for found in rows.values():
        assert len(found["stated"]) == 7 and found["date"].endswith(("-31", "-30", "-28"))
        assert found["basis"].startswith("CMS deselection")
