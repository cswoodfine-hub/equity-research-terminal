"""A revenue line joined to the application whose exclusivity governs it."""

import datetime as dt

import db
import loe
import loe_link


def _db(tmp_path):
    path = str(tmp_path / "link.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'SNY', 'Sanofi'),"
                 " (2, 'REGN', 'Regeneron'), (3, 'PFE', 'Pfizer'), (4, 'AZN', 'Astra')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " internal_code) VALUES"
                 " (10, 1, 'Dupixent', 1, NULL),"
                 " (11, 2, 'Dupixent', 1, 'BLA761055'),"
                 " (12, 3, 'Xtandi', 1, NULL),"
                 " (13, 3, 'Comirnaty', 1, 'BLA125742'),"
                 " (14, 4, 'Zoladex', 1, NULL)")
    conn.execute("INSERT INTO exclusivities (asset_id, region, protection_type,"
                 " identifier, expiry_date, source) VALUES"
                 " (11, 'US', 'reference product exclusivity', 'ref', '2029-03-28', 't'),"
                 " (11, 'US', 'patent', '9034', '2031-01-25', 't')")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                 " application_number, source) VALUES"
                 " (14, 'US', 'FDA', '1989-12-29', 'NDA019726', 't')")
    conn.commit()
    return conn


def _links(tmp_path):
    path = tmp_path / "loe_link.csv"
    path.write_text("# comment\nticker,asset,application_number,note\n"
                    "SNY,Dupixent,BLA761055,partner\n"
                    "PFE,Xtandi,NDA203415,astellas\n"
                    "PFE,Nobody,NDA1,not on file\n")
    return path


