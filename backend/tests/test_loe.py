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
