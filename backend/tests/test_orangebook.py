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


def test_a_patent_listed_per_strength_is_stored_once():
    """The book repeats a patent for every product strength.

    Mounjaro held 522 rows for 10 distinct patents and the table was 63% exact
    duplicates. Protection belongs to the application, not to the strength.
    """
    rows = _parsed()
    mounjaro = next(r for r in rows if r["internal_code"] == "NDA215866")
    keys = [(e["protection_type"], e["identifier"], e["expiry_date"])
            for e in mounjaro["exclusivities"]]
    assert len(keys) == len(set(keys))


def test_short_applicant_names_resolve_through_the_full_name():
    """Regression: the book abbreviates Novo Nordisk to NOVO, which matched nothing.

    33 Novo products and 114 Merck products were dropped, Ozempic and Wegovy among
    them. The full name column is unambiguous.
    """
    products = (
        "Ingredient~DF;Route~Trade_Name~Applicant~Strength~Appl_Type~Appl_No~Product_No"
        "~TE_Code~Approval_Date~RLD~RS~Type~Applicant_Full_Name\n"
        "SEMAGLUTIDE~SOLUTION;SUBCUTANEOUS~OZEMPIC~NOVO~2MG/1.5ML~N~209637~001~~"
        "Dec 5, 2017~Yes~Yes~RX~NOVO NORDISK INC\n"
        # Merck KGaA is a different company and must not land under MRK.
        "CLADRIBINE~TABLET;ORAL~MAVENCLAD~MERCK~10MG~N~022561~001~~Mar 29, 2019~Yes~Yes~RX~MERCK KGAA\n"
    )
    patents = ("Appl_Type~Appl_No~Product_No~Patent_No~Patent_Expire_Date_Text~"
               "Drug_Substance_Flag~Drug_Product_Flag~Patent_Use_Code~Delist_Flag~Submission_Date\n"
               "N~209637~001~8129343~Jan 5, 2033~~~~~Feb 1, 2018\n"
               "N~022561~001~7888328~Jun 1, 2031~~~~~Apr 1, 2019\n")
    rows = parse_orange_book(products, patents, _read("orange_book_exclusivity.txt"),
                             APPLICANT_MAP)
    by_ticker = {r["ticker"]: r for r in rows}
    assert "NVO" in by_ticker and by_ticker["NVO"]["brand"] == "Ozempic"
    assert "MRK" not in by_ticker, "Merck KGaA is not Merck & Co"
