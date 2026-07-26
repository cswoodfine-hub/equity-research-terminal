"""build_pipeline over a seeded DB, no network.

Trials are loaded through the real fetcher with the CTGov fetch monkeypatched to the
saved fixture (5 drug trials, one per phase bucket except Phase 2/3).
"""

import json
from pathlib import Path

import db
import pipeline
import seed
from fetchers.trials_ctgov import TrialsFetcher

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov_studies.json"


def test_pipeline_counts_and_drilldown(tmp_path, monkeypatch):
    payload = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(TrialsFetcher, "fetch", lambda self: payload)

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    TrialsFetcher("LLY", db_file).run()

    rows = {r["ticker"]: r for r in pipeline.build_pipeline(db_file)}
    assert rows["LLY"]["total"] == 5
    assert rows["LLY"]["phases"] == {
        "Phase 1": 1, "Phase 1/2": 1, "Phase 2": 1,
        "Phase 2/3": 0, "Phase 3": 1, "Phase 4": 1,
    }
    assert rows["PFE"]["total"] == 0  # untouched company is zero-filled

    phase3 = pipeline.trials_for(db_file, "LLY", "Phase 3")
    assert len(phase3) == 1 and phase3[0]["phase"] == "Phase 3"
    assert isinstance(phase3[0]["conditions"], list)

    assert len(pipeline.trials_for(db_file, "LLY")) == 5  # no phase filter
    assert pipeline.trials_for(db_file, "ZZZZ") is None  # unknown ticker


def test_is_follow_up_reads_the_standard_lifecycle_titles():
    yes = [
        "A Long-term Follow-up Study in Participants Who Received CTX001",
        "An Open-Label Extension Study to Assess Long-Term Safety",
        "Roll-over Study to Allow Continued Access to Ribociclib",
        "A Rollover Study of CC-122",
        "Long-term Extension Study to Evaluate Safety and Tolerability",
    ]
    no = [
        "A Study of Pembrolizumab in Combination With Chemotherapy",
        "Phase 3 Trial of Tirzepatide in Adults With Obesity",
        "",
        None,
    ]
    assert all(pipeline.is_follow_up(t) for t in yes)
    assert not any(pipeline.is_follow_up(t) for t in no)


def _study(nct, title, phase):
    """A minimal CTGov-shaped interventional drug study parse_studies will keep."""
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title},
            "statusModule": {"overallStatus": "RECRUITING"},
            "designModule": {"studyType": "INTERVENTIONAL", "phases": [phase]},
            "conditionsModule": {"conditions": ["Melanoma"]},
            "armsInterventionsModule": {
                "interventions": [{"type": "DRUG", "name": "Widgetinib"}]},
        }
    }


def test_follow_up_is_flagged_per_trial_and_counted_off_development(tmp_path, monkeypatch):
    # A Phase 3 follow-up sits inside the pipeline count until it is recognised; a Phase 4
    # follow-up stays in the post-approval bucket, so it is not counted again as follow-up.
    payload = {"studies": [
        _study("NCT10000001", "A Long-term Follow-up Study of Widgetinib", "PHASE3"),
        _study("NCT10000002", "A Phase 3 Study of Widgetinib in Melanoma", "PHASE3"),
        _study("NCT10000003", "Widgetinib Roll-over Study", "PHASE4"),
    ]}
    monkeypatch.setattr(TrialsFetcher, "fetch", lambda self: payload)

    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    TrialsFetcher("LLY", db_file).run()

    lly = next(r for r in pipeline.build_pipeline(db_file) if r["ticker"] == "LLY")
    assert lly["follow_up"] == 1            # only the Phase 3 follow-up, not the Phase 4 one

    rows = {t["nct_id"]: t for t in pipeline.trials_for(db_file, "LLY")}
    assert rows["NCT10000001"]["follow_up"] is True
    assert rows["NCT10000002"]["follow_up"] is False
    assert rows["NCT10000003"]["follow_up"] is True   # a Phase 4 rollover is still follow-up
