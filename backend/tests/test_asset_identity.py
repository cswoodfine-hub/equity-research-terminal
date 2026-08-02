"""Giving a brand-only row the identity that is already on file, or one request away.

The case throughout is Pfizer, which books revenue on Eliquis, Xtandi, Padcev and
Adcetris and holds the FDA application for none of them.
"""

import pytest

import asset_identity
import asset_merge
import db
from fetchers import brand_lookup_openfda as lookup


def _company(conn, company_id, ticker):
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (?, ?, ?)",
                 (company_id, ticker, ticker))


def _asset(conn, asset_id, company_id, brand, generic=None, code=None, marketed=1):
    conn.execute(
        "INSERT INTO assets (id, owner_company_id, brand_name, generic_name,"
        "                    internal_code, is_marketed) VALUES (?, ?, ?, ?, ?, ?)",
        (asset_id, company_id, brand, generic, code, marketed))


@pytest.mark.parametrize("name, expected", [
    ("Eliquis", True), ("Padcev", True), ("Nurtec ODT/Vydura", True),
    ("Launches", False), ("License", False), ("Grant", False), ("Royalty", False),
    ("Total product sales", False), ("Product And Service Other", False),
    ("Collaboration Arrangement Including Arrangements With Affiliate", False),
])
def test_looks_like_a_product(name, expected):
    assert asset_identity.looks_like_a_product(name) is expected


@pytest.mark.parametrize("a, b", [
    ("Paxlovid", "Paxlovid (Copackaged)"),
    ("KRYSTEXXA", "Krystexxa"),
    ("Wainua", "Wainua (Autoinjector)"),
])
def test_brands_that_are_the_same_product(a, b):
    assert asset_merge.canonical_brand(a) == asset_merge.canonical_brand(b)


def test_brands_that_are_not_the_same_product():
    """The digits stay, because they are what tells two vaccines apart."""
    assert (asset_merge.canonical_brand("Prevnar 13")
            != asset_merge.canonical_brand("Prevnar 20"))


def test_the_ingredient_is_taken_across_companies(tmp_path):
    """Apixaban is what Eliquis is whether Bristol Myers or Pfizer books the sale, so
    the row that names it answers for the row that does not."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "BMY")
    _company(conn, 2, "PFE")
    _asset(conn, 10, 1, "Eliquis", generic="Apixaban", code="NDA202155")
    _asset(conn, 11, 2, "Eliquis")
    conn.commit()
    conn.close()

    assert asset_identity.fill(path)["named"] == 1
    conn = db.get_connection(path)
    assert conn.execute("SELECT generic_name FROM assets WHERE id = 11").fetchone()[0] \
        == "Apixaban"
    conn.close()


def test_no_approval_is_ever_copied(tmp_path):
    """One application is held by one company. Writing it under a second would count a
    single approval twice everywhere approvals are counted."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "BMY")
    _company(conn, 2, "PFE")
    _asset(conn, 10, 1, "Eliquis", generic="Apixaban")
    _asset(conn, 11, 2, "Eliquis")
    conn.execute("INSERT INTO approvals (asset_id, application_number, approval_date)"
                 " VALUES (10, 'NDA202155', '2012-12-28')")
    conn.commit()
    conn.close()

    asset_identity.fill(path)
    conn = db.get_connection(path)
    assert conn.execute(
        "SELECT COUNT(*) FROM approvals WHERE asset_id = 11").fetchone()[0] == 0
    conn.close()


