"""parse_purple_book runs against a saved trimmed Purple Book CSV, no network."""

import datetime as dt
from pathlib import Path

from fetchers.exclusivity_purplebook import (
    APPLICANT_MAP, FLOOR_PROTECTION, _licensure_date, parse_purple_book)

FIXTURE = Path(__file__).parent / "fixtures" / "purplebook_sample.csv"


def test_licensure_date_rolls_a_future_two_digit_year_back_a_century():
    today = dt.date(2026, 7, 26)
    # A 1954 licensure written 4-Sep-54 pivots to 2054; it must roll back, not project a
    # 12-year floor out to 2066.
    assert _licensure_date("4-Sep-54", today) == dt.date(1954, 9, 4)
    # A recent, genuinely past date is left alone.
    assert _licensure_date("8-Dec-23", today) == dt.date(2023, 12, 8)
    assert _licensure_date("", today) is None


def _floor(product):
    return next((e for e in product["exclusivities"]
                 if e["protection_type"] == FLOOR_PROTECTION), None)


def test_parse_purple_book_matches_and_filters():
    rows = parse_purple_book(FIXTURE.read_text(), APPLICANT_MAP)
    by_code = {r["internal_code"]: r for r in rows}

    # Universe applicants are kept, non-universe rows dropped. Aranesp has no published
    # exclusivity but a licensure date, so it is kept on the computed 12-year floor.
    assert set(by_code) == {"BLA103951", "BLA125514", "BLA125874"}

    keytruda = by_code["BLA125514"]
    assert keytruda["ticker"] == "MRK"
    assert keytruda["brand"] == "Keytruda"
    assert keytruda["modality"] == "biologic"
    # The published orphan date (2031) is later than the 12-year floor (2014+12=2026),
    # so the orphan wins the max but the floor is still recorded.
    assert max(e["expiry_date"] for e in keytruda["exclusivities"]) == "2031-01-25"
    assert _floor(keytruda)["expiry_date"] == "2026-09-04"


def test_statutory_floor_wins_when_later_than_orphan():
    """OTARMENI was approved in 2026, so its 12-year floor (2038) runs past its orphan
    exclusivity (2033); the floor sets the LOE. A biologic with no reference-product
    exclusivity on file no longer reads short to its orphan date."""
    by_code = {r["internal_code"]: r
               for r in parse_purple_book(FIXTURE.read_text(), APPLICANT_MAP)}
    otarmeni = by_code["BLA125874"]
    assert _floor(otarmeni)["expiry_date"] == "2038-04-23"
    assert max(e["expiry_date"] for e in otarmeni["exclusivities"]) == "2038-04-23"

    # A product whose file gives a reference-product exclusivity keeps it and gets no
    # computed floor, so a published date is never shadowed by the statute.
    for product in by_code.values():
        has_ref = any(e["protection_type"] == "reference product exclusivity"
                      for e in product["exclusivities"])
        assert not (has_ref and _floor(product))


# --- the date format the source changed to ------------------------------
def test_both_date_forms_the_file_has_used_are_read():
    """The September 2026 release writes "October 18, 2017" where the saved fixture
    writes "4-Sep-14". Only the second was accepted, so against the live file every
    date read as None, every product was dropped for having neither an exclusivity nor
    a licensure, and the fetcher parsed nothing while reporting no error."""
    from fetchers.exclusivity_purplebook import _pb_date

    assert _pb_date("October 18, 2017") == dt.date(2017, 10, 18)
    assert _pb_date("4-Sep-14") == dt.date(2014, 9, 4)
    assert _pb_date("") is None
    assert _pb_date("not a date") is None


