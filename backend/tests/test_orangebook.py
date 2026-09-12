"""parse_orange_book runs against saved trimmed Orange Book files, no network."""

from pathlib import Path

from fetchers.exclusivity_orangebook import APPLICANT_MAP, parse_orange_book

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text()


def _parsed():
    return parse_orange_book(
        _read("orange_book_products.txt"),
        _read("orange_book_patent.txt"),
        _read("orange_book_exclusivity.txt"),
        APPLICANT_MAP,
    )


def test_discontinued_products_are_not_losing_exclusivity():
    """Regression: a DISCN product is off the market, so its live patents are not LOE.

    Axiron was discontinued but still lists a patent to 2027, and used to appear as
    Lilly's next loss of exclusivity. On the real Orange Book 1,291 of 1,819 tracked
    applications are fully discontinued, so this was not an edge case.
    """
    codes = {r["internal_code"] for r in _parsed()}
    assert "NDA22504" not in codes          # normalize_appl drops the leading zero
    assert not any("Axiron" == r["brand"] for r in _parsed())


def test_an_application_survives_when_any_strength_is_still_marketed():
    """Corlanor lists one discontinued strength and one live one. It stays."""
    by_code = {r["internal_code"]: r for r in _parsed()}
    assert "NDA206143" in by_code
    assert by_code["NDA206143"]["brand"] == "Corlanor"
    assert by_code["NDA206143"]["ticker"] == "AMGN"


def test_parse_orange_book_matches_and_filters():
    rows = _parsed()
    # Protected, still-marketed products only. The no-protection NDA, the discontinued
    # product, and the non-universe applicant are all dropped.
    by_code = {r["internal_code"]: r for r in rows}
    assert set(by_code) == {"NDA215866", "NDA217806", "NDA206143"}

    mounjaro = by_code["NDA215866"]
    assert mounjaro["ticker"] == "LLY"
    assert mounjaro["brand"] == "Mounjaro"
    assert mounjaro["generic"] == "Tirzepatide"
    assert mounjaro["modality"] == "small molecule"
    assert mounjaro["exclusivities"]

    # LOE is the latest expiry across patents + exclusivity.
    loe = max(e["expiry_date"] for e in mounjaro["exclusivities"])
    assert loe == "2039-07-22"
    kinds = {e["protection_type"] for e in mounjaro["exclusivities"]}
    assert kinds == {"patent", "regulatory exclusivity"}


def test_a_patent_listed_per_strength_is_stored_once():
    """The book repeats a patent for every product strength.

    Mounjaro held 522 rows for 10 distinct patents and the table was 63% exact
    duplicates. Protection belongs to the application, not to the strength.
    """
    rows = _parsed()
    mounjaro = next(r for r in rows if r["internal_code"] == "NDA215866")
    keys = [(e["protection_type"], e["identifier"], e["expiry_date"])
            for e in mounjaro["exclusivities"]]
    assert len(keys) == len(set(keys))


def test_short_applicant_names_resolve_through_the_full_name():
    """Regression: the book abbreviates Novo Nordisk to NOVO, which matched nothing.

    33 Novo products and 114 Merck products were dropped, Ozempic and Wegovy among
    them. The full name column is unambiguous.
    """
    products = (
        "Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~Product_No"
        "~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n"
        "SEMAGLUTIDE~SOLUTION;SUBCUTANEOUS~OZEMPIC~NOVO~2MG/1.5ML~N~209637~001~~"
        "Dec 5, 2017~Yes~Yes~RX~NOVO NORDISK INC\n"
        # Merck KGaA is a different company and must not land under MRK.
        "CLADRIBINE~TABLET;ORAL~MAVENCLAD~MERCK~10MG~N~022561~001~~Mar 29, 2019~Yes~Yes~RX~MERCK KGAA\n"
    )
    patents = ("Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~"
               "Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~Submission_Date\n"
               "N~209637~001~8129343~Jan 5, 2033~~~~~Feb 1, 2018\n"
               "N~022561~001~7888328~Jun 1, 2031~~~~~Apr 1, 2019\n")
    rows = parse_orange_book(products, patents, _read("orange_book_exclusivity.txt"),
                             APPLICANT_MAP)
    by_ticker = {r["ticker"]: r for r in rows}
    assert "NVO" in by_ticker and by_ticker["NVO"]["brand"] == "Ozempic"
    assert "MRK" not in by_ticker, "Merck KGaA is not Merck & Co"


