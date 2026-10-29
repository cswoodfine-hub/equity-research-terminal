"""The molecule patent from the USPTO's extensions, and generic launches from the FDA
Paragraph IV list, as the LOE resolver reads them."""

from __future__ import annotations

import pytest

import db
import loe


@pytest.fixture(autouse=True)
def _no_real_curated_files(tmp_path, monkeypatch):
    """Real brand names, so no committed curated file may reach these fixtures."""
    monkeypatch.setattr(loe, "CURATED_DISCLOSED", tmp_path / "none.csv")
    monkeypatch.setattr(loe, "CMS_DESELECTIONS", tmp_path / "none-cms.csv")
    monkeypatch.setattr(loe, "CURATED_COMPOUND", tmp_path / "none-compound.csv")


def _row(identifier, expiry, kind):
    return {"identifier": identifier, "expiry_date": expiry, "patent_kind": kind}


def test_the_extended_patent_is_the_molecule_with_its_paediatric_extension():
    """Rinvoq: RE47221, upadacitinib, extended to 2033; the latest substance patent, a
    crystal form, runs to 2036."""
    rows = [_row("RE47221", "2033-02-16", "substance"),
            _row("RE47221*PED", "2033-08-16", None),
            _row("11186584", "2036-10-17", "substance")]
    assert loe.molecule_patent(rows, {"RE47221"}) == ("2033-08-16", "RE47221")
    # The base date is unchanged: the extended patent is the floor of the range.
    assert loe.compound_expiry(rows, None, {"RE47221"}) == ("2036-10-17", "11186584")


def test_a_combination_takes_its_latest_extended_component():
    rows = [_row("7176220", "2027-02-27", "substance"),
            _row("8148374", "2029-09-03", "substance"),
            _row("9000000", "2032-08-15", "substance")]
    assert loe.molecule_patent(rows, {"7176220", "8148374"}) == ("2029-09-03", "8148374")


def test_no_extended_patent_listed_gives_no_floor():
    rows = [_row("111", "2030-01-01", "substance")]
    assert loe.molecule_patent(rows, {"999"}) == (None, None)
    assert loe.molecule_patent(rows, set()) == (None, None)


def _db(tmp_path):
    path = str(tmp_path / "mol.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'MRK', 'Merck'),"
                 " (2, 'BMY', 'BMS'), (3, 'NVS', 'Novartis'), (4, 'ABBV', 'AbbVie')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, internal_code,"
                 " is_marketed) VALUES (10, 1, 'Januvia', 'NDA21995', 1),"
                 " (11, 2, 'Revlimid', 'NDA21880', 1), (12, 3, 'Tasigna', 'NDA22068', 1),"
                 " (13, 4, 'Rinvoq', 'NDA211675', 1)")
    conn.execute("INSERT INTO exclusivities (asset_id, region, protection_type,"
                 " identifier, expiry_date, patent_kind, source) VALUES"
                 " (10, 'US', 'patent', '7326708', '2026-11-24', 'substance', 'orange_book'),"
                 " (13, 'US', 'patent', 'RE47221', '2033-02-16', 'substance', 'orange_book'),"
                 " (13, 'US', 'patent', 'RE47221*PED', '2033-08-16', NULL, 'orange_book'),"
                 " (13, 'US', 'patent', '11186584', '2036-10-17', 'substance', 'orange_book')")
    conn.execute("INSERT INTO patent_term_extensions (patent, kind) VALUES"
                 " ('RE47221', 'certificate')")
    conn.execute("INSERT INTO paragraph_iv_list (application_number, rld_name,"
                 " first_marketing) VALUES ('NDA21995', 'Januvia', '2026-05-28'),"
                 " ('NDA21995', 'Januvia', '2026-07-01'),"
                 " ('NDA21880', 'Revlimid', '2022-03-03'),"
                 " ('NDA22068', 'Tasigna', '2025-05-23')")
    conn.commit()
    return conn


def _disclose(monkeypatch, tmp_path, body):
    path = tmp_path / "disclosed.csv"
    path.write_text("ticker,brand,loe,basis,note\n" + body)
    monkeypatch.setattr(loe, "CURATED_DISCLOSED", path)


def test_a_generic_on_sale_pulls_a_patent_date_earlier(tmp_path):
    got = loe.for_assets(_db(tmp_path), [10])[10]
    assert got["date"] == "2026-05-28"                    # the earliest strength
    assert got["basis"] == "generic marketed (2026-05-28, FDA Paragraph IV list)"
    assert got["past"] is True


def test_a_filer_disclosure_stands_over_a_volume_limited_launch(tmp_path, monkeypatch):
    """Revlimid's generics launched in 2022 under volume limits; BMS dates the cliff to
    2026-01-31, when they end."""
    _disclose(monkeypatch, tmp_path, "BMY,Revlimid,2026-01-31,BMS 10-K,\n")
    got = loe.for_assets(_db(tmp_path), [11])[11]
    assert got["date"] == "2026-01-31"
    assert got["basis"].startswith("BMS 10-K")


def test_a_disclosed_loss_with_no_date_takes_the_launch_date(tmp_path, monkeypatch):
    """Novartis says Tasigna's generics are on the market without saying since when; the
    list says 2025-05-23."""
    _disclose(monkeypatch, tmp_path, "NVS,Tasigna,expired,Novartis 20-F,\n")
    got = loe.for_assets(_db(tmp_path), [12])[12]
    assert got["date"] == "2025-05-23"


def test_the_molecule_floor_is_reported_without_moving_the_date(tmp_path):
    got = loe.for_assets(_db(tmp_path), [13])[13]
    assert got["date"] == "2036-10-17"
    assert got["basis"] == "drug substance patent"
    assert (got["molecule_date"], got["molecule_patent"]) == ("2033-08-16", "RE47221")
