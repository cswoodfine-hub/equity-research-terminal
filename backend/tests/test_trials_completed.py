"""Completed studies with results, the evidence behind a marketed product."""

import json
from pathlib import Path

import db
import product_profile
from fetchers.trials_completed import TrialsCompletedFetcher, parse_studies

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov_completed_lly.json"


def test_parses_the_registry_payload():
    rows = parse_studies(json.loads(FIXTURE.read_text()))
    assert rows, "the fixture should hold studies"
    first = rows[0]
    assert first["nct_id"].startswith("NCT")
    assert first["title"]
    # Completion date and the primary endpoint are the two facts this view is for.
    assert first["completion_date"]
    assert first["primary_outcome"]
    assert json.loads(first["conditions"]) != []


def test_a_study_with_no_outcomes_carries_no_endpoint():
    rows = parse_studies({"studies": [{"protocolSection": {
        "identificationModule": {"nctId": "NCT0001", "briefTitle": "A study"},
        "designModule": {"phases": ["PHASE3"]},
    }}]})
    assert rows[0]["primary_outcome"] is None
    assert rows[0]["phase"] == "Phase 3"
    assert rows[0]["completion_date"] is None


def test_skips_a_study_with_no_identifier():
    assert parse_studies({"studies": [{"protocolSection": {}}]}) == []


def test_binds_a_study_to_the_product_its_intervention_names(tmp_path):
    path = str(tmp_path / "completed.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('LLY', 'Eli Lilly')")
    cid = conn.execute("SELECT id FROM companies").fetchone()["id"]
    conn.execute("INSERT INTO assets (owner_company_id, brand_name, generic_name,"
                 "                    is_marketed) VALUES (?, 'Verzenio', 'Abemaciclib', 1)",
                 (cid,))
    asset_id = conn.execute("SELECT id FROM assets").fetchone()["id"]
    conn.commit()
    conn.close()

    fetcher = TrialsCompletedFetcher("LLY", path)
    rows = fetcher.normalise({"company_id": cid, "studies": [{"protocolSection": {
        "identificationModule": {"nctId": "NCT9001", "briefTitle": "A study of X"},
        "designModule": {"phases": ["PHASE3"], "enrollmentInfo": {"count": 600}},
        "statusModule": {"completionDateStruct": {"date": "2025-03-01"}},
        "conditionsModule": {"conditions": ["Breast Cancer"]},
        "armsInterventionsModule": {"interventions": [{"name": "Abemaciclib 150 mg"}]},
        "outcomesModule": {"primaryOutcomes": [{"measure": "Invasive disease-free survival"}]},
    }}]})
    assert rows[0]["asset_id"] == asset_id
    assert fetcher.upsert(rows).rows_fetched == 1

    # A second run of the same study updates it rather than duplicating it.
    fetcher.upsert(rows)
    conn = db.get_connection(path)
    assert conn.execute("SELECT COUNT(*) FROM completed_trials").fetchone()[0] == 1
    profile_rows = conn.execute(
        "SELECT primary_outcome, enrollment FROM completed_trials").fetchone()
    conn.close()
    assert profile_rows["primary_outcome"] == "Invasive disease-free survival"
    assert profile_rows["enrollment"] == 600


def test_summary_is_the_labels_own_first_sentence():
    label = ("1 INDICATIONS AND USAGE MOUNJARO is indicated as an adjunct to diet and "
             "exercise to improve glycemic control in adults with type 2 diabetes "
             "mellitus. MOUNJARO is a GIP receptor agonist.")
    assert product_profile.summarise(label) == (
        "MOUNJARO is indicated as an adjunct to diet and exercise to improve glycemic "
        "control in adults with type 2 diabetes mellitus.")


def test_summary_stops_at_a_bulleted_indication_list():
    label = ("INDICATIONS AND USAGE VERZENIO is a kinase inhibitor indicated: • in "
             "combination with endocrine therapy • as monotherapy")
    assert product_profile.summarise(label) == "VERZENIO is a kinase inhibitor indicated."


def test_no_label_means_no_summary():
    assert product_profile.summarise(None) is None
    assert product_profile.summarise("") is None
    assert product_profile.summarise("INDICATIONS AND USAGE .") is None
