"""Every candidate for one indication, compared on what it is and what its trials posted."""

import json

import pytest

import db
import landscape as L


@pytest.mark.parametrize("condition, indication, ok", [
    ("Type 2 Diabetes", "Diabetes Mellitus, Type 2", True),
    ("Type 1 Diabetes", "Diabetes Mellitus, Type 2", False),        # the subtype guard
    ("Non-Small Cell Lung Cancer", "Carcinoma, Non-Small-Cell Lung", True),
    ("Breast Cancer", "Breast Neoplasms", True),                       # cancer is a neoplasm
    ("Psoriatic Arthritis", "Arthritis, Rheumatoid", False),
    ("Ulcerative Colitis", "Colitis, Ulcerative", True),
    ("Healthy Volunteers", "Obesity", False),
    ("Lung Cancer", "Carcinoma, Non-Small-Cell Lung", False),          # broader, not the same
])
def test_a_free_text_condition_meets_its_indication(condition, indication, ok):
    assert L.condition_matches(condition, indication) is ok


def test_the_same_measure_in_other_words_and_at_another_week_is_one_endpoint():
    a = L.endpoint_key("Percent Change From Baseline in Body Weight at Week 32", "percent change")
    b = L.endpoint_key("Percentage Change in Body Weight From Baseline to Week 68", "Percent change")
    c = L.endpoint_key("Change From Baseline in Body Weight at Week 32", "kg")
    assert a == b
    assert a != c                       # a different unit is a different measure


def test_the_time_point_is_the_last_one_named_in_weeks():
    assert L.weeks_of("Change at Week 32", "Baseline, Week 32") == 32
    assert L.weeks_of(None, "Baseline up to 12 months") == pytest.approx(52.1, abs=0.2)
    assert L.weeks_of("Change in HbA1c", None) is None


def test_a_placebo_arm_that_names_the_drug_is_the_drugs_arm():
    assert L.is_placebo("Placebo", ["tirzepatide"])
    assert L.is_placebo("Placebo + Metformin", ["tirzepatide"])
    assert not L.is_placebo("Tirzepatide 15 mg + Placebo", ["Tirzepatide"])


