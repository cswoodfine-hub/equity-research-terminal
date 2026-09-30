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
    assert set(names) == {"Tirzepatide", "Cagrilintide"}       # not baricitinib
    assert names["Tirzepatide"]["brands"] == ["Zepbound"]      # the compound, its brand
    assert names["Tirzepatide"]["linked_by"] == ["trial"]
    assert names["Tirzepatide"]["stage"] == "Marketed"
    assert names["Cagrilintide"]["stage"] == "Phase 3"
    assert names["Tirzepatide"]["mechanisms"][0]["value"].startswith("Glucagon-like")


def test_each_arm_reads_against_the_placebo_of_its_own_trial(land):
    group = land["endpoints"][0]
    row = group["rows"][0]
    assert row["arm"] == "Tirzepatide 15 mg" and row["arm_is_drug"]
    assert row["delta"] == pytest.approx(-18.5)
    assert row["p_value"] == "<0.001" and row["weeks"] == 72


def test_each_row_carries_what_the_scorecard_tests_it_with(land):
    row = land["endpoints"][0]["rows"][0]
    assert (row["outcome_index"], row["outcome_type"], row["category_index"]) == (0, "PRIMARY", 0)
    assert row["param"] == "LEAST_SQUARES_MEAN"
    assert row["arm_names_drug"] and not row["arm_is_control"]
    assert row["reference_is_drug"] is False and row["head_to_head"] is None
    assert row["analyses"] == [{"method": None, "param_type": None, "param_value": -18.5,
                                "ci_pct": None, "ci_lower": None, "ci_upper": None,
                                "p_value": "<0.001"}]
    for key in ("lower", "upper", "reference_spread", "reference_lower", "reference_upper"):
        assert key in row


def test_whose_arm_it_is_is_read_from_the_titles():
    names = ["Sitagliptin"]
    assert L._is_control_arm("Placebo", names)
    assert L._is_control_arm("Standard of care", names)
    assert not L._is_control_arm("Sitagliptin 100 mg + Placebo", names)
    # A comparator arm that holds the drug, by a filed name or a component of a combination.
    assert L._title_names("Placebo + Sitagliptin", L._names_of({"_names": names, "name": "X"}))
    assert L._title_names("Liraglutide 1.8 mg", L._names_of(
        {"_names": ["Xultophy"], "name": "Insulin degludec + Liraglutide"}))
    assert not L._title_names("Insulin Glargine", ["Insulin icodec"])


def test_safety_keeps_each_trial_as_a_stratum(land):
    s = next(x for x in land["safety"] if x["name"] == "Tirzepatide")
    assert s["strata"] == [{
        "nct_id": "NCT1", "phase": "Phase 3", "kind": "placebo", "arms": 1,
        "control_title": "Placebo", "control_is_drug": False,
        "control": {"serious": [44, 643], "withdrawn": [17, 643], "deaths": [0, 643]},
        "arm_rows": [{"title": "Tirzepatide 15 mg", "is_control": False,
                      "serious": [40, 630], "withdrawn": [39, 630], "deaths": [0, 630]}]}]


def test_safety_pools_the_drug_arms_against_placebo_in_the_same_trials(land):
    s = next(x for x in land["safety"] if x["name"] == "Tirzepatide")
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
    zep = next(c for c in L.landscape(path, 1)["candidates"] if c["name"] == "Tirzepatide")
    assert zep["stage"] == "Marketed · Phase 3 here" and not zep["on_label"]


def test_the_comparator_is_placebo_else_the_control_else_the_other_of_two_arms():
    arm = lambda t: {"group_title": t, "group_description": ""}
    assert L.comparator([arm("Pembrolizumab"), arm("Placebo")], ["pembrolizumab"])[1] == "placebo"
    assert L.comparator([arm("Durvalumab"), arm("Sub-study A: SoC")], ["durvalumab"])[1] == "control"
    ref, kind = L.comparator([arm("Pembrolizumab 2 mg/kg"), arm("Docetaxel 75 mg/m^2")],
                             ["pembrolizumab"])
    assert kind == "comparator" and ref["group_title"].startswith("Docetaxel")
    assert L.comparator([arm("Arm A"), arm("Arm B"), arm("Arm C")], ["x"]) == (None, None)


