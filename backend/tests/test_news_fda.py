"""FDA announcement feeds: parsing, conservative company matching, and the fetcher
storing matched items in the news table. No network."""

from pathlib import Path

import db
import rssfeed
import seed
from fetchers.news_fda import NewsFdaFetcher

_FIX = Path(__file__).resolve().parent / "fixtures"
_PRESS = (_FIX / "fda_press.xml").read_text()


# --- parsing --------------------------------------------------------------
def test_parse_feed_reads_items_and_dates():
    items = rssfeed.parse_feed(_PRESS)
    assert len(items) == 3
    first = items[0]
    assert first["title"].startswith("FDA Approves New Eli Lilly")
    assert first["published"] == "2026-07-17"          # RFC 822 -> ISO, tz stripped
    assert first["url"].endswith("lilly-t2d")


def test_parse_feed_bad_xml_is_empty():
    assert rssfeed.parse_feed("<not xml") == []


# --- matching -------------------------------------------------------------
def test_company_tokens_drop_generic_words():
    tokens = rssfeed.company_tokens("Eli Lilly and Company", "LLY", ["Zepbound"])
    assert "LLY" in tokens and "Lilly" in tokens and "Zepbound" in tokens
    assert "Company" not in tokens and "and" not in tokens   # too generic


def test_match_is_by_word_boundary_not_substring():
    token_map = {1: ["Bayer"]}
    assert rssfeed.match_company("Bayer reports data", token_map) == 1
    assert rssfeed.match_company("the taxpayer meeting", token_map) is None


def test_match_finds_a_brand():
    token_map = {7: ["Vertex", "Casgevy"]}
    assert rssfeed.match_company("Casgevy gains an indication", token_map) == 7


def test_generic_brand_words_are_not_match_tokens():
    # The product-revenue parser turns 10-K segment rows into stray brand names.
    # A company must not bind to a press release just because it says "general".
    tokens = rssfeed.company_tokens("Johnson & Johnson", "JNJ",
                                    ["GENERAL", "Influenza", "Darzalex"])
    assert "Darzalex" in tokens                 # a real coined brand survives
    assert "GENERAL" not in tokens and "Influenza" not in tokens
    token_map = {6: tokens}
    assert rssfeed.match_company(
        "M15 General Principles for Model-Informed Drug Development", token_map) is None
    assert rssfeed.match_company("Darzalex gains an indication", token_map) == 6


def test_multi_word_brand_labels_are_dropped_not_guessed():
    # The product-revenue parser writes revenue-line labels into brand_name. There is
    # no safe way to know which word is the brand, so the whole label is dropped rather
    # than leak a common word like "Children" or "Liver" as a match token.
    tokens = rssfeed.company_tokens("Johnson & Johnson", "JNJ",
                                    ["Children'S Allegra Allergy", "Tzield"])
    assert "Tzield" in tokens                         # a lone coined brand survives
    assert not any(t in tokens for t in ("Children", "Allegra", "Allergy"))
    assert rssfeed.match_company(
        "FDA approves a therapy for young children", {6: tokens}) is None


# --- fetcher --------------------------------------------------------------
def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    vid = conn.execute("SELECT id FROM companies WHERE ticker='VRTX'").fetchone()[0]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, is_marketed)"
                 " VALUES (?, 'Casgevy', 1)", (vid,))
    conn.commit()
    conn.close()


def test_fetcher_matches_items_to_companies_and_keeps_the_rest(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = NewsFdaFetcher(db_file)
    raw = [{**it, "feed": "fda_press"} for it in rssfeed.parse_feed(_PRESS)]
    rows = fetcher.normalise(raw)
    fetcher.upsert(rows)

    conn = db.get_connection(db_file)
    try:
        news = {r["url"].split("/")[-1]: r for r in conn.execute(
            "SELECT n.url, n.source, n.title, c.ticker FROM news n"
            " LEFT JOIN companies c ON c.id = n.company_id")}
    finally:
        conn.close()
    assert news["lilly-t2d"]["ticker"] == "LLY"          # matched by name
    assert news["casgevy-peds"]["ticker"] == "VRTX"      # matched by brand (a CBER product)
    assert news["registration"]["ticker"] is None        # named nobody, still kept
    assert news["lilly-t2d"]["source"] == "fda_press"


def test_upsert_is_idempotent_on_the_url(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    fetcher = NewsFdaFetcher(db_file)
    raw = [{**it, "feed": "fda_press"} for it in rssfeed.parse_feed(_PRESS)]
    fetcher.upsert(fetcher.normalise(raw))
    fetcher.upsert(fetcher.normalise(raw))               # twice
    conn = db.get_connection(db_file)
    try:
        assert conn.execute("SELECT COUNT(*) FROM news").fetchone()[0] == 3
    finally:
        conn.close()