def _book(tmp_path):
    path = str(tmp_path / "land.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1, 'LLY', 'Lilly')")
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (2, 'NVO', 'Novo')")
    conn.execute("INSERT INTO indications (id, name) VALUES (1, 'Obesity')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed) VALUES (1, 1, 'Tirzepatide', 'Zepbound', 1)")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (2, 2, 'Cagrilintide', 0)")
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase)"
                 " VALUES (2, 1, 'Phase 3')")
    # The incumbent arrives through a completed trial whose first condition is obesity.
    conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title,"
                 " phase, conditions, completion_date, enrollment) VALUES"
                 " ('NCT1', 1, 1, 'SURMOUNT-1', 'Phase 3', ?, '2022-04-01', 2539)",
                 (json.dumps(["Obesity"]),))
    # A trial listing obesity only in passing does not bring its drug in.
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, is_marketed)"
                 " VALUES (3, 1, 'Baricitinib', 1)")
    conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title,"
                 " phase, conditions) VALUES ('NCT2', 1, 3, 'A study in arthritis',"
                 " 'Phase 3', ?)", (json.dumps(["Arthritis, Rheumatoid", "Obesity"]),))
    for gid, title, value, n in (("OG000", "Placebo", -2.4, 643),
                                 ("OG001", "Tirzepatide 15 mg", -20.9, 630)):
        conn.execute("INSERT INTO trial_result_outcomes (nct_id, outcome_index, outcome_type,"
                     " title, time_frame, unit, param_type, group_id, group_title, value,"
                     " n_analysed) VALUES ('NCT1', 0, 'PRIMARY',"
                     " 'Percent Change From Baseline in Body Weight', 'Baseline, Week 72',"
                     " 'percent change', 'LEAST_SQUARES_MEAN', ?, ?, ?, ?)",
                     (gid, title, value, n))
    conn.execute("INSERT INTO trial_result_analyses (nct_id, outcome_index, group_ids,"
                 " param_value, p_value) VALUES ('NCT1', 0, ?, -18.5, '<0.001')",
                 (json.dumps(["OG000", "OG001"]),))
    for gid, title, ser, risk, wd in (("EG000", "Placebo", 44, 643, 17),
                                      ("EG001", "Tirzepatide 15 mg", 40, 630, 39)):
        conn.execute("INSERT INTO trial_result_safety (nct_id, group_id, group_title,"
                     " serious_affected, serious_at_risk, deaths_affected, deaths_at_risk,"
                     " withdrawn_ae) VALUES ('NCT1', ?, ?, ?, ?, 0, ?, ?)",
                     (gid, title, ser, risk, risk, wd))
    for gid, aff, risk in (("EG000", 61, 643), ("EG001", 195, 630)):
        conn.execute("INSERT INTO trial_result_events (nct_id, term, serious, group_id,"
                     " affected, at_risk) VALUES ('NCT1', 'Nausea', 0, ?, ?, ?)",
                     (gid, aff, risk))
    conn.execute("INSERT INTO trial_result_fetches (nct_id, has_results) VALUES ('NCT1', 1)")
    conn.execute("INSERT INTO labels (asset_id, setid, indications_text) VALUES (1, 's1',"
                 " 'ZEPBOUND is indicated to reduce excess body weight in adults with obesity')")
    conn.execute("INSERT INTO asset_pharmacology (asset_id, kind, value, detail, source)"
                 " VALUES (1, 'mechanism', 'Glucagon-like peptide 1 receptor agonist',"
                 " 'AGONIST', 'chembl')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def land(tmp_path, monkeypatch):
    path = _book(tmp_path)
    monkeypatch.setattr(L, "_big_pharma_ids", lambda conn: {1, 2})
    monkeypatch.setattr(L, "_model_lines", lambda db_path, tickers, verdict_for=None: {})
    return L.landscape(path, 1)


def test_the_landscape_takes_the_incumbent_by_its_trial_and_the_rival_by_its_pipeline(land):
    names = {c["name"]: c for c in land["candidates"]}
    assert set(names) == {"Zepbound", "Cagrilintide"}          # not baricitinib
    assert names["Zepbound"]["linked_by"] == ["trial"]
    assert names["Zepbound"]["stage"] == "Marketed"
    assert names["Cagrilintide"]["stage"] == "Phase 3"
    assert names["Zepbound"]["mechanisms"][0]["value"].startswith("Glucagon-like")


def test_each_arm_reads_against_the_placebo_of_its_own_trial(land):
    group = land["endpoints"][0]
    row = group["rows"][0]
    assert row["arm"] == "Tirzepatide 15 mg" and row["arm_is_drug"]
    assert row["delta"] == pytest.approx(-18.5)
    assert row["p_value"] == "<0.001" and row["weeks"] == 72


def test_safety_pools_the_drug_arms_against_placebo_in_the_same_trials(land):
    s = next(x for x in land["safety"] if x["name"] == "Zepbound")
    assert s["serious_rate"] == pytest.approx(40 / 630)
    assert s["placebo_serious_rate"] == pytest.approx(44 / 643)
    assert s["withdrawn_rate"] == pytest.approx(39 / 630)
    nausea = s["top_events"][0]
    assert nausea["term"] == "Nausea"
    assert nausea["rate"] == pytest.approx(195 / 630)
    assert nausea["placebo_rate"] == pytest.approx(61 / 643)


def test_a_marketed_drug_is_marketed_here_only_where_its_label_names_the_disease(tmp_path, monkeypatch):
    path = _book(tmp_path)
    conn = db.get_connection(path)
    conn.execute("UPDATE labels SET indications_text = 'indicated for type 2 diabetes'")
    conn.commit()
    conn.close()
    monkeypatch.setattr(L, "_big_pharma_ids", lambda conn: {1, 2})
    monkeypatch.setattr(L, "_model_lines", lambda db_path, tickers, verdict_for=None: {})
    zep = next(c for c in L.landscape(path, 1)["candidates"] if c["name"] == "Zepbound")
    assert zep["stage"] == "Marketed · Phase 3 here" and not zep["on_label"]


def test_the_comparator_is_placebo_else_the_control_else_the_other_of_two_arms():
    arm = lambda t: {"group_title": t, "group_description": ""}
    assert L.comparator([arm("Pembrolizumab"), arm("Placebo")], ["pembrolizumab"])[1] == "placebo"
    assert L.comparator([arm("Durvalumab"), arm("Sub-study A: SoC")], ["durvalumab"])[1] == "control"
    ref, kind = L.comparator([arm("Pembrolizumab 2 mg/kg"), arm("Docetaxel 75 mg/m^2")],
                             ["pembrolizumab"])
    assert kind == "comparator" and ref["group_title"].startswith("Docetaxel")
    assert L.comparator([arm("Arm A"), arm("Arm B"), arm("Arm C")], ["x"]) == (None, None)
