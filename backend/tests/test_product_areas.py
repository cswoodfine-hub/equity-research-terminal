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


# --- a pipeline asset: the disease it is modelled in, not every trial it has run -------
def _indication(conn, asset_id, name, *, is_lead=0, phase="Phase 3"):
    cur = conn.execute("INSERT INTO indications (name) VALUES (?)", (name,))
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase, is_lead)"
                 " VALUES (?, ?, ?, ?)", (asset_id, cur.lastrowid, phase, is_lead))
    conn.commit()
    return cur.lastrowid


def _trial(conn, asset_id, nct, conditions):
    conn.execute("INSERT INTO trials (nct_id, asset_id, conditions) VALUES (?, ?, ?)",
                 (nct, asset_id, conditions))
    conn.commit()


def _assumption(conn, asset_id, indication_id, key="penetration_peak_pct", value=0.02):
    conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                 " key, value) VALUES (?, ?, 'US', 'base', ?, ?)",
                 (asset_id, indication_id, key, value))
    conn.commit()


def test_the_modelled_disease_beats_every_trial_the_asset_has_run(tmp_path):
    """Tozorakimab's trials are mostly SARS-CoV-2 and the line in the book is chronic
    obstructive pulmonary disease. Read as one blob of conditions the asset came back as
    an infectious disease and drew its success rate from the wrong precedent table."""
    path, conn = _seed(tmp_path)
    asset_id = _asset(conn, generic="Tozorakimab")
    copd = _indication(conn, asset_id, "Pulmonary Disease, Chronic Obstructive")
    _indication(conn, asset_id, "Severe Acute Respiratory Syndrome", is_lead=1)
    _trial(conn, asset_id, "NCT1", "COVID-19|SARS-CoV-2 Infection|Viral Pneumonia")
    _trial(conn, asset_id, "NCT2", "COVID-19|Acute Respiratory Distress Syndrome")
    _assumption(conn, asset_id, copd)
    conn.close()
    assert product_areas.areas_for(path, [asset_id]) == {asset_id: "Respiratory"}


def test_the_lead_flag_does_not_decide_it(tmp_path):
    """Retatrutide and cagrilintide are both flagged lead in cardiovascular disease, on
    their outcomes trials, while the line the book carries for each is obesity. The lead
    flag is the indication mapper's, not the analyst's."""
    path, conn = _seed(tmp_path)
    asset_id = _asset(conn, generic="Retatrutide")
    _indication(conn, asset_id, "Cardiovascular Diseases", is_lead=1)
    obesity = _indication(conn, asset_id, "Obesity")
    _assumption(conn, asset_id, obesity)
    conn.close()
    assert product_areas.areas_for(path, [asset_id]) == {asset_id: "Metabolic"}


def test_an_asset_modelled_in_nothing_still_falls_back_to_its_trials(tmp_path):
    """Nothing changes for an asset with no modelled indication: the trials still answer,
    so the 384 assets this does not apply to behave as they did."""
    path, conn = _seed(tmp_path)
    asset_id = _asset(conn, generic="Some Compound")
    _indication(conn, asset_id, "Pulmonary Disease, Chronic Obstructive", is_lead=1)
    _trial(conn, asset_id, "NCT9", "Breast Neoplasms|Carcinoma, Ductal")
    conn.close()
    assert product_areas.areas_for(path, [asset_id]) == {asset_id: "Oncology"}
