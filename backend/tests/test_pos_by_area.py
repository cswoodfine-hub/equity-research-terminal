"""Published success rates by therapeutic area, rather than one number for the book."""

import pytest

import assumptions
import forecast

RAMP = {"Phase 3": {"pos": 0.65, "source": "analyst convention"}}
BY_AREA = {("Oncology", "Phase 3"): {"pos": 0.439, "sample_size": "n(LOA)=819", "note": ""},
           ("All indications", "Phase 3"): {"pos": 0.524, "sample_size": "", "note": ""}}


def test_an_asset_takes_its_own_areas_rate():
    got, basis = forecast.pos({}, "Phase 3", RAMP, area="Oncology", by_area=BY_AREA)
    assert got == pytest.approx(0.439)
    assert "Oncology" in basis and "n(LOA)=819" in basis


def test_an_area_the_study_does_not_cover_reads_as_all_indications():
    got, basis = forecast.pos({}, "Phase 3", RAMP, area="Dermatology", by_area=BY_AREA)
    assert got == pytest.approx(0.524) and "all indications" in basis


def test_an_asset_with_no_area_reads_as_all_indications():
    got, basis = forecast.pos({}, "Phase 3", RAMP, area=None, by_area=BY_AREA)
    assert got == pytest.approx(0.524) and "all indications" in basis


def test_the_curated_ramp_still_answers_where_the_study_has_no_row():
    got, basis = forecast.pos({}, "Phase 3", RAMP, area="Oncology", by_area={})
    assert got == pytest.approx(0.65) and "phase default" in basis
    got, basis = forecast.pos({}, "Phase 4", RAMP, area="Oncology", by_area=BY_AREA)
    assert got is None and basis is None


def test_a_stated_value_and_composite_factors_still_win():
    assert forecast.pos({"pos": 0.9}, "Phase 3", RAMP, area="Oncology", by_area=BY_AREA) == (0.9, "stated")
    got, basis = forecast.pos({"pos_regulatory": 0.8, "pos_launch": 0.5}, "Phase 3", RAMP,
                              area="Oncology", by_area=BY_AREA)
    assert got == pytest.approx(0.4) and basis == "composite factors"


def test_the_file_covers_every_area_the_model_classifies_to():
    import therapeutic_areas
    by_area = assumptions.pos_by_area()
    assert by_area, "no published rates on file"
    covered = {area for area, _ in by_area}
    for area in therapeutic_areas.area_names():
        if area in ("Healthy volunteers", therapeutic_areas.OTHER):
            continue
        assert area in covered, f"no published rate for {area}"
    for phase in ("Phase 1", "Phase 1/2", "Phase 2", "Phase 2/3", "Phase 3", "Filed"):
        assert ("All indications", phase) in by_area
