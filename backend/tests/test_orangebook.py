"""parse_orange_book runs against saved trimmed Orange Book files, no network."""

from pathlib import Path

from fetchers.exclusivity_orangebook import APPLICANT_MAP, parse_orange_book

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name):
    return (FIXTURES / name).read_text()


def _parsed():
    return parse_orange_book(
        _read("orange_book_products.txt"),
        _read("orange_book_patent.txt"),
        _read("orange_book_exclusivity.txt"),
        APPLICANT_MAP,
    )


def test_discontinued_products_are_not_losing_exclusivity():
    """Regression: a DISCN product is off the market, so its live patents are not LOE.

    Axiron was discontinued but still lists a patent to 2027, and used to appear as
    Lilly's next loss of exclusivity. On the real Orange Book 1,291 of 1,819 tracked
    applications are fully discontinued, so this was not an edge case.
    """
    codes = {r["internal_code"] for r in _parsed()}
    assert "NDA22504" not in codes          # normalize_appl drops the leading zero
    assert not any("Axiron" == r["brand"] for r in _parsed())


def test_an_application_survives_when_any_strength_is_still_marketed():
    """Corlanor lists one discontinued strength and one live one. It stays."""
    by_code = {r["internal_code"]: r for r in _parsed()}
    assert "NDA206143" in by_code
    assert by_code["NDA206143"]["brand"] == "Corlanor"
    assert by_code["NDA206143"]["ticker"] == "AMGN"


def test_parse_orange_book_matches_and_filters():
    rows = _parsed()
    # Protected, still-marketed products only. The no-protection NDA, the discontinued
    # product, and the non-universe applicant are all dropped.
    by_code = {r["internal_code"]: r for r in rows}
    assert set(by_code) == {"NDA215866", "NDA217806", "NDA206143"}

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
