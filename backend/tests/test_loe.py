"""build_loe over a seeded DB, no network.

Orange Book data is loaded through the real fetcher with its download monkeypatched to
the saved fixture files.
"""

from pathlib import Path

import db
import loe
import seed
import whatchanged
from fetchers.exclusivity_orangebook import OrangeBookFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_download():
    return {
        "products": (FIXTURES / "orange_book_products.txt").read_text(),
        "patents": (FIXTURES / "orange_book_patent.txt").read_text(),
        "exclusivity": (FIXTURES / "orange_book_exclusivity.txt").read_text(),
    }


def test_loe_cliff_and_detail(tmp_path, monkeypatch):
    monkeypatch.setattr(OrangeBookFetcher, "fetch", lambda self: _fixture_download())

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    OrangeBookFetcher(db_file).run()

    cliff = loe.build_loe(db_file, horizon=20)
    rows = {r["ticker"]: r for r in cliff["rows"]}
    # Mounjaro and Zepbound both expire 2039-07-22 in the fixture.
    assert rows["LLY"]["total"] == 2
    assert rows["LLY"]["years"].get(2039) == 2
    assert rows["PFE"]["total"] == 0  # untouched company

    detail = loe.loe_detail(db_file, "LLY")
    assert len(detail) == 2
    assert {a["brand_name"] for a in detail} == {"Mounjaro", "Zepbound"}
    assert all(a["loe_year"] == 2039 for a in detail)
    assert loe.loe_detail(db_file, "ZZZZ") is None


def test_loe_carries_the_protection_type_that_set_it(tmp_path):
    """A date without its basis reads as a cliff even when it is not one.

    86% of biologic LOE dates come from orphan exclusivity, which covers a single
    orphan indication and does not gate biosimilar entry.
    """
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='AMGN'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
                 " VALUES (?, 'Testbio', 'biologic', 1)", (cid,))
    aid = conn.execute("SELECT id FROM assets WHERE brand_name='Testbio'").fetchone()[0]
    # The later date is the orphan one, so it sets the LOE and must be named as such.
    for kind, expiry in (("reference product exclusivity", "2029-01-01"),
                         ("orphan exclusivity", "2031-06-14")):
        conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                     " expiry_date, source) VALUES (?,?,'X',?,'purple_book')",
                     (aid, kind, expiry))
    conn.commit()
    conn.close()

    asset = next(a for a in loe.loe_detail(db_file, "AMGN")
                 if a["brand_name"] == "Testbio")
    assert asset["loe"] == "2031-06-14"
    assert asset["loe_basis"] == "orphan exclusivity"

    item = next(i for i in whatchanged.build_feed(db_file, ticker="AMGN", loe_months=120)
                if i["kind"] == "loe" and "Testbio" in i["headline"])
    assert item["loe_basis"] == "orphan exclusivity"
    assert "orphan exclusivity expires" in item["headline"]


def test_merged_loe_floors_biologics_and_leaves_others():
    # The 12-year floor wins when it lands after the latest listed date.
    assert loe.merged_loe("2031-06-14", "orphan exclusivity", 2035) == (
        "2035-12-31", "statutory floor (12y)")
    # A biologic with no listed date at all still gets the floor.
    assert loe.merged_loe(None, None, 2033) == ("2033-12-31", "statutory floor (12y)")
    # A later listed patent beats the floor and keeps its own basis.
    assert loe.merged_loe("2040-01-01", "patent", 2035) == ("2040-01-01", "patent")
    # No floor (a small molecule) is left untouched.
    assert loe.merged_loe("2043-05-01", "patent", None) == ("2043-05-01", "patent")


def test_loe_detail_shows_range_and_merges_floor(tmp_path):
    """A small molecule reports the earliest and latest expiry; a biologic whose only
    Purple Book date is a short orphan exclusivity is lifted to the 12-year floor."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='AMGN'").fetchone()[0]

    # Small molecule with two patents: the range runs earliest to latest.
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
                 " VALUES (?, 'Testsmall', 'small molecule', 1)", (cid,))
    sid = conn.execute("SELECT id FROM assets WHERE brand_name='Testsmall'").fetchone()[0]
    for expiry in ("2038-03-01", "2043-09-15"):
        conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                     " expiry_date, source) VALUES (?, 'patent', 'X', ?, 'orange_book')",
                     (sid, expiry))

    # Biologic whose only listed date is a 2031 orphan exclusivity, but with a 2035
    # statutory floor computed: the floor should set the displayed LOE.
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, modality, is_marketed)"
                 " VALUES (?, 'Testfloor', 'biologic', 1)", (cid,))
    bid = conn.execute("SELECT id FROM assets WHERE brand_name='Testfloor'").fetchone()[0]
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, identifier,"
                 " expiry_date, source) VALUES (?, 'orphan exclusivity', 'X',"
                 " '2031-06-14', 'purple_book')", (bid,))
    conn.execute("INSERT INTO biologic_loe (asset_id, loe_year, floor_year, basis)"
                 " VALUES (?, 2035, 2035, 'statutory floor')", (bid,))
    conn.commit()
    conn.close()

    detail = {a["brand_name"]: a for a in loe.loe_detail(db_file, "AMGN")}

    small = detail["Testsmall"]
    assert small["loe_year"] == 2043
    assert small["loe_earliest_year"] == 2038

    floored = detail["Testfloor"]
    assert floored["loe_year"] == 2035
    assert floored["loe_basis"] == "statutory floor (12y)"


def test_a_substance_patent_sets_the_date_over_a_later_use_patent():
    # Mounjaro's use patent runs to 2041 and its molecule patents to 2039. A generic
    # can carve a method-of-use claim out of its label, so 2041 is not the cliff.
    date, basis = loe.effective("2041-12-30", "patent", None,
                                substance_max="2039-06-14")
    assert date == "2039-06-14"
    assert basis == "drug substance patent"


def test_without_a_substance_flag_the_latest_listed_date_still_stands():
    date, basis = loe.effective("2033-03-01", "patent", None, substance_max=None)
    assert (date, basis) == ("2033-03-01", "patent")


def test_the_biologic_floor_still_applies_over_a_substance_patent():
    date, basis = loe.effective("2030-01-01", "patent", 2035,
                                substance_max="2030-01-01")
    assert date == "2035-12-31"
    assert basis == "statutory floor (12y)"
