"""Routing one molecule's trials to the brand whose label covers them."""

import brand_split
import db

MOUNJARO_LABEL = ("MOUNJARO is indicated as an adjunct to diet and exercise to improve "
                  "glycemic control in adults with type 2 diabetes mellitus.")
ZEPBOUND_LABEL = ("ZEPBOUND is indicated to reduce excess body weight in adults with "
                  "obesity or adults with overweight, and to treat moderate to severe "
                  "obstructive sleep apnea in adults with obesity.")


def test_covers_reads_the_inverted_registry_form():
    # "Diabetes Mellitus, Type 2" is how the registry writes type 2 diabetes mellitus.
    assert brand_split.covers(MOUNJARO_LABEL, "Diabetes Mellitus, Type 2")
    assert brand_split.covers(MOUNJARO_LABEL, "Type 2 Diabetes")
    assert not brand_split.covers(MOUNJARO_LABEL, "Obesity")
    assert brand_split.covers(ZEPBOUND_LABEL, "Obstructive Sleep Apnea")
    # Type 1 is not type 2, and a label that never says it does not cover it.
    assert not brand_split.covers(MOUNJARO_LABEL, "Type 1 Diabetes")


def test_the_first_condition_decides():
    labels = {31: MOUNJARO_LABEL, 13: ZEPBOUND_LABEL}
    # Listed under diabetes first, so it is the diabetes brand's trial even though both
    # labels cover something in the list.
    assert brand_split.decide(
        labels, ["Diabetes Mellitus, Type 2", "Obesity", "Overweight"]) == 31
    assert brand_split.decide(labels, ["Obesity", "Type 2 Diabetes"]) == 13


def test_falls_back_to_counting_when_the_first_names_neither():
    labels = {31: MOUNJARO_LABEL, 13: ZEPBOUND_LABEL}
    assert brand_split.decide(
        labels, ["Psoriasis", "Overweight", "Obesity"]) == 13


def test_decides_nothing_when_no_label_covers_it():
    labels = {31: MOUNJARO_LABEL, 13: ZEPBOUND_LABEL}
    assert brand_split.decide(labels, ["Metabolic Dysfunction-Associated Steatosis"]) is None
    assert brand_split.decide(labels, []) is None


def test_decides_nothing_when_both_labels_cover_it_equally():
    labels = {1: "indicated for obesity", 2: "indicated for obesity"}
    assert brand_split.decide(labels, ["Obesity"]) is None


def test_base_brand_is_the_plain_product():
    assert brand_split.base_brand({1: "rinvoq lq", 2: "rinvoq"}) == 2
    # Two different products, neither a presentation of the other.
    assert brand_split.base_brand({1: "mounjaro", 2: "zepbound"}) is None
    # The same brand filed twice names no base.
    assert brand_split.base_brand({1: "zithromax", 2: "zithromax"}) is None


