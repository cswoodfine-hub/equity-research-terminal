"""Patent term extensions: parsing the USPTO's two lists and storing them. No network.

The certificate fixture is the USPTO's file as published through 2026-09-08, whole,
since a .xls cannot be cut without a writer the app does not carry. The application
fixture is rows cut from the five-year list of the same date."""

from pathlib import Path

import db
import pte
from fetchers.pte_uspto import PteFetcher

_FIX = Path(__file__).resolve().parent / "fixtures"
_CERTS = (_FIX / "pte_certs.xls").read_bytes()
_APPS = (_FIX / "pte_applications.xlsx").read_bytes()


def test_patent_key_reads_the_spellings_the_lists_use():
    assert pte.patent_key(6515117.0) == "6515117"
    assert pte.patent_key("RE47739") == "RE47739"
    assert pte.patent_key("RE47739 ") == "RE47739"
    assert pte.patent_key("RE47,739") == "RE47739"
    assert pte.patent_key("5.093.200") == "5093200"
    assert pte.patent_key("4,826, 810") == "4826810"
    assert pte.patent_key("") is None
    assert pte.patent_key("*The expiration date listed") is None


def test_certificates_name_the_compound_patents_an_analyst_established():
    certs = {r["patent"]: r for r in pte.parse_certificates(_CERTS)}
    assert len(certs) > 1000
    # The five rows of data/compound_patent.csv, each the extended patent, each
    # extended to the date the Orange Book lists.
    assert certs["6515117"]["extended_expiry"] == "2025-10-04"      # Farxiga, 5 years
    assert certs["8129343"]["extended_expiry"] == "2031-12-05"      # Ozempic, 1040 days
    assert certs["9474780"]["extended_expiry"] == "2036-05-13"      # Mounjaro
    assert certs["RE47739"]["extended_expiry"] == "2027-03-05"      # Ibrance
    assert certs["8129343"]["trade_name"] == "OZEMPIC (semaglutide)"


def test_a_malformed_original_expiry_is_left_null_not_repaired():
    kynamro = next(r for r in pte.parse_certificates(_CERTS) if r["patent"] == "7511131")
    assert kynamro["original_expiry"] is None          # published as "12/13/22025"
    assert kynamro["extension"] == "412 days"
    assert kynamro["extended_expiry"] is None


def test_extended_expiry_adds_calendar_years_and_days():
    assert pte.extended_expiry("2020-10-04", "5 years") == "2025-10-04"
    assert pte.extended_expiry("2020-02-29", "1 year") == "2021-02-28"
    assert pte.extended_expiry("2023-01-16", "1,509 days") == "2027-03-05"
    assert pte.extended_expiry("2023-01-16", "until approval") is None
    assert pte.extended_expiry(None, "5 years") is None


def test_applications_keep_every_patent_a_holder_applied_on():
    apps = pte.parse_applications(_APPS)
    wayrilz = sorted(r["patent"] for r in apps if r["trade_name"].startswith("WAYRILZ"))
    # Three applications for one product: only one can be granted, so a pending
    # application does not say which patent holds the molecule.
    assert wayrilz == ["8940744", "9266895", "9994576"]
    assert all(r["filed"] == "2025-10-27" for r in apps if r["patent"] in wayrilz)


def test_fetcher_replaces_the_table(monkeypatch, tmp_path):
    db_file = tmp_path / "t.db"
    db.init(db_file)
    fetcher = PteFetcher(db_file)
    files = {pte.CERTIFICATES_URL: _CERTS, pte.APPLICATIONS_URL: _APPS}
    monkeypatch.setattr(fetcher, "_get", files.__getitem__)
    for _ in range(2):                                  # twice: replaced, not appended
        rows = fetcher.normalise(fetcher.fetch())
        fetcher.snapshot(rows)
        fetcher.upsert(rows)
    conn = db.get_connection(db_file)
    try:
        counts = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM patent_term_extensions GROUP BY kind").fetchall())
    finally:
        conn.close()
    assert counts["application"] == 4
    assert counts["certificate"] == len(pte.parse_certificates(_CERTS))


def test_an_empty_certificate_list_fails_rather_than_emptying_the_table(monkeypatch,
                                                                        tmp_path):
    fetcher = PteFetcher(tmp_path / "t.db")
    monkeypatch.setattr(pte, "parse_certificates", lambda payload: [])
    monkeypatch.setattr(fetcher, "_get", lambda url: b"")
    try:
        fetcher.fetch()
    except RuntimeError as exc:
        assert "no rows" in str(exc)
    else:
        raise AssertionError("an empty certificate list must not pass")