def test_a_linked_application_under_an_unmapped_applicant_is_kept_for_its_assets():
    """Pfizer books Xtandi on Astellas's NDA. Astellas is not in the map, and the row
    used to be dropped; with the application linked to the asset on file it is kept,
    carries the asset ids, and no ticker is invented for it."""
    header = ("Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~"
              "Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n")
    products = header + ("ENZALUTAMIDE~CAPSULE;ORAL~XTANDI~ASTELLAS~40MG~N~203415~001~~"
                         "Aug 31, 2012~Yes~Yes~RX~ASTELLAS PHARMA US INC\n")
    patents = ("Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~"
               "Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~"
               "Submission_Date\n"
               "N~203415~001~7709517~Aug 13, 2027~Y~~~~Dec 12, 2012\n")
    exclusivity = "Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date\n"
    assert parse_orange_book(products, patents, exclusivity, APPLICANT_MAP) == []
    rows = parse_orange_book(products, patents, exclusivity, APPLICANT_MAP,
                             linked={"NDA203415": [824]})
    assert len(rows) == 1
    assert rows[0]["ticker"] is None and rows[0]["asset_ids"] == [824]
    assert rows[0]["exclusivities"][0]["identifier"] == "7709517"
    assert rows[0]["exclusivities"][0]["patent_kind"] == "substance"


def test_attach_direct_writes_onto_the_asset_and_creates_nothing(tmp_path):
    import db
    from fetchers.exclusivity_orangebook import OB_SOURCE, attach_direct
    path = str(tmp_path / "ob.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'PFE', 'Pfizer')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (824, 1, 'Xtandi', 1)")
    product = {"asset_ids": [824], "modality": "small molecule", "exclusivities": [
        {"protection_type": "patent", "identifier": "7709517",
         "expiry_date": "2027-08-13", "patent_kind": "substance"}]}
    from fetchers.exclusivity_orangebook import clear_direct
    clear_direct(conn, [product], OB_SOURCE)
    assert attach_direct(conn, product, OB_SOURCE, with_kind=True) == 1
    # A second application on the same asset adds its rows rather than replacing them.
    tablet = {"asset_ids": [824], "modality": "small molecule", "exclusivities": [
        {"protection_type": "patent", "identifier": "9999", "expiry_date": "2033-01-01",
         "patent_kind": "product"}]}
    assert attach_direct(conn, tablet, OB_SOURCE, with_kind=True) == 1
    assert conn.execute("SELECT COUNT(*) FROM exclusivities").fetchone()[0] == 2
    # Clearing once per run then re-attaching rebuilds in place.
    clear_direct(conn, [product, tablet], OB_SOURCE)
    assert attach_direct(conn, product, OB_SOURCE, with_kind=True) == 1
    rows = conn.execute("SELECT asset_id, identifier, patent_kind, source FROM"
                        " exclusivities").fetchall()
    assert [tuple(r) for r in rows] == [(824, "7709517", "substance", OB_SOURCE)]
    assert conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 1
    assert conn.execute("SELECT modality FROM assets WHERE id = 824").fetchone()[0] \
        == "small molecule"


def test_a_marketed_product_with_nothing_live_is_kept_as_a_listing():
    """Symbicort is in the book with no patent and no exclusivity. It used to be dropped
    on the way in; now it is carried as a listing with no rows, so the silence can be
    read as the finding it is. The old assertions on the fixture stand: a product no
    asset holds is still never created for it."""
    header = ("Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~"
              "Product_No~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n")
    products = header + ("BUDESONIDE; FORMOTEROL~AEROSOL~SYMBICORT~ASTRAZENECA~80MCG~N~"
                         "021929~001~~Jul 21, 2006~Yes~Yes~RX~ASTRAZENECA LP\n")
    patents = ("Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~"
               "Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~"
               "Submission_Date\n")
    rows = parse_orange_book(products, patents,
                             "Appl_Type~Appl_No~Product_No~Exclusivity_Code~Exclusivity_Date\n",
                             APPLICANT_MAP)
    assert len(rows) == 1 and rows[0]["listed_only"] is True
    assert rows[0]["exclusivities"] == [] and rows[0]["approval_date"] == "2006-07-21"


def test_a_listing_with_nothing_live_reads_as_an_loe_in_the_past(tmp_path):
    import db
    import loe
    from fetchers.exclusivity_orangebook import record_listing
    path = str(tmp_path / "lst.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'AZN', 'Astra')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " internal_code) VALUES (522, 1, 'Symbicort', 1, 'NDA21929')")
    record_listing(conn, {"internal_code": "NDA21929", "approval_date": "2006-07-21",
                          "applicant": "ASTRAZENECA LP", "exclusivities": []}, 522)
    got = loe.for_assets(conn, [522])[522]
    # Past and dateless: the approval year is not the year generics came.
    assert got["past"] is True and got["date"] is None
    assert got["basis"].startswith("lapsed, date not in the Orange Book")
    # A recent approval with nothing listed is not a lapsed product.
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed)"
                 " VALUES (523, 1, 'Prezcobix', 1)")
    record_listing(conn, {"internal_code": "NDA220092", "approval_date": "2026-02-27",
                          "applicant": "JANSSEN", "exclusivities": []}, 523)
    assert 523 not in loe.for_assets(conn, [523])
    # A live row on file outranks the listing.
    conn.execute("INSERT INTO exclusivities (asset_id, region, protection_type,"
                 " identifier, expiry_date, source) VALUES"
                 " (522, 'US', 'patent', '1', '2030-05-28', 't')")
    assert loe.for_assets(conn, [522])[522]["date"] == "2030-05-28"
