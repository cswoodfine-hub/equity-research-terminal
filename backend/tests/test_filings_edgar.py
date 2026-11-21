"""parse_submissions runs against a saved EDGAR submissions fixture, no network."""

import json
from pathlib import Path

from fetchers.filings_edgar import parse_submissions

FIXTURE = Path(__file__).parent / "fixtures" / "edgar_submissions_lly.json"


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


def test_a_filing_keeps_the_moment_it_was_accepted_and_tolerates_a_feed_without_one():
    recent = {"form": ["8-K", "8-K"], "filingDate": ["2026-10-29", "2026-08-05"],
              "accessionNumber": ["0000059478-26-000100", "0000059478-26-000080"],
              "primaryDocument": ["a.htm", "b.htm"],
              "primaryDocDescription": ["8-K", "8-K"], "items": ["2.02,9.01", "2.02,9.01"],
              "acceptanceDateTime": ["2026-10-29T10:28:05.000Z"]}
    rows = parse_submissions({"filings": {"recent": recent}}, "59478")
    assert rows[0]["accepted_at"] == "2026-10-29T10:28:05.000Z"
    assert rows[1]["accepted_at"] is None
    del recent["acceptanceDateTime"]
    assert all(r["accepted_at"] is None
               for r in parse_submissions({"filings": {"recent": recent}}, "59478"))
