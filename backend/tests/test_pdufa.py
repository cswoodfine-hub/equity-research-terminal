"""PDUFA extraction from 8-K text. No network and no API calls.

The model is a reader here, not a source. Every test below asks the same question in a
different way: did this come out of the document, or out of the model? That is the only
thing standing between an extracted calendar and an invented one.
"""

import datetime as dt

import pytest

import catalysts
import db
import pdufa
import seed

TODAY = dt.date(2026, 7, 19)

FILING = """
<html><head><style>p{color:red}</style></head><body>
<p>On July 2, 2026, Eli Lilly and Company announced that the U.S. Food and Drug
Administration has accepted its New Drug Application for Retatrutide for the treatment
of obesity. The FDA has set a Prescription Drug User Fee Act (PDUFA) target action date
of March 14, 2027.</p>
</body></html>
"""


def _document():
    return pdufa.strip_html(FILING)


def _reply(**overrides):
    base = {"found": True, "date": "2027-03-14", "product": "Retatrutide",
            "indication": "obesity",
            "quote": "The FDA has set a Prescription Drug User Fee Act (PDUFA) target "
                     "action date of March 14, 2027."}
    base.update(overrides)
    return base


# --- reading the filing ---------------------------------------------------
def test_html_is_reduced_to_prose():
    text = _document()
    assert "PDUFA" in text and "March 14, 2027" in text
    assert "<p>" not in text and "color:red" not in text


def test_a_filing_that_mentions_no_review_is_never_sent():
    """The cheap check runs before the model does, so most 8-Ks cost nothing."""
    assert pdufa.REGULATORY_HINT.search(_document())
    assert not pdufa.REGULATORY_HINT.search(
        "Results of operations for the quarter ended June 30, 2026.")


def test_only_filings_worth_reading_are_candidates():
    assert pdufa.WORTH_READING.search("Material agreement signed, Other events")
    assert not pdufa.WORTH_READING.search("Results of operations")


# --- reading the model ----------------------------------------------------
def test_json_survives_surrounding_prose():
    assert pdufa.parse_reply('Here you go: {"found": false} hope that helps')["found"] is False
    assert pdufa.parse_reply("no json here") is None
    assert pdufa.parse_reply("") is None
    assert pdufa.parse_reply("{oops") is None


def test_a_good_extraction_passes():
    row = pdufa.validate(_reply(), _document(), today=TODAY)
    assert row["date"] == "2027-03-14"
    assert row["product"] == "Retatrutide"
    assert row["indication"] == "obesity"


def test_nothing_found_is_nothing_written():
    assert pdufa.validate({"found": False}, _document(), today=TODAY) is None
    assert pdufa.validate(None, _document(), today=TODAY) is None


# --- the guards that matter ----------------------------------------------
def test_a_product_the_filing_never_names_is_refused():
    """The failure this exists for: a name the model supplied from its own knowledge
    rather than from the document."""
    assert pdufa.validate(_reply(product="Tirzepatide"), _document(),
                          today=TODAY) is None


def test_a_quote_that_is_not_in_the_filing_is_refused():
    """If the model cannot point at where it read the date, it did not read it."""
    invented = "The FDA has set a target action date of March 14, 2027 for this drug."
    assert pdufa.validate(_reply(quote=invented), _document(), today=TODAY) is None


def test_a_date_already_past_is_refused():
    assert pdufa.validate(_reply(date="2026-01-01"), _document(), today=TODAY) is None


def test_a_date_beyond_a_review_window_is_refused():
    """A goal date four years out is a typo or a different kind of date."""
    assert pdufa.validate(_reply(date="2030-03-14"), _document(), today=TODAY) is None


def test_an_unparseable_date_is_refused():
    for bad in ("March 2027", "", None, "2027-13-45"):
        assert pdufa.validate(_reply(date=bad), _document(), today=TODAY) is None


def test_a_missing_product_is_refused():
    assert pdufa.validate(_reply(product=""), _document(), today=TODAY) is None
    assert pdufa.validate(_reply(product=None), _document(), today=TODAY) is None


def test_a_trivially_short_quote_is_refused():
    """A few words match any document by accident."""
    assert pdufa.validate(_reply(quote="the FDA"), _document(), today=TODAY) is None


def test_matching_ignores_whitespace_and_case():
    """The document and the model's echo differ in entities and spacing, and that alone
    must not throw away a good extraction."""
    row = pdufa.validate(
        _reply(quote="the fda has  set a prescription drug user fee act (pdufa) "
                     "TARGET ACTION DATE of March 14, 2027."),
        _document(), today=TODAY)
    assert row is not None


# --- without a key --------------------------------------------------------
def test_no_key_is_reported_not_crashed(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    db_file = tmp_path / "test.db"
    db.init(db_file)
    result = pdufa.extract(db_file, today=TODAY)

    assert result["status"] == "no key"
    assert result["found"] == 0
    assert "ANTHROPIC_API_KEY" in result["detail"]


def test_candidates_are_recent_filings_of_the_right_kind(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    company = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    rows = [
        ("0001", "8-K", "2026-07-01", "Other events", "https://example.com/a.htm"),
        ("0002", "8-K", "2026-07-02", "Results of operations", "https://example.com/b.htm"),
        ("0003", "8-K", "2019-01-01", "Other events", "https://example.com/c.htm"),
        ("0004", "10-K", "2026-07-03", "Other events", "https://example.com/d.htm"),
    ]
    for accession, form, filed, title, url in rows:
        conn.execute(
            "INSERT INTO filings (company_id, form_type, filed_date, accession, title,"
            " url) VALUES (?, ?, ?, ?, ?, ?)",
            (company, form, filed, accession, title, url))
    conn.commit()
    conn.close()

    found = {c["accession"] for c in pdufa.candidates(db_file, today=TODAY)}
    assert found == {"0001"}        # right kind, recent, and worth reading


def test_an_extracted_row_is_marked_machine_written(tmp_path):
    """It lands with is_curated 0, so a later refresh can revise it and the UI can
    show the filing it came from."""
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    catalysts.add_catalyst(db_file, "LLY", "PDUFA", "2027-03-14", "Retatrutide PDUFA",
                           is_curated=0, source_url="https://example.com/a.htm",
                           date_confidence="confirmed")
    rows = catalysts.list_catalysts(db_file, within_days=3650, ticker="LLY")
    assert len(rows) == 1
    assert rows[0]["is_curated"] == 0
    assert rows[0]["source_url"] == "https://example.com/a.htm"


# --- an error that will repeat stops the loop ----------------------------
def test_a_billing_or_auth_failure_is_fatal():
    """It fails identically on the next filing, and each retry costs an EDGAR fetch."""
    class BadRequestError(Exception):
        pass

    assert pdufa.is_fatal(BadRequestError(
        "Error code: 400 - Your credit balance is too low to access the Anthropic API"))
    assert pdufa.is_fatal(Exception("invalid x-api-key"))

    class AuthenticationError(Exception):
        pass

    assert pdufa.is_fatal(AuthenticationError("nope"))


def test_a_one_off_failure_is_not_fatal():
    """A timeout or a bad document is this filing's problem, not the run's."""
    assert not pdufa.is_fatal(TimeoutError("read timed out"))
    assert not pdufa.is_fatal(ValueError("could not parse"))
