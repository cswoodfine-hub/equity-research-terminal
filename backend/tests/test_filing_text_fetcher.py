"""The 8-K exhibit route: the body is a pointer, the exhibit is the news."""

import json

from fetchers.filing_text_edgar import FilingTextEdgarFetcher

INDEX = json.dumps({"directory": {"item": [
    {"name": "0001193125-26-323940-index.html"},
    {"name": "dyn-20260729.htm"},
    {"name": "dyn-ex99_1.htm"},
    {"name": "dyn-20260729.xsd"},
    {"name": "R1.htm"},
]}})

PRIMARY = "<div>Item 2.02 Results of Operations.</div><div>See Exhibit 99.1.</div>"
EXHIBIT = "<div>Dyne Therapeutics Reports Second Quarter 2026 Financial Results</div>"


def _fetcher(tmp_path, monkeypatch, pending):
    import db
    path = str(tmp_path / "t.db")
    db.init(path)
    fetcher = FilingTextEdgarFetcher("DYN", db_path=path)
    monkeypatch.setattr(fetcher, "_pending", lambda conn: pending)
    monkeypatch.setenv("SEC_USER_AGENT", "test contact@example.com")

    def read(url, user_agent):
        if url.endswith("index.json"):
            return INDEX
        if "ex99" in url:
            return EXHIBIT
        return PRIMARY

    monkeypatch.setattr(fetcher, "_read", read)
    monkeypatch.setattr("fetchers.filing_text_edgar.time.sleep", lambda s: None)
    return fetcher


def test_an_eight_k_stores_its_body_and_its_exhibit(tmp_path, monkeypatch):
    """Dyne's quarterly 8-K body says only that a press release is furnished as Exhibit
    99.1. Without the exhibit the stored text says nothing the title did not."""
    pending = [{"company_id": 1, "accession": "0001-1", "form_type": "8-K",
                "filed_date": "2026-07-29",
                "url": "https://www.sec.gov/Archives/edgar/data/1/0001/dyn.htm"}]
    rows = _fetcher(tmp_path, monkeypatch, pending).fetch()
    sections = {r["section"]: r["text"] for r in rows}
    assert sections["body"].startswith("Item 2.02")
    assert "Second Quarter 2026 Financial Results" in sections["exhibit"]


def test_a_missing_exhibit_is_not_an_error(tmp_path, monkeypatch):
    """Most 8-Ks furnish none, and the body still stands on its own."""
    pending = [{"company_id": 1, "accession": "0001-2", "form_type": "8-K",
                "filed_date": "2026-06-22",
                "url": "https://www.sec.gov/Archives/edgar/data/1/0002/dyn.htm"}]
    fetcher = _fetcher(tmp_path, monkeypatch, pending)
    monkeypatch.setattr(fetcher, "_exhibit_urls", lambda url, ua: [])
    rows = fetcher.fetch()
    assert [r["section"] for r in rows] == ["body"]