def test_the_file_joins_only_assets_on_file(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(loe_link, "LINK_FILE", _links(tmp_path))
    links = loe_link.load(conn)
    assert set(links) == {10, 12}
    assert links[10]["code"] == "BLA761055" and links[12]["code"] == "NDA203415"


def test_a_line_reads_the_holders_resolved_date(tmp_path, monkeypatch):
    """Sanofi's Dupixent has no rows of its own; it reads Regeneron's, and says so."""
    conn = _db(tmp_path)
    monkeypatch.setattr(loe_link, "LINK_FILE", _links(tmp_path))
    got = loe.for_assets(conn, [10])
    assert got[10]["date"] == "2031-01-25"
    assert got[10]["via"] == 11
    assert "via BLA761055 (Dupixent)" in got[10]["basis"]
    # The holder itself is unchanged, and a line whose holder has no date stays empty.
    assert loe.for_assets(conn, [11])[11]["date"] == "2031-01-25"
    assert 12 not in loe.for_assets(conn, [12]) or not loe.for_assets(conn, [12]).get(12, {}).get("date")


def test_attach_targets_names_lines_with_no_holder_and_coded_assets(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(loe_link, "LINK_FILE", _links(tmp_path))
    targets = loe_link.attach_targets(conn)
    assert targets["NDA203415"] == [12]          # nothing on file holds Astellas's NDA
    assert "BLA761055" in targets and 10 not in targets["BLA761055"]   # Regeneron holds it
    assert targets["BLA125742"] == [13]          # an asset already carrying the code


def test_an_elapsed_patent_term_is_an_loe_in_the_past(tmp_path, monkeypatch):
    """Zoladex was approved in 1989. No patent filed before that can be in force, so the
    LOE is past whether or not the book lists anything."""
    conn = _db(tmp_path)
    monkeypatch.setattr(loe_link, "LINK_FILE", _links(tmp_path))
    got = loe.for_assets(conn, [14])[14]
    # Past, and no date: the rule establishes that protection is gone, not when.
    assert got["past"] is True and got["date"] is None
    assert got["basis"].startswith("lapsed by 2014 at the latest")


def test_sync_writes_an_approval_once_from_openfda(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    monkeypatch.setattr(loe_link, "LINK_FILE", _links(tmp_path))
    calls = []

    def fake(number):
        calls.append(number)
        if number == "NDA203415":
            return {"application_number": "NDA203415", "sponsor": "ASTELLAS",
                    "approval_date": "2012-08-31", "brand": "XTANDI"}
        return None

    got = loe_link.sync_approvals(conn, fetch=fake)
    assert got["written"] == 1 and got["unknown"] == ["BLA761055"]
    row = conn.execute("SELECT approval_date, application_number, source FROM approvals"
                       " WHERE asset_id = 12").fetchone()
    assert (row["approval_date"], row["application_number"]) == ("2012-08-31", "NDA203415")
    assert row["source"] == loe_link.LINK_SOURCE
    # No modality is stamped from the application type.
    assert conn.execute("SELECT modality FROM assets WHERE id = 12").fetchone()[0] is None
    # A second run touches nothing that already has an approval.
    again = loe_link.sync_approvals(conn, fetch=fake)
    assert again["written"] == 0 and again["skipped"] == 1


def test_holders_match_either_form_of_the_code(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " internal_code) VALUES (15, 3, 'Adcirca', 1, 'NDA022332')")
    conn.commit()
    assert loe_link.holders(conn, "NDA22332") == [15]
    assert loe_link.holders(conn, "NDA22332", exclude=(15,)) == []


def test_a_line_inherits_a_dateless_past_loss_from_its_holder(tmp_path, monkeypatch):
    """UTHR's Adcirca reads PFE's Adcirca, whose loss comes from an elapsed-term rule.
    The rules now run before links, so the line inherits it rather than ending with
    no LOE and a perpetuity."""
    conn = _db(tmp_path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (5, 'UTHR', 'United')")
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " internal_code) VALUES (20, 3, 'Adcirca', 1, 'NDA22332'),"
                 " (21, 5, 'Adcirca', 1, NULL)")
    conn.execute("INSERT INTO approvals (asset_id, region, agency, approval_date,"
                 " application_number, source) VALUES (20, 'US', 'FDA', '1990-05-22',"
                 " 'NDA022332', 't')")
    conn.commit()
    path = tmp_path / "l.csv"
    path.write_text("ticker,asset,application_number,note\nUTHR,Adcirca,NDA022332,x\n")
    monkeypatch.setattr(loe_link, "LINK_FILE", path)
    got = loe.for_assets(conn, [21])[21]
    assert got["past"] is True and got["via"] == 20


def test_two_lines_naming_each_other_do_not_loop(tmp_path, monkeypatch):
    conn = _db(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " internal_code) VALUES (30, 3, 'Alpha', 1, 'NDA200002'),"
                 " (31, 3, 'Beta', 1, 'NDA200001')")
    conn.commit()
    path = tmp_path / "l.csv"
    path.write_text("ticker,asset,application_number,note\n"
                    "PFE,Alpha,NDA200001,x\nPFE,Beta,NDA200002,x\n")
    monkeypatch.setattr(loe_link, "LINK_FILE", path)
    got = loe.for_assets(conn, [30, 31])       # would raise RecursionError before
    assert 30 not in got and 31 not in got


def test_a_non_reference_product_takes_no_bpcia_floor(tmp_path, monkeypatch):
    """A biosimilar is not a reference product: a floor-based date is dropped rather
    than protecting Inflectra to 2028 against competition since 2016."""
    conn = _db(tmp_path)
    conn.execute("INSERT INTO assets (id, owner_company_id, brand_name, is_marketed,"
                 " internal_code) VALUES (40, 3, 'Inflectra', 1, NULL)")
    conn.execute("INSERT INTO biologic_loe (asset_id, loe_year, loe_date, basis,"
                 " floor_year) VALUES (40, 2028, '2028-06-30', 'statutory floor', 2028)")
    conn.commit()
    path = tmp_path / "l.csv"
    path.write_text("ticker,asset,application_number,note,reference_product\n"
                    "PFE,Inflectra,BLA125544,biosimilar,0\n")
    monkeypatch.setattr(loe_link, "LINK_FILE", path)
    assert 40 not in loe.for_assets(conn, [40])
    path.write_text("ticker,asset,application_number,note,reference_product\n"
                    "PFE,Inflectra,BLA125544,biosimilar,\n")
    assert loe.for_assets(conn, [40])[40]["date"] == "2028-12-31"
