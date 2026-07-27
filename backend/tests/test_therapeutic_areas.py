"""Condition strings to therapeutic areas. Pure, no network, no model."""

import json

import therapeutic_areas as ta


def test_the_three_spellings_of_nsclc_land_together():
    """The registry spells one disease several ways, which is the whole reason
    conditions cannot be browsed raw."""
    for spelling in ("Carcinoma, Non-Small-Cell Lung", "Non-Small Cell Lung Cancer",
                     "Non-small Cell Lung Cancer"):
        assert ta.classify([spelling]) == "Oncology"


def test_areas_by_example():
    cases = {
        "Oncology": ["Multiple Myeloma"],
        "Metabolic": ["Obesity", "Overweight"],
        "Immunology and inflammation": ["Systemic Lupus Erythematosus"],
        "Neuroscience": ["Alzheimer Disease"],
        "Cardiovascular": ["Peripheral Arterial Disease"],
        "Infectious disease": ["Influenza Vaccine"],
        "Respiratory": ["Asthma"],
        "Haematology": ["Sickle Cell Disease"],
        "Ophthalmology": ["Geographic Atrophy"],
        "Renal and hepatic": ["Chronic Kidney Disease"],
        "Healthy volunteers": ["Healthy Volunteers"],
    }
    for expected, conditions in cases.items():
        assert ta.classify(conditions) == expected, conditions


def test_a_disease_outranks_a_healthy_cohort():
    """Phase 1 oncology studies often list a healthy arm too. The disease wins."""
    assert ta.classify(["Healthy", "Advanced Solid Tumors"]) == "Oncology"


def test_unmatched_conditions_stay_in_other():
    """Never forced into an area they do not belong to."""
    assert ta.classify(["Opioid Use Disorder"]) == ta.OTHER
    assert ta.classify([]) == ta.OTHER
    assert ta.classify(None) == ta.OTHER
    assert ta.classify("") == ta.OTHER


def test_accepts_the_json_string_the_table_stores():
    assert ta.classify(json.dumps(["Breast Cancer"])) == "Oncology"
    assert ta.classify("not json at all") == ta.OTHER


def test_classification_is_stable():
    """Same input, same area, every time: no model and no randomness."""
    conditions = ["Metastatic Breast Cancer", "Healthy"]
    assert len({ta.classify(conditions) for _ in range(50)}) == 1


def test_classify_label_reads_the_first_indication():
    # A malignancy warning further down the section does not make a rheumatoid
    # arthritis drug an oncology product.
    label = ("1 INDICATIONS AND USAGE OLUMIANT is indicated for the treatment of adults "
             "with moderately to severely active rheumatoid arthritis. Malignancies "
             "have been reported in patients treated with OLUMIANT.")
    assert ta.classify_label(label) == "Immunology and inflammation"


def test_classify_label_takes_the_area_named_first():
    # Cymbalta is a depression drug that also treats diabetic neuropathic pain. Taking
    # the areas in declared order made it metabolic on the word "diabetic".
    label = ("INDICATIONS AND USAGE CYMBALTA is indicated for the treatment of major "
             "depressive disorder, diabetic peripheral neuropathic pain and fibromyalgia")
    assert ta.classify_label(label) == "Neuroscience"


def test_classify_label_states_nothing_for_a_label_it_cannot_read():
    assert ta.classify_label("") == ta.OTHER
    assert ta.classify_label(
        "INDICATIONS AND USAGE indicated as a diagnostic contrast agent"
    ) == ta.OTHER
