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
