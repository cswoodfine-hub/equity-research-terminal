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
