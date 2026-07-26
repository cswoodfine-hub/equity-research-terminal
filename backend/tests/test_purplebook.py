"""parse_purple_book runs against a saved trimmed Purple Book CSV, no network."""

import datetime as dt
from pathlib import Path

from fetchers.exclusivity_purplebook import (
    APPLICANT_MAP, FLOOR_PROTECTION, _licensure_date, parse_purple_book)

FIXTURE = Path(__file__).parent / "fixtures" / "purplebook_sample.csv"


def test_licensure_date_rolls_a_future_two_digit_year_back_a_century():
    today = dt.date(2026, 7, 26)
    # A 1954 licensure written 4-Sep-54 pivots to 2054; it must roll back, not project a
    # 12-year floor out to 2066.
    assert _licensure_date("4-Sep-54", today) == dt.date(1954, 9, 4)
    # A recent, genuinely past date is left alone.
    assert _licensure_date("8-Dec-23", today) == dt.date(2023, 12, 8)
    assert _licensure_date("", today) is None


def _floor(product):
    return next((e for e in product["exclusivities"]
                 if e["protection_type"] == FLOOR_PROTECTION), None)


def test_parse_purple_book_matches_and_filters():
    rows = parse_purple_book(FIXTURE.read_text(), APPLICANT_MAP)
    by_code = {r["internal_code"]: r for r in rows}

    # Universe applicants are kept, non-universe rows dropped. Aranesp has no published
    # exclusivity but a licensure date, so it is kept on the computed 12-year floor.
    assert set(by_code) == {"BLA103951", "BLA125514", "BLA125874"}

    keytruda = by_code["BLA125514"]
    assert keytruda["ticker"] == "MRK"
    assert keytruda["brand"] == "Keytruda"
    assert keytruda["modality"] == "biologic"
    # The published orphan date (2031) is later than the 12-year floor (2014+12=2026),
    # so the orphan wins the max but the floor is still recorded.
    assert max(e["expiry_date"] for e in keytruda["exclusivities"]) == "2031-01-25"
    assert _floor(keytruda)["expiry_date"] == "2026-09-04"


def test_statutory_floor_wins_when_later_than_orphan():
    """OTARMENI was approved in 2026, so its 12-year floor (2038) runs past its orphan
    exclusivity (2033); the floor sets the LOE. A biologic with no reference-product
    exclusivity on file no longer reads short to its orphan date."""
    by_code = {r["internal_code"]: r
               for r in parse_purple_book(FIXTURE.read_text(), APPLICANT_MAP)}
    otarmeni = by_code["BLA125874"]
    assert _floor(otarmeni)["expiry_date"] == "2038-04-23"
    assert max(e["expiry_date"] for e in otarmeni["exclusivities"]) == "2038-04-23"

    # A product whose file gives a reference-product exclusivity keeps it and gets no
    # computed floor, so a published date is never shadowed by the statute.
    for product in by_code.values():
        has_ref = any(e["protection_type"] == "reference product exclusivity"
                      for e in product["exclusivities"])
        assert not (has_ref and _floor(product))
