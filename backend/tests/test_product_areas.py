"""Resolving the disease a marketed product treats."""

import db
import product_areas

DIABETES = ("1 INDICATIONS AND USAGE MOUNJARO is indicated as an adjunct to diet and "
            "exercise to improve glycemic control in adults with type 2 diabetes "
            "mellitus.")


def _seed(tmp_path):
    path = str(tmp_path / "areas.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    conn.commit()
    return path, conn


def _asset(conn, brand=None, generic=None):
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    cur = conn.execute(
        "INSERT INTO assets (owner_company_id, brand_name, generic_name, is_marketed)"
        " VALUES (?, ?, ?, 1)", (cid, brand, generic))
    conn.commit()
    return cur.lastrowid


def _label(conn, asset_id, text, setid="s1"):
    conn.execute("INSERT INTO labels (setid, asset_id, effective_time, indications_text)"
                 " VALUES (?, ?, '2026-05-06', ?)", (setid, asset_id, text))
    conn.commit()


def test_reads_the_products_own_label(tmp_path):
    path, conn = _seed(tmp_path)
    asset_id = _asset(conn, brand="Mounjaro", generic="Tirzepatide")
    _label(conn, asset_id, DIABETES)
    conn.close()
    assert product_areas.areas_for(path, [asset_id]) == {asset_id: "Metabolic"}


def test_borrows_the_label_of_another_row_of_the_same_brand(tmp_path):
    path, conn = _seed(tmp_path)
    labelled = _asset(conn, brand="Aromasin")            # label, no approval
    unlabelled = _asset(conn, brand="Aromasin", generic="Exemestane")
    _label(conn, labelled, "INDICATIONS AND USAGE AROMASIN is indicated for early "
                           "breast cancer")
    conn.close()
    assert product_areas.areas_for(path, [unlabelled])[unlabelled] == "Oncology"


def test_falls_back_to_what_its_trials_study(tmp_path):
    path, conn = _seed(tmp_path)
    asset_id = _asset(conn, brand="Retevmo", generic="Selpercatinib")
    conn.execute("INSERT INTO trials (nct_id, asset_id, title, conditions)"
                 " VALUES ('NCT01', ?, 'A study', '[\"Non-Small Cell Lung Cancer\"]')",
                 (asset_id,))
    conn.commit()
    conn.close()
    assert product_areas.areas_for(path, [asset_id])[asset_id] == "Oncology"


def test_falls_back_to_the_ingredient_where_it_names_a_class(tmp_path):
    path, conn = _seed(tmp_path)
    # Humulin R has no label of its own, no sibling with one and no trials.
    asset_id = _asset(conn, brand="Humulin R Pen",
                      generic="Insulin Recombinant Human")
    conn.close()
    assert product_areas.areas_for(path, [asset_id])[asset_id] == "Metabolic"


def test_states_nothing_when_nothing_on_file_says(tmp_path):
    path, conn = _seed(tmp_path)
    asset_id = _asset(conn, brand="Vyndaqel", generic="Tafamidis Meglumine")
    conn.close()
    assert product_areas.areas_for(path, [asset_id])[asset_id] is None


def test_ignores_an_unknown_asset(tmp_path):
    path, conn = _seed(tmp_path)
    conn.close()
    assert product_areas.areas_for(path, [999, None]) == {999: None}
