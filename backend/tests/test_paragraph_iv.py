"""Paragraph IV certifications: parsing the list text, resolving the current PDF link,
matching a reference drug to an asset, and the challenged state the LOE view reads. No
network."""

from pathlib import Path

import db
import loe as loe_module
import paragraph_iv
import seed
from fetchers.paragraph_iv_fda import ParagraphIvFetcher

_FIX = Path(__file__).resolve().parent / "fixtures"
_TEXT = (_FIX / "paragraph_iv.txt").read_text()
_PAGE = (_FIX / "patent_cert_page.html").read_text()


# --- parsing --------------------------------------------------------------
def test_parse_reads_one_row_per_reference_drug_with_earliest_date():
    rows = {r["application_number"]: r["first_submission"]
            for r in paragraph_iv.parse_list(_TEXT)}
    assert rows["NDA21539"] == "2012-04-04"
    assert rows["NDA201292"] == "2017-07-12"
    assert rows["NDA20802"] is None                  # Pre-MMA has no cert date
    # Zepbound appears twice; the earlier certification is the one kept.
    assert rows["NDA21780"] == "2025-06-01"


def test_resolve_list_url_takes_the_new_certifications_link():
    url = paragraph_iv.resolve_list_url(_PAGE)
    assert url == "https://www.fda.gov/media/166048/download?attachment"
    assert paragraph_iv.resolve_list_url("<html>no link here</html>") is None


# --- fetcher --------------------------------------------------------------
def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    lly = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    cur = conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                       " internal_code, modality, is_marketed)"
                       " VALUES (?, 'Zepbound', 'Tirzepatide', 'NDA21780',"
                       " 'small molecule', 1)", (lly,))
    asset_id = cur.lastrowid
    conn.commit()
    conn.close()
    return asset_id


def _challenges(db_file):
    conn = db.get_connection(db_file)
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM patent_challenges")]
    finally:
        conn.close()


def test_fetcher_matches_reference_drug_to_asset_and_drops_the_rest(tmp_path):
    db_file = tmp_path / "t.db"
    asset_id = _seed(db_file)
    fetcher = ParagraphIvFetcher(db_file)
    rows = fetcher.normalise(paragraph_iv.parse_list(_TEXT))
    # Only Zepbound is in the universe; Acetadote, Gilotrif and Excedrin are dropped.
    assert [r["application_number"] for r in rows] == ["NDA21780"]

    fetcher.upsert(rows)
    challenges = _challenges(db_file)
    assert len(challenges) == 1
    assert challenges[0]["asset_id"] == asset_id
    assert challenges[0]["first_submission"] == "2025-06-01"


def test_upsert_is_idempotent_and_prunes_resolved_challenges(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = ParagraphIvFetcher(db_file)
    fetcher.upsert(fetcher.normalise(paragraph_iv.parse_list(_TEXT)))
    fetcher.upsert(fetcher.normalise(paragraph_iv.parse_list(_TEXT)))     # twice
    assert len(_challenges(db_file)) == 1

    # The challenge drops off the next list; it is withdrawn rather than left stale.
    fetcher.upsert(fetcher.normalise([]))
    assert _challenges(db_file) == []


def test_loe_detail_marks_a_challenged_asset(tmp_path):
    db_file = tmp_path / "t.db"
    asset_id = _seed(db_file)
    conn = db.get_connection(db_file)
    conn.execute("INSERT INTO exclusivities (asset_id, protection_type, expiry_date,"
                 " source) VALUES (?, 'patent', '2032-06-01', 'orange_book')",
                 (asset_id,))
    conn.execute("INSERT INTO patent_challenges (asset_id, application_number,"
                 " first_submission) VALUES (?, 'NDA21780', '2025-06-01')", (asset_id,))
    conn.commit()
    conn.close()

    detail = loe_module.loe_detail(db_file, "LLY")
    zepbound = next(a for a in detail if a["brand_name"] == "Zepbound")
    assert zepbound["challenged"] == 1
    assert zepbound["challenge_date"] == "2025-06-01"
