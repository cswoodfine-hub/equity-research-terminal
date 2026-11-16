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


# --- the trial somebody else runs with your molecule ------------------------

from fetchers.trials_ctgov import _is_our_collaboration  # noqa: E402
import trial_mapping  # noqa: E402

_NOVARTIS = trial_mapping.normalise("Novartis Pharmaceuticals")
# (normalised asset name, asset id), as trial_mapping._asset_names returns them.
_NVS_ASSETS = [("inclisiran", 20), ("leqvio", 20), ("ribociclib", 21)]


def _study(nct="NCT03705234", lead="University of Oxford",
           collaborators=("The TIMI Study Group", "Novartis Pharmaceuticals"),
           interventions=("Inclisiran", "Placebo"),
           phases=("PHASE3",), enrollment=16124):
    """ORION-4 as the registry actually files it, by default."""
    return {"protocolSection": {
        "identificationModule": {"nctId": nct},
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": lead},
            "collaborators": [{"name": n} for n in collaborators]},
        "designModule": {"phases": list(phases),
                         "enrollmentInfo": {"count": enrollment}},
        "armsInterventionsModule": {
            "interventions": [{"name": n} for n in interventions]}}}


def test_an_academic_trial_of_your_own_molecule_is_yours():
    """ORION-4: 16,124 participants of inclisiran with major adverse cardiovascular
    events as its primary endpoint, led by the University of Oxford with Novartis a
    collaborator. The lead-sponsor query cannot see it, so the book held no row for it
    at all while pricing a smaller Novartis-led study in the same setting as Leqvio's
    gate."""
    assert _is_our_collaboration(_study(), _NOVARTIS, _NVS_ASSETS, set()) is True


def test_somebody_elses_molecule_is_not_yours():
    """The test that keeps query.spons usable. A company is named on studies of other
    people's medicines it supplied or part-funded, and those are not its programmes."""
    other = _study(interventions=("Evolocumab", "Placebo"))
    assert _is_our_collaboration(other, _NOVARTIS, _NVS_ASSETS, set()) is False


def test_a_loose_sponsor_match_is_not_a_collaboration():
    """query.spons matches the sponsor fields loosely, so the company has to be named
    rather than merely returned."""
    not_named = _study(collaborators=("The TIMI Study Group",))
    assert _is_our_collaboration(not_named, _NOVARTIS, _NVS_ASSETS, set()) is False


def test_the_company_leading_its_own_study_is_left_to_the_first_pass():
    """A company is sometimes listed as its own collaborator. The lead-sponsor query
    runs first and owns those, or the study would arrive twice."""
    own = _study(lead="Novartis Pharmaceuticals",
                 collaborators=("Novartis Pharmaceuticals",))
    assert _is_our_collaboration(own, _NOVARTIS, _NVS_ASSETS, set()) is False


def test_a_study_already_in_hand_is_not_taken_twice():
    assert _is_our_collaboration(_study(), _NOVARTIS, _NVS_ASSETS,
                                 {"NCT03705234"}) is False


def test_a_company_with_no_assets_yet_claims_nothing():
    """A brand-new ticker on its first refresh has no assets to match against, and must
    not therefore claim every study it is named on."""
    assert _is_our_collaboration(_study(), _NOVARTIS, [], set()) is False


def test_a_study_with_no_id_is_refused():
    broken = _study()
    broken["protocolSection"]["identificationModule"] = {}
    assert _is_our_collaboration(broken, _NOVARTIS, _NVS_ASSETS, set()) is False


def test_the_collaborators_are_asked_for():
    """The predicate reads the collaborator list, so the fetch has to request it."""
    from fetchers.trials_ctgov import FIELDS
    assert "protocolSection.sponsorCollaboratorsModule.collaborators" in FIELDS


def test_an_investigator_study_with_a_marketed_drug_is_not_a_programme():
    """The test that makes the rule usable. Matching on the molecule alone returns 1,659
    studies the book does not hold, and they are overwhelmingly academics running their
    own trial with an approved medicine: 225 name pembrolizumab, 113 nivolumab, 81
    durvalumab. Scale is what separates a registrational or pragmatic outcomes trial from
    investigator-initiated work."""
    small = _study(interventions=("Inclisiran", "Placebo"), phases=("PHASE2",),
                   enrollment=60)
    assert _is_our_collaboration(small, _NOVARTIS, _NVS_ASSETS, set()) is False


def test_a_late_phase_study_below_the_size_is_not_taken():
    assert _is_our_collaboration(_study(enrollment=999), _NOVARTIS, _NVS_ASSETS,
                                 set()) is False
    assert _is_our_collaboration(_study(enrollment=1000), _NOVARTIS, _NVS_ASSETS,
                                 set()) is True


def test_a_large_early_phase_study_is_not_taken():
    """Size without a late phase is a platform or a registry, not a gate."""
    assert _is_our_collaboration(_study(phases=("PHASE1",), enrollment=5000),
                                 _NOVARTIS, _NVS_ASSETS, set()) is False


def test_a_study_with_no_design_block_is_refused_rather_than_assumed():
    bare = _study()
    del bare["protocolSection"]["designModule"]
    assert _is_our_collaboration(bare, _NOVARTIS, _NVS_ASSETS, set()) is False


def test_a_phase_two_three_study_qualifies_on_its_phase_three_half():
    """The registry files an adaptive late-stage study as both, and the book reads that
    as a Phase 3 gate elsewhere (forecast_view._LAYER_GATE_PHASES). Recorded because
    the rule says "Phase 3 or 4" and this is the case where that is not a string
    comparison."""
    both = _study(phases=("PHASE2", "PHASE3"), enrollment=2250)
    assert _is_our_collaboration(both, _NOVARTIS, _NVS_ASSETS, set()) is True
    only_two = _study(phases=("PHASE2",), enrollment=2250)
    assert _is_our_collaboration(only_two, _NOVARTIS, _NVS_ASSETS, set()) is False


# --- a study that is not the company's programme ------------------------------

def test_a_study_named_not_ours_is_skipped_and_cannot_return(tmp_path):
    """ASCEND matched Bayer only because Bayer owns a product of aspirin. Oxford leads it,
    Bayer is one of nine collaborators, and its primary completed in 2018. Who sponsors
    cannot be the test, because Oxford sponsors ORION-4 too; whose programme it is, is."""
    from fetchers import trials_ctgov as T
    f = tmp_path / "not_ours.csv"
    f.write_text("ticker,nct_id,basis\nBAYN,NCT00135226,an academic trial of a generic\n")
    assert T.not_our_trials("BAYN", f) == {"NCT00135226"}
    assert T.not_our_trials("bayn", f) == {"NCT00135226"}
    assert T.not_our_trials("NVS", f) == set()


def test_the_shipped_exclusions_name_a_basis_and_a_registry_record():
    from fetchers import trials_ctgov as T
    import csv as _csv
    with open(T.NOT_OUR_TRIALS_CSV, newline="", encoding="utf-8") as handle:
        rows = list(_csv.DictReader(l for l in handle if not l.lstrip().startswith("#")))
    assert rows, "the file is empty"
    for r in rows:
        assert r["nct_id"].startswith("NCT"), r
        assert "clinicaltrials.gov/study/" + r["nct_id"] in r["basis"], r["nct_id"]
        assert len(r["basis"]) > 80, r["nct_id"]
