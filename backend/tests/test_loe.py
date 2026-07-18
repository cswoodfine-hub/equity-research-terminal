"""build_loe over a seeded DB, no network.

Orange Book data is loaded through the real fetcher with its download monkeypatched to
the saved fixture files.
"""

from pathlib import Path

import db
import loe
import seed
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