def _seed(tmp_path):
    path = str(tmp_path / "split.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    ids = {}
    for brand, label in (("Mounjaro", MOUNJARO_LABEL), ("Zepbound", ZEPBOUND_LABEL)):
        conn.execute(
            "INSERT INTO assets (owner_company_id, brand_name, generic_name,"
            "                    is_marketed) VALUES (?, ?, 'Tirzepatide', 1)",
            (cid, brand))
        ids[brand] = conn.execute("SELECT id FROM assets WHERE brand_name = ?",
                                  (brand,)).fetchone()["id"]
        conn.execute("INSERT INTO labels (setid, asset_id, effective_time,"
                     "                    indications_text)"
                     " VALUES (?, ?, '2026-05-06', ?)",
                     (f'setid-{brand}', ids[brand], label))
    conn.commit()
    return path, conn, ids


def test_moves_a_diabetes_trial_to_the_diabetes_brand(tmp_path):
    path, conn, ids = _seed(tmp_path)
    for nct, conditions in (("NCT01", '["Type 2 Diabetes"]'),
                            ("NCT02", '["Obesity", "Overweight"]')):
        conn.execute("INSERT INTO trials (nct_id, asset_id, title, conditions)"
                     " VALUES (?, ?, 'A study of tirzepatide', ?)",
                     (nct, ids["Zepbound"], conditions))     # both start on one brand
    conn.commit()
    conn.close()

    result = brand_split.split(path)
    assert result["moved"] == 1

    conn = db.get_connection(path)
    where = dict(conn.execute("SELECT nct_id, asset_id FROM trials"))
    conn.close()
    assert where["NCT01"] == ids["Mounjaro"]
    assert where["NCT02"] == ids["Zepbound"]

    # Running it again decides the same way and moves nothing.
    assert brand_split.split(path)["moved"] == 0


def test_a_curated_mapping_outranks_the_label(tmp_path):
    path, conn, ids = _seed(tmp_path)
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, conditions)"
                 " VALUES ('NCT03', ?, 'A study', '[\"Type 2 Diabetes\"]')",
                 (ids["Zepbound"],))
    conn.execute("INSERT INTO trial_asset_map (nct_id, asset_id, note)"
                 " VALUES ('NCT03', ?, 'analyst says Zepbound')", (ids["Zepbound"],))
    conn.commit()
    conn.close()

    assert brand_split.split(path)["moved"] == 0

    conn = db.get_connection(path)
    assert conn.execute("SELECT asset_id FROM trials").fetchone()[0] == ids["Zepbound"]
    conn.close()


def _pair(conn, asset_id, name):
    row = conn.execute("SELECT id FROM indications WHERE name = ?", (name,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO indications (name) VALUES (?)", (name,))
        row = conn.execute("SELECT id FROM indications WHERE name = ?", (name,)).fetchone()
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, region)"
                 " VALUES (?, ?, 'US')", (asset_id, row["id"]))
    return conn.execute("SELECT id FROM asset_indications WHERE asset_id = ?"
                        "   AND indication_id = ?", (asset_id, row["id"])).fetchone()["id"]


def _readout(conn, cid, asset_id, nct, pair):
    conn.execute("INSERT INTO catalysts (company_id, asset_id, asset_indication_id,"
                 " catalyst_type, expected_date, title, source_url, status)"
                 " VALUES (?, ?, ?, 'data readout', '2027-10', 'Phase 3',"
                 " ?, 'pending')",
                 (cid, asset_id, pair, "https://clinicaltrials.gov/study/" + nct))


def test_a_readout_follows_its_study_to_the_brand_it_moved_to(tmp_path):
    """SURMOUNT-MMO's readout stayed on Mounjaro's obesity row after its study moved to
    Zepbound, and the layer test then asked for an obesity model Mounjaro does not have."""
    path, conn, ids = _seed(tmp_path)
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    wrong = _pair(conn, ids["Mounjaro"], "Obesity")
    right = _pair(conn, ids["Zepbound"], "Obesity")
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, conditions)"
                 " VALUES ('NCT05556512', ?, 'SURMOUNT-MMO', '[\"Obesity\"]')",
                 (ids["Mounjaro"],))
    _readout(conn, cid, ids["Zepbound"], "NCT05556512", wrong)
    conn.commit(); conn.close()

    assert brand_split.split(path)["moved"] == 1
    conn = db.get_connection(path)
    got = conn.execute("SELECT asset_indication_id FROM catalysts").fetchone()[0]
    conn.close()
    assert got == right


def test_a_readout_whose_disease_the_new_brand_lacks_is_let_go(tmp_path):
    """Left on the old brand's pair it would be valued against a product the study is not
    about; unlinked, the linker can try again and the row says it is unlinked."""
    path, conn, ids = _seed(tmp_path)
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    wrong = _pair(conn, ids["Mounjaro"], "Obesity")
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, conditions)"
                 " VALUES ('NCT09', ?, 'A study', '[\"Obesity\"]')", (ids["Mounjaro"],))
    _readout(conn, cid, ids["Zepbound"], "NCT09", wrong)
    conn.commit(); conn.close()

    brand_split.split(path)
    conn = db.get_connection(path)
    got = conn.execute("SELECT asset_indication_id FROM catalysts").fetchone()[0]
    conn.close()
    assert got is None
