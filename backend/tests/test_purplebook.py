"""parse_purple_book runs against a saved trimmed Purple Book CSV, no network."""

from pathlib import Path

from fetchers.exclusivity_purplebook import APPLICANT_MAP, parse_purple_book

FIXTURE = Path(__file__).parent / "fixtures" / "purplebook_sample.csv"


def test_parse_purple_book_matches_and_filters():
    rows = parse_purple_book(FIXTURE.read_text(), APPLICANT_MAP)
    by_code = {r["internal_code"]: r for r in rows}

    # Keytruda (Merck) and OTARMENI (Regeneron) are kept; the no-exclusivity and
    # non-universe rows are dropped.
    assert set(by_code) == {"BLA125514", "BLA125874"}

    keytruda = by_code["BLA125514"]
    assert keytruda["ticker"] == "MRK"
    assert keytruda["brand"] == "Keytruda"
    assert keytruda["modality"] == "biologic"
    assert max(e["expiry_date"] for e in keytruda["exclusivities"]) == "2031-01-25"
