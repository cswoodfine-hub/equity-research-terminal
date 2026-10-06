"""The CMS brand matching every CMS reader shares (cms.py). No network."""

from __future__ import annotations

import cms
import db


def _db(tmp_path):
    path = str(tmp_path / "cms.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'BMY','BMS'),"
                 " (2,'PFE','Pfizer'), (3,'AMGN','Amgen'), (4,'XYZ','Other')")
    conn.execute("""INSERT INTO assets (id, owner_company_id, brand_name, generic_name)
        VALUES (10,1,'Eliquis','Apixaban'), (11,2,'Eliquis','Apixaban'),
               (12,3,'Repatha','Evolocumab'), (13,3,'Crestor','Rosuvastatin'),
               (14,4,'Crestor','Something Else')""")
    conn.commit()
    return path, conn


def test_a_co_marketed_brand_belongs_to_both_owners(tmp_path):
    _, conn = _db(tmp_path)
    try:
        assets = cms.brand_assets(conn)
        single = cms.brand_map(conn)
    finally:
        conn.close()
    assert assets["eliquis"] == [10, 11]
    assert single["eliquis"] == 10                 # the single map is unchanged
    # Same brand name, different molecule: the second asset gets nothing.
    assert assets["crestor"] == [13]


def test_match_brand_reads_a_container_as_its_brand(tmp_path):
    _, conn = _db(tmp_path)
    try:
        assets = cms.brand_assets(conn)
    finally:
        conn.close()
    assert cms.match_brand("Repatha Sureclick", assets) == ([12], "repatha")
    assert cms.match_brand("Eliquis*", assets) == ([10, 11], "eliquis")
    assert cms.match_brand("Lyrica CR", assets) == (None, "lyrica cr")


def test_a_generic_row_is_one_named_by_its_ingredient():
    assert cms.is_generic_row("Rosuvastatin Calcium", "Rosuvastatin Calcium")
    assert cms.is_generic_row("Apixaban*", "apixaban")
    assert not cms.is_generic_row("Eliquis", "Apixaban")
    assert not cms.is_generic_row("Eliquis", "")       # nothing to compare: not generic