# --- licensure dates for the products openFDA cannot reach --------------
LIVE_FORM = """Purple Book Monthly Report

legend N/R/U
N/R/U,Applicant,BLA Number,Proprietary Name,Proper Name,License Type,Strength,Dosage Form,Route of Administration,Product Presentation,Marketing Status,Licensure,Approval Date
U,"Kite Pharma, Inc.",125643,Yescarta,axicabtagene ciloleucel,351(a),,Suspension,Intravenous,Bag,Rx,Licensed,"October 18, 2017"
U,"Kite Pharma, Inc.",125643,Yescarta,axicabtagene ciloleucel,351(a),,Suspension,Intravenous,Bag,Rx,Licensed,"March 5, 2022"
U,GlaxoSmithKline Biologicals,103239,Engerix-B,hepatitis b vaccine,351(a),10MCG,Suspension,Intramuscular,Vial,Rx,Licensed,"August 28, 1989"
U,"Two Owners, Inc.",111111,Sharedname,something,351(a),,Solution,Intravenous,Vial,Rx,Licensed,"May 1, 2001"
U,"Other Owner, Inc.",222222,Sharedname,something else,351(a),,Solution,Intravenous,Vial,Rx,Licensed,"May 1, 2002"
U,"Nodate Inc.",333333,Undated,nothing,351(a),,Solution,Intravenous,Vial,Rx,Licensed,
"""


def test_parse_licensures_takes_the_earliest_date_per_bla():
    """A BLA appears once per presentation and per supplement. The original licensure
    is the earliest of them, not the latest strength added under it."""
    from fetchers.exclusivity_purplebook import parse_licensures

    rows = {r["brand"].upper(): r for r in parse_licensures(LIVE_FORM)}
    assert rows["YESCARTA"]["approval_date"] == "2017-10-18"
    assert rows["YESCARTA"]["application_number"] == "BLA125643"
    assert rows["ENGERIX-B"]["approval_date"] == "1989-08-28"
    # A row with no date cannot date anything and is left out.
    assert "UNDATED" not in rows


def test_parse_licensures_keeps_a_product_no_applicant_map_knows():
    """parse_purple_book keeps a product only where its applicant maps to a company in
    the universe, which is right for a loss-of-exclusivity view and fatal here: Abeona,
    Autolus and Krystal are in no map and each sells a licensed product with a date.
    Asked with a map holding only GSK, it cannot see Kite's Yescarta; parse_licensures
    reads every row whoever filed it."""
    from fetchers.exclusivity_purplebook import parse_licensures, parse_purple_book

    mapped = {p["brand"].upper() for p in parse_purple_book(LIVE_FORM, {"GSK": ["GLAXO"]})}
    assert "YESCARTA" not in mapped
    assert {r["brand"].upper() for r in parse_licensures(LIVE_FORM)} >= {
        "YESCARTA", "ENGERIX-B"}


def _asset(conn, company_id, brand, marketed=1, appl=None):
    conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, is_marketed) VALUES (?, ?, ?)",
        (company_id, brand, marketed))
    asset_id = conn.execute("SELECT MAX(id) FROM assets").fetchone()[0]
    if appl:
        conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                     " VALUES (?, ?, '2000-01-01')", (asset_id, appl))
    return asset_id


def test_attach_licensures_dates_the_products_openfda_cannot(tmp_path):
    """The CAR-Ts, gene therapies, vaccines and clotting factors are CBER and are not in
    Drugs@FDA at all. The Purple Book is the register that holds them."""
    import db
    from fetchers.exclusivity_purplebook import attach_licensures, parse_licensures

    path = str(tmp_path / "pb.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'GILD', 'Gilead')")
    yescarta = _asset(conn, 1, "Yescarta")
    conn.commit()

    got = attach_licensures(conn, parse_licensures(LIVE_FORM))
    conn.commit()
    assert got["written"] == 1
    row = conn.execute(
        "SELECT application_number, approval_date, source FROM approvals WHERE asset_id = ?",
        (yescarta,)).fetchone()
    assert row["application_number"] == "BLA125643"
    assert row["approval_date"] == "2017-10-18"
    assert row["source"] == "purple_book"
    conn.close()


