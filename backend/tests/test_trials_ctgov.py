"""parse_studies runs against a saved CTGov fixture, no network."""

import json
from pathlib import Path

from fetchers.trials_ctgov import normalize_phase, parse_studies

FIXTURE = Path(__file__).parent / "fixtures" / "ctgov_studies.json"


def test_normalize_phase():
    assert normalize_phase(["PHASE1"]) == "Phase 1"
    assert normalize_phase(["EARLY_PHASE1"]) == "Phase 1"
    assert normalize_phase(["PHASE1", "PHASE2"]) == "Phase 1/2"
    assert normalize_phase(["PHASE2", "PHASE3"]) == "Phase 2/3"
    assert normalize_phase(["PHASE4"]) == "Phase 4"
    assert normalize_phase(["NA"]) is None
    assert normalize_phase([]) is None


def test_parse_studies_filters_and_normalises():
    payload = json.loads(FIXTURE.read_text())
    rows = parse_studies(payload)

    # 7 studies in, NA-phase and non-drug studies dropped -> 5 kept.
    assert len(rows) == 5
    by_phase = {r["phase"] for r in rows}
    assert by_phase == {"Phase 1", "Phase 1/2", "Phase 2", "Phase 3", "Phase 4"}

    # Every kept row has an nct_id, a humanised status, and at least one drug.
    for r in rows:
        assert r["nct_id"].startswith("NCT")
        assert r["overall_status"][0].isupper() and r["overall_status"].islower() is False
        assert r["interventions"]
        assert isinstance(r["conditions"], list)

    # Status is humanised, not the raw enum.
    statuses = {r["overall_status"] for r in rows}
    assert "Active not recruiting" in statuses or "Recruiting" in statuses
    assert not any("_" in s for s in statuses)
