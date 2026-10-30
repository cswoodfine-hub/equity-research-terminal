"""Orange Book patent use codes: parsing FDA's patent page (a saved copy of NDA202293,
Farxiga), choosing which pages to read, and storing a definition once. No network."""

from __future__ import annotations

from pathlib import Path

import db
import use_codes
from fetchers.use_codes_ob import UseCodesFetcher, needed

PAGE = Path(__file__).parent / "fixtures" / "ob_patent_info_nda202293.html"


def test_the_page_gives_each_code_its_wording():
    got = use_codes.parse(PAGE.read_text())
    assert got["U-493"] == "TREATMENT OF TYPE 2 DIABETES MELLITUS"
    assert got["U-2139"] == ("TREATMENT OF TYPE 2 DIABETES MELLITUS IN COMBINATION WITH "
                             "EXENATIDE")
    # The paediatric extension rows carry empty tooltips, which are no definition.
    assert all(text for text in got.values())
    assert use_codes.parse("") == {}


def test_the_page_url_takes_the_book_s_application_shape():
    assert use_codes.page_url("NDA202293").endswith(
        "Product_No=001&Appl_No=202293&Appl_type=N")
    assert use_codes.page_url("ANDA090001").endswith("Appl_type=A")
    assert use_codes.page_url("BLA125514") is None
    # Five digits in the book, six on the page.
    assert "Appl_No=021549&" in use_codes.page_url("NDA21549")


def test_the_plan_reads_the_pages_covering_most_missing_codes_first():
    wanted = {"NDA1": {"U-1", "U-2"}, "NDA2": {"U-2"}, "NDA3": {"U-3", "U-1", "U-2"}}
    assert use_codes.plan(wanted) == ["NDA3"]
    assert use_codes.plan({"NDA1": {"U-1"}, "NDA2": {"U-2"}}, limit=1) == ["NDA1"]
    assert use_codes.plan({}) == []


def test_only_undefined_codes_are_looked_up_and_a_definition_is_kept(tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    conn = db.get_connection(db_file)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AZN', 'AZ')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (1, 1, 'Farxiga', 1)")
    conn.execute("INSERT INTO orange_book_listings (asset_id, appl_code) VALUES (1, 'NDA202293')")
    conn.execute("INSERT INTO exclusivities (asset_id, region, protection_type, identifier,"
                 " expiry_date, use_codes, source) VALUES (1, 'US', 'patent', '6515117',"
                 " '2025-10-04', 'U-2139,U-493', 'orange_book')")
    conn.execute("INSERT INTO patent_use_codes (code, definition) VALUES ('U-493', 'KEPT')")
    conn.commit()
    assert needed(conn) == {"NDA202293": {"U-2139"}}
    conn.close()
    fetcher = UseCodesFetcher(db_file)
    rows = [{"code": c, "definition": t, "appl_code": "NDA202293"}
            for c, t in use_codes.parse(PAGE.read_text()).items()]
    fetcher.upsert(rows)
    conn = db.get_connection(db_file)
    got = dict(conn.execute("SELECT code, definition FROM patent_use_codes"))
    assert got["U-493"] == "KEPT" and got["U-2139"].endswith("WITH EXENATIDE")
    assert needed(conn) == {}