def test_attach_licensures_leaves_a_product_openfda_already_dated(tmp_path):
    """Only the gap. A product the other source carries is not argued with."""
    import db
    from fetchers.exclusivity_purplebook import attach_licensures, parse_licensures

    path = str(tmp_path / "pb.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'GILD', 'Gilead')")
    _asset(conn, 1, "Yescarta", appl="BLA125643")
    conn.commit()

    assert attach_licensures(conn, parse_licensures(LIVE_FORM))["written"] == 0
    assert conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1
    conn.close()


def test_attach_licensures_refuses_a_brand_standing_for_two_applications(tmp_path):
    """Two BLAs under one proprietary name is not resolved by guessing which."""
    import db
    from fetchers.exclusivity_purplebook import attach_licensures, parse_licensures

    path = str(tmp_path / "pb.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'X', 'X plc')")
    _asset(conn, 1, "Sharedname")
    conn.commit()

    got = attach_licensures(conn, parse_licensures(LIVE_FORM))
    assert got == {"written": 0, "ambiguous": 1, "unmatched": 0}
    conn.close()


def test_attach_licensures_reads_the_first_of_several_brands_on_one_asset(tmp_path):
    """"Fluarix, Fluarix Quadrivalent" is one asset holding two brands; the first is the
    one the application is filed under."""
    import db
    from fetchers.exclusivity_purplebook import attach_licensures, parse_licensures

    path = str(tmp_path / "pb.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'GSK', 'GSK plc')")
    asset = _asset(conn, 1, "Engerix-B, Engerix-B Paediatric")
    conn.commit()

    assert attach_licensures(conn, parse_licensures(LIVE_FORM))["written"] == 1
    assert conn.execute("SELECT approval_date FROM approvals WHERE asset_id = ?",
                        (asset,)).fetchone()[0] == "1989-08-28"
    conn.close()


def test_attach_licensures_ignores_an_unmarketed_asset(tmp_path):
    """A pipeline compound has no approval to find, and the gap this closes is the
    marketed register."""
    import db
    from fetchers.exclusivity_purplebook import attach_licensures, parse_licensures

    path = str(tmp_path / "pb.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'GILD', 'Gilead')")
    _asset(conn, 1, "Yescarta", marketed=0)
    conn.commit()

    assert attach_licensures(conn, parse_licensures(LIVE_FORM))["written"] == 0
    conn.close()


def test_a_later_bla_for_the_same_molecule_keeps_the_first_licensure_clock():
    """Saphnelo's shape: a 2021 BLA and a 2026 BLA for the same proper name from the same
    sponsor. The second earns no new 12 years (42 U.S.C. 262(k)(7)(C)), so both floors
    count from 2021. A BLA with a different proper name keeps its own clock."""
    header = FIXTURE.read_text().splitlines()[3]
    rows = [
        "U,MSD International Business GmbH,125514,Keytruda,pembrolizumab,351(a),50MG,"
        "For Injection,Intravenous,Single-Dose Vial,Rx,Licensed,4-Sep-14,,N/A,N/A,,"
        "Original,,2405,001,CDER,,,,,,",
        "U,MSD International Business GmbH,761999,Keytruda,pembrolizumab,351(a),395MG,"
        "Injection,Subcutaneous,Single-Dose Vial,Rx,Licensed,19-Sep-25,,N/A,N/A,,"
        "Original,,2405,001,CDER,,,,,,",
        "U,MSD International Business GmbH,761888,Keytruda Qlex,"
        "pembrolizumab and berahyaluronidase alfa-pmph,351(a),790MG,Injection,"
        "Subcutaneous,Single-Dose Vial,Rx,Licensed,19-Sep-25,,N/A,N/A,,Original,,2405,"
        "001,CDER,,,,,,",
    ]
    csv_text = "\n".join(["sample", "", "legend", header] + rows) + "\n"
    by_code = {r["internal_code"]: r for r in parse_purple_book(csv_text, APPLICANT_MAP)}
    assert _floor(by_code["BLA125514"])["expiry_date"] == "2026-09-04"
    assert _floor(by_code["BLA761999"])["expiry_date"] == "2026-09-04"
    assert _floor(by_code["BLA761888"])["expiry_date"] == "2037-09-19"