def test_two_brands_of_one_molecule_are_one_compound(tmp_path, monkeypatch):
    """Mounjaro and Zepbound are both tirzepatide: one row, both brands, both trials."""
    path = _book(tmp_path)
    conn = db.get_connection(path)
    conn.execute("UPDATE assets SET molecule_id = 1 WHERE id = 1")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed, molecule_id) VALUES (4, 1, 'Tirzepatide', 'Mounjaro', 1, 1)")
    conn.execute("INSERT INTO completed_trials (nct_id, sponsor_company_id, asset_id, title,"
                 " phase, conditions) VALUES ('NCT4', 1, 4, 'SURMOUNT-2', 'Phase 3', ?)",
                 (json.dumps(["Obesity"]),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(L, "_big_pharma_ids", lambda conn: {1, 2})
    monkeypatch.setattr(L, "_model_lines", lambda db_path, tickers, verdict_for=None: {
        1: {"per_share": 71.77, "pos": 1.0, "peak_revenue": 30000, "peak_year": 2031,
            "years": [2026], "revenue_share": [1.0], "currency": "USD"},
        4: {"per_share": 146.87, "pos": 1.0, "peak_revenue": 72000, "peak_year": 2028,
            "years": [2026], "revenue_share": [1.0], "currency": "USD"}})
    land = L.landscape(path, 1)
    tirz = [c for c in land["candidates"] if c["name"] == "Tirzepatide"]
    assert len(tirz) == 1
    assert tirz[0]["brands"] == ["Mounjaro", "Zepbound"]
    assert {t["nct_id"] for t in tirz[0]["trials"]} == {"NCT1", "NCT4"}
    assert tirz[0]["model"]["per_share"] == pytest.approx(71.77 + 146.87)


def test_a_generic_name_is_cleaned_to_the_compound():
    assert L._clean_generic("Osimertinib Mesylate") == "Osimertinib"
    assert L._clean_generic("Fam-Trastuzumab Deruxtecan-Nxki") == "Trastuzumab deruxtecan"
    assert L._clean_generic("Cemiplimab-Rwlc") == "Cemiplimab"
    assert L._clean_generic("UBT251") == "UBT251"            # a code keeps its capitals
    assert L._clean_generic("Mk-0616") == "MK-0616"


def test_a_salt_and_its_parent_are_one_compound():
    """ChEMBL files osimertinib mesylate apart from osimertinib; the trial code arm is the drug."""
    cands = {315: {"ticker": "AZN", "generic": "Osimertinib Mesylate", "brand": "Tagrisso"},
             6531: {"ticker": "AZN", "generic": "AZD9291 80 mg/40 mg"},
             7: {"ticker": "LLY", "generic": "Osimertinib"}}
    pharm = {315: {"molecule": [{"value": "OSIMERTINIB MESYLATE", "ref": "CHEMBL3545063"}]},
             6531: {"molecule": [{"value": "OSIMERTINIB", "ref": "CHEMBL3353410"}]}}
    groups = sorted(sorted(g) for g in L.compound_groups(cands, pharm))
    assert groups == [[7], [315, 6531]]            # another company's copy stays its own


# --- whose arm it is: the review round ------------------------------------------------------
def _arm(title, desc=""):
    return {"group_title": title, "group_description": desc}


def test_a_salt_or_a_suffix_does_not_hide_the_drug():
    osi = L.drug_identity({"name": "Osimertinib", "_names": ["Tagrisso", "Osimertinib Mesylate"]})
    ref, kind = L.comparator([_arm("Osimertinib 80mg"), _arm("Chemotherapy")], osi)
    assert kind == "comparator" and ref["group_title"] == "Chemotherapy"
    cemi = L.drug_identity({"name": "Cemiplimab", "_names": ["Libtayo", "Cemiplimab-Rwlc"]})
    assert L.comparator([_arm("Cemiplimab 350 mg"), _arm("Platinum Doublet")], cemi)[1] == (
        "comparator")
    # "Pramlintide + Placebo" is the drug with a dummy, never a control arm.
    pram = L.drug_identity({"name": "Pramlintide", "_names": ["Symlin", "Pramlintide Acetate"]})
    assert not L.is_placebo("Pramlintide + Placebo", pram)
    assert not L._is_control_arm("Pramlintide + Placebo", pram)


def test_a_biosimilar_is_not_read_as_its_reference_product():
    cands = {1: {"name": "Bevacizumab", "_names": ["Mvasi", "Bevacizumab-Awwb"]},
             2: {"name": "Bevacizumab", "_names": ["Avastin", "Bevacizumab"]}}
    ids = L.identities(cands)
    assert ids[1]["plain"] == [] and not L.names_drug("Bevacizumab 15 mg/kg", ids[1])
    alone = L.drug_identity(cands[1])
    assert alone["plain"] == ["Bevacizumab"]
    # Where the reference product is not a candidate, a code on the other arm says so.
    assert L.comparator([_arm("Bevacizumab"), _arm("ABP 215")], alone) == (None, None)


def test_an_extension_arm_is_not_a_third_arm_and_the_one_unnamed_arm_is_the_comparator():
    nivo = ["Opdivo", "Nivolumab"]
    ref, kind = L.comparator([_arm("Nivolumab"), _arm("Docetaxel"),
                              _arm("Extension Phase of Docetaxel Arm: Nivolumab")], nivo)
    assert ref["group_title"] == "Docetaxel" and kind == "comparator"
    ref, _ = L.comparator([_arm("Tirzepatide 5 mg"), _arm("Tirzepatide 10 mg"),
                           _arm("Tirzepatide 15 mg"), _arm("Semaglutide 1 mg")],
                          ["Mounjaro", "Tirzepatide"])
    assert ref["group_title"] == "Semaglutide 1 mg"
    assert L.comparator([_arm("Arm A"), _arm("Arm B"), _arm("Arm C")], ["x"]) == (None, None)


def test_a_combination_is_named_only_by_every_component_or_its_own_name():
    xul = L.drug_identity({"name": "Insulin degludec + Liraglutide",
                           "_names": ["Xultophy 100/3.6", "Insulin Degludec", "Liraglutide"]})
    assert not L.names_drug("Insulin degludec 100 U/mL", xul)
    assert not L.names_drug("IDeg OD", xul)
    assert L.names_drug("Insulin degludec/liraglutide", xul)
    assert L.names_drug("Xultophy 100/3.6", xul)
    assert L.mentions_drug("Liraglutide 1.8 mg", xul)       # a part: never a clean control


def test_a_description_names_the_drug_only_as_the_arms_own_treatment():
    ixe, bari = L.drug_identity(["Ixekizumab"]), L.drug_identity(["Baricitinib"])
    assert not L._described("Etanercept 50 mg twice weekly. Placebo for ixekizumab given as "
                            "2 SC injections", ixe)
    assert not L._described("Adalimumab 40 mg and baricitinib placebo orally. Non-responders "
                            "were rescued with baricitinib 4 mg", bari)
    assert not L._described("Rovalpituzumab tesirine IV. Dexamethasone coadministered orally",
                            L.drug_identity(["Dexamethasone"]))
    assert L._described("Dapagliflozin 10 mg once daily", L.drug_identity(["Dapagliflozin"]))


def test_an_arm_that_adds_another_candidate_is_not_the_drugs_alone():
    ids = L.identities({1: {"name": "Nivolumab", "_names": ["Opdivo", "Nivolumab"]},
                        2: {"name": "Ipilimumab", "_names": ["Yervoy", "Ipilimumab"]},
                        3: {"name": "Pemetrexed", "_names": ["Alimta", "Pemetrexed"]},
                        4: {"name": "Pembrolizumab", "_names": ["Keytruda", "Pembrolizumab"]}})
    assert L.claimed_by_other("Nivolumab 1 mg/kg + Ipilimumab 3 mg/kg", "Placebo", 1, ids)
    assert not L.claimed_by_other("Nivolumab 240 mg", "Placebo", 1, ids)
    # A backbone both arms share claims nothing.
    assert not L.claimed_by_other("Pembrolizumab + Pemetrexed", "Placebo + Pemetrexed", 4, ids)
    # Another candidate's own arm in a trial of this drug is that candidate's.
    assert L.claimed_by_other("Ipilimumab 10 mg/kg", "Placebo", 1, ids)


def test_small_cell_lung_cancer_is_not_non_small_cell():
    assert not L.condition_matches("Small Cell Lung Cancer", "Carcinoma, Non-Small-Cell Lung")
    assert not L.condition_matches("Extensive-stage Small-cell Lung Cancer",
                                   "Carcinoma, Non-Small-Cell Lung")
    assert L.condition_matches("Non-small Cell Lung Cancer", "Carcinoma, Non-Small-Cell Lung")


def test_the_safety_stratum_leaves_out_an_arm_that_adds_another_candidate():
    cand = {"asset_id": 1, "name": "Nivolumab", "_names": ["Opdivo", "Nivolumab"]}
    ids = L.identities({1: cand, 2: {"name": "Ipilimumab", "_names": ["Yervoy", "Ipilimumab"]}})
    row = lambda t, s: {"group_title": t, "serious_affected": s, "serious_at_risk": 100,
                        "deaths_affected": 0, "deaths_at_risk": 100, "withdrawn_ae": 1,
                        "other_at_risk": 100}
    rows = [row("Nivolumab 240 mg", 30), row("Nivolumab 1 mg/kg + Ipilimumab 3 mg/kg", 70),
            row("Placebo", 20)]
    st = L._stratum("N1", "Phase 3", rows, rows[2], "placebo", cand, ids)
    assert [a["title"] for a in st["arm_rows"]] == ["Nivolumab 240 mg"]