def test_a_disputed_ingredient_is_left_alone(tmp_path):
    """A brand two rows give different ingredients for identifies neither."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "AAA")
    _company(conn, 2, "BBB")
    _company(conn, 3, "CCC")
    _asset(conn, 10, 1, "Duplo", generic="Alpha")
    _asset(conn, 11, 2, "Duplo", generic="Beta")
    _asset(conn, 12, 3, "Duplo")
    conn.commit()
    conn.close()

    assert asset_identity.fill(path)["named"] == 0
    conn = db.get_connection(path)
    assert conn.execute("SELECT generic_name FROM assets WHERE id = 12").fetchone()[0] is None
    conn.close()


def test_an_existing_ingredient_is_never_overwritten(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "AAA")
    _company(conn, 2, "BBB")
    _asset(conn, 10, 1, "Duplo", generic="Alpha")
    _asset(conn, 11, 2, "Duplo", generic="Kept")
    conn.commit()
    conn.close()

    asset_identity.fill(path)
    conn = db.get_connection(path)
    assert conn.execute("SELECT generic_name FROM assets WHERE id = 11").fetchone()[0] \
        == "Kept"
    conn.close()


def test_brand_duplicates_fold_into_the_identified_row(tmp_path):
    """openFDA files it as "Paxlovid (Copackaged)" with an NDA, the revenue table files
    it as "Paxlovid" with nothing, and the second reads as a product with no approval."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "PFE")
    _asset(conn, 10, 1, "Paxlovid (Copackaged)", generic="Nirmatrelvir", code="NDA217188")
    _asset(conn, 11, 1, "Paxlovid")
    conn.commit()
    pairs = asset_merge.find_brand_duplicates(conn, 1)
    conn.close()
    assert pairs == [(10, [11])]


def test_two_identified_rows_are_left_alone(tmp_path):
    """Both carry an approval, and choosing between them would throw one away on a
    spelling."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "PFE")
    _asset(conn, 10, 1, "Paxlovid", generic="Nirmatrelvir")
    _asset(conn, 11, 1, "Paxlovid (Copackaged)", generic="Nirmatrelvir Ritonavir")
    conn.commit()
    assert asset_merge.find_brand_duplicates(conn, 1) == []
    conn.close()


def test_lookup_reads_a_drugsfda_record():
    record = {"application_number": "NDA213674", "sponsor_name": "ASTELLAS",
              "openfda": {"generic_name": ["ENZALUTAMIDE"]}}
    assert lookup.read(record) == {"generic": "Enzalutamide",
                                   "application": "NDA213674", "sponsor": "ASTELLAS"}


def test_lookup_skips_a_record_with_no_ingredient():
    assert lookup.read({"application_number": "NDA1", "openfda": {}}) is None
    assert lookup.read(None) is None


def test_lookup_records_the_sponsor_and_writes_no_approval(tmp_path):
    """Pfizer sells Xtandi and Astellas holds the application. The row is corroborated,
    not credited: the note says whose filing it is and no approval row appears."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "PFE")
    _asset(conn, 10, 1, "Xtandi")
    conn.commit()
    conn.close()

    def fake_get(url):
        assert 'openfda.brand_name:"Xtandi"' in url or "Xtandi" in url
        return {"application_number": "NDA213674", "sponsor_name": "ASTELLAS",
                "openfda": {"generic_name": ["ENZALUTAMIDE"]}}

    assert lookup.resolve(path, get=fake_get)["found"] == 1
    conn = db.get_connection(path)
    row = conn.execute("SELECT generic_name, internal_code, notes FROM assets"
                       " WHERE id = 10").fetchone()
    assert row["generic_name"] == "Enzalutamide"
    assert row["internal_code"] == "NDA213674"
    assert "ASTELLAS" in row["notes"]
    assert conn.execute(
        "SELECT COUNT(*) FROM approvals WHERE asset_id = 10").fetchone()[0] == 0
    conn.close()


def test_lookup_never_asks_about_a_line_item(tmp_path):
    """A request spent on "Collaboration Arrangement" is a certain miss."""
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "MRNA")
    _asset(conn, 10, 1, "Collaboration Arrangement Including Arrangements With Affiliate")
    _asset(conn, 11, 1, "Grant")
    conn.commit()
    conn.close()

    asked = []

    def fake_get(url):
        asked.append(url)
        return None

    assert lookup.resolve(path, get=fake_get) == {"found": 0, "missing": 0, "errors": []}
    assert asked == []


def test_lookup_leaves_an_identified_row_alone(tmp_path):
    path = tmp_path / "t.db"
    db.init(path)
    conn = db.get_connection(path)
    _company(conn, 1, "PFE")
    _asset(conn, 10, 1, "Ibrance", generic="Palbociclib", code="NDA207103")
    conn.commit()
    conn.close()

    asked = []
    lookup.resolve(path, get=lambda url: asked.append(url))
    assert asked == []
