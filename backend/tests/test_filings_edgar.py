"""parse_submissions runs against a saved EDGAR submissions fixture, no network."""

import json
from pathlib import Path

import db
import seed
from fetchers.filings_edgar import FilingsEdgarFetcher, news_title, parse_submissions

FIXTURE = Path(__file__).parent / "fixtures" / "edgar_submissions_lly.json"
ITEMS_FIXTURE = Path(__file__).parent / "fixtures" / "edgar_submissions_items.json"


def _titles(fixture: Path) -> dict:
    payload = json.loads(fixture.read_text())
    rows = parse_submissions(payload, payload["cik"])
    return {r["accession"]: r for r in rows}


def test_parse_submissions_keeps_material_and_builds_url():
    payload = json.loads(FIXTURE.read_text())
    rows = parse_submissions(payload, payload["cik"])

    # 4 material filings (3 8-K, 1 10-Q); the two Form 144 rows are dropped.
    assert len(rows) == 4
    assert {r["form_type"] for r in rows} == {"8-K", "10-Q"}
    assert sum(r["form_type"] == "8-K" for r in rows) == 3

    first = rows[0]
    assert first["accession"] and first["filed_date"]
    # Doc URL uses the un-padded CIK and the accession without dashes.
    assert first["url"].startswith("https://www.sec.gov/Archives/edgar/data/59478/")
    assert "-" not in first["url"].rsplit("/", 2)[1]  # accession segment has no dashes


def test_item_codes_become_the_title():
    """The item codes on the submissions feed are what an 8-K is about."""
    rows = _titles(ITEMS_FIXTURE)
    assert rows["0000318154-26-000042"]["title"] == "Material cybersecurity incident"
    # Exhibits ride along with almost everything, so the earnings release leads.
    assert rows["0000059478-26-000018"]["title"] == "Results of operations"
    # Where every item is routine they are still better than the form name.
    assert rows["0000318154-26-000031"]["title"] == ("Shareholder vote, "
                                                    "Financial statements and exhibits")


def test_a_description_that_only_names_the_form_is_not_a_title():
    """Regression: "8-K", "FORM 8-K" and "CURRENT REPORT" all mean the same nothing.

    The fallback to primaryDocDescription is there for filers who write the
    announcement into it. Taking the form's own name instead produced "8-K: FORM 8-K",
    which is the same defect as "8-K: 8-K" wearing a different hat.
    """
    rows = _titles(ITEMS_FIXTURE)
    assert rows["0000059478-26-000009"]["title"] == "8-K"      # desc "CURRENT REPORT"
    assert rows["0001121404-26-000008"]["title"] == "6-K"      # desc "6-K"
    assert rows["0001776985-26-000047"]["title"] == "6-K"      # desc "FORM 6-K"


def test_a_foreign_filer_writing_the_announcement_keeps_it():
    """A 6-K carries no item codes, so the filer's description is the only title there
    is. Most say "6-K"; the ones that do not are the announcement itself."""
    rows = _titles(ITEMS_FIXTURE)
    assert rows["0001697862-26-000033"]["title"] == "DIRECTOR/PDMR SHAREHOLDING"


def test_the_form_is_never_named_twice():
    """Regression: 501 news rows read "8-K: 8-K" or "6-K: 6-K"."""
    assert news_title("8-K", "Results of operations") == "8-K: Results of operations"
    assert news_title("6-K", "DIRECTOR/PDMR SHAREHOLDING") == "6-K: DIRECTOR/PDMR SHAREHOLDING"
    # Where nothing resolved, the form is said once rather than twice.
    assert news_title("8-K", "8-K") == "8-K"
    assert news_title("6-K", "6-K") == "6-K"
    assert news_title("8-K", "") == "8-K"
    assert news_title("8-K", None) == "8-K"


def test_no_filing_in_the_fixture_names_its_form_twice():
    """The end to end guarantee, across every title shape the feed produces."""
    for row in _titles(ITEMS_FIXTURE).values():
        title = news_title(row["form_type"], row["title"])
        assert title == row["form_type"] or not title.endswith(f": {row['form_type']}")


def test_a_news_headline_heals_when_the_description_improves(tmp_path):
    """Regression: 323 rows sat on "8-K: 8-K" for weeks after the fix that resolved it.

    The upsert was ON CONFLICT(url) DO NOTHING, so the first title written to a URL was
    the last. The filings row beside it used DO UPDATE and healed on the next refresh,
    which is why the two tables disagreed about the same document.
    """
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)

    payload = json.loads(ITEMS_FIXTURE.read_text())
    fetcher = FilingsEdgarFetcher("AMGN", db_file)
    fetcher._cik = payload["cik"]
    rows = fetcher.normalise(payload)
    url = next(r["url"] for r in rows if r["accession"] == "0000318154-26-000042")

    conn = db.get_connection(db_file)
    company_id = conn.execute(
        "SELECT id FROM companies WHERE ticker='AMGN'").fetchone()[0]
    conn.execute("INSERT INTO news (company_id, source, title, url, published_at)"
                 " VALUES (?, 'edgar_8k', '8-K: 8-K', ?, '2026-07-31')",
                 (company_id, url))
    conn.commit()
    conn.close()

    fetcher.upsert(rows)

    conn = db.get_connection(db_file)
    titles = dict(conn.execute(
        "SELECT url, title FROM news WHERE source = 'edgar_8k'").fetchall())
    conn.close()
    assert titles[url] == "8-K: Material cybersecurity incident"
    # And nothing anywhere in the feed names its form twice.
    assert not [t for t in titles.values() if t in ("8-K: 8-K", "6-K: 6-K")]
