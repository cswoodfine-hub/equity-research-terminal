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
