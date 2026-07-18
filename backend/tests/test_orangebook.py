"""parse_orange_book runs against saved trimmed Orange Book files, no network."""

from pathlib import Path

from fetchers.exclusivity_orangebook import APPLICANT_MAP, parse_orange_book

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text()


def test_parse_orange_book_matches_and_filters():
    rows = parse_orange_book(
        _read("orange_book_products.txt"),
        _read("orange_book_patent.txt"),
        _read("orange_book_exclusivity.txt"),
        APPLICANT_MAP,
    )
    # Two protected Lilly products; the no-protection NDA and the non-universe
    # applicant are dropped.
    by_code = {r["internal_code"]: r for r in rows}
    assert set(by_code) == {"NDA215866", "NDA217806"}

    mounjaro = by_code["NDA215866"]
    assert mounjaro["ticker"] == "LLY"
    assert mounjaro["brand"] == "Mounjaro"
    assert mounjaro["generic"] == "Tirzepatide"
    assert mounjaro["modality"] == "small molecule"
    assert mounjaro["exclusivities"]

    # LOE is the latest expiry across patents + exclusivity.
    loe = max(e["expiry_date"] for e in mounjaro["exclusivities"])
    assert loe == "2039-07-22"
    kinds = {e["protection_type"] for e in mounjaro["exclusivities"]}
    assert kinds == {"patent", "regulatory exclusivity"}
