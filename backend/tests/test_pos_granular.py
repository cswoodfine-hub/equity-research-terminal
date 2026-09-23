"""A big pharma Phase 2 or 3 asset is placed at its gate, with a band, not at its
phase's entry with a point."""

import datetime as dt

import pytest

import db
import forecast
import pos_granular as PG

TODAY = dt.date(2026, 9, 22)


def _seed(tmp_path, trials=(), readouts=(), prevalence=None, unit="patients",
          name="XYZ-1234", modality=None, phase="Phase 3"):
    path = str(tmp_path / "pos.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name, reporting_currency)"
                 " VALUES (1, 'ABBV', 'AbbVie', 'USD')")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, modality,"
                 " is_marketed) VALUES (7, 1, ?, ?, 0)", (name, modality))
    conn.execute("INSERT INTO indications (id, name) VALUES (3, 'Multiple myeloma')")
    conn.execute("INSERT INTO asset_indications (asset_id, indication_id, phase, is_lead,"
                 " region) VALUES (7, 3, ?, 1, 'US')", (phase,))
    for nct, status, completion, enrollment, design in trials:
        conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
                     " overall_status, primary_completion_date, enrollment, design,"
                     " title, conditions) VALUES (?, 7, 1, 'Phase 3', ?, ?, ?, ?,"
                     " 'A study', '[\"Multiple Myeloma\"]')",
                     (nct, status, completion, enrollment, design))
    for i, (drug, ph, outcome, on) in enumerate(readouts):
        conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase,"
                     " outcome, event_date) VALUES (?, 1, ?, ?, ?, ?)",
                     (f"000-{i}", drug, ph, outcome, on))
    if prevalence is not None:
        conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                     " key, value, unit) VALUES (7, 3, 'US', 'base', 'prevalence', ?, ?)",
                     (prevalence, unit))
    conn.commit()
    return conn


def _catalyst(conn, title, date, kind="PDUFA", description="FDA accepted it."):
    conn.execute("INSERT INTO catalysts (company_id, catalyst_type, expected_date,"
                 " title, description, is_curated, source_url, status) VALUES"
                 " (1, ?, ?, ?, ?, 0, 'https://sec.gov/x', 'pending')",
                 (kind, date, title, description))
    conn.commit()


def _resolve(conn, **kw):
    # The default asset qualifies for NO cut: a code number has no readable stem and
    # "solid tumours" names no sub-type. That isolates whatever a test is actually
    # about, because a test of the filing stage should not also be a test of the
    # antibody rate. Tests about the cuts pass a name and a condition of their own.
    args = dict(area="Oncology", phase="Phase 3", names=["XYZ-1234"], company_id=1,
                prevalence_us=None, biomarker_selected=False,
                conditions_text="solid tumours", today=TODAY)
    args.update(kw)
    return PG.resolve(conn, 7, **args)


def test_the_transitions_file_reads_and_carries_its_n():
    table = PG.transitions()
    assert table[("area", "Oncology", "p3_to_nda")] == {
        "pos": 0.477, "n": 495, "source": "Figure 2 p7"}
    assert table[("modality", "ADCs", "nda_to_approval")]["n"] == 12


def test_an_asset_at_phase_3_entry_gets_the_tables_own_figure(tmp_path):
    """The chain reproduces the likelihood pos_by_area.csv already carries, so nothing
    moves for an asset with no evidence beyond its phase."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500,
                                    "Randomized, Double, Treatment"),))
    got = _resolve(conn)
    conn.close()
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert got["stage"] == "entering"
    assert [s["gate"] for s in got["chain"]] == ["p3_to_nda", "nda_to_approval"]
    assert "NCT1 recruiting" in got["basis"]


def test_a_positive_phase_3_readout_leaves_only_the_approval_step(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Completed", "2026-03-01", 500, None),),
                 readouts=(("XYZ-1234", 3, "positive", "2026-06-01"),))
    got = _resolve(conn)
    conn.close()
    assert got["pos"] == pytest.approx(0.920)
    assert got["stage"] == "positive" and "2026-06-01" in got["evidence"]


def test_a_negative_readout_with_no_open_study_is_nil(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Completed", "2026-03-01", 500, None),),
                 readouts=(("XYZ-1234", 3, "negative", "2026-06-01"),))
    got = _resolve(conn)
    conn.close()
    assert got["pos"] == 0.0 and got["stage"] == "negative"


def test_a_negative_readout_with_other_studies_open_keeps_the_gate_and_floors_the_band(tmp_path):
    """Volrustomig's lung study stopped for futility with three others recruiting to
    2030. One trial's answer is not the asset's."""
    conn = _seed(tmp_path, trials=(("NCT1", "Active not recruiting", "2026-03-01", 500, None),
                                   ("NCT2", "Recruiting", "2029-01-01", 900, None)),
                 readouts=(("XYZ-1234", 3, "negative", "2026-06-01"),))
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "mixed"
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert got["low"] == 0.0 and "NCT2" in got["evidence"]


def test_a_passed_completion_date_reports_a_readout_due_and_moves_nothing(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Active not recruiting", "2026-07-01", 500,
                                    None),))
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "reading_out"
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert "no readout on file" in got["evidence"]


def test_the_band_comes_from_the_cuts_the_asset_qualifies_for(tmp_path):
    """An antibody in a haematological cancer: the point stays on the area chain and
    the band is what the antibody and haematology cuts say."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    got = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma")
    conn.close()
    assert {c["group"] for c in got["cuts"]} == {"Monoclonal antibody", "Hematologic"}
    # The point used to sit on the band's low edge, because it was the area chain and
    # every cut here is above it. It now sits inside, which is what a band around a
    # central estimate should look like.
    assert got["low"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert got["high"] == pytest.approx(0.681 * 0.954, abs=1e-4)
    assert got["low"] < got["pos"] < got["high"]


def test_a_thin_cut_is_refused_and_says_why(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    got = _resolve(conn, names=["telisotuzumab vedotin"], conditions_text="lung")
    conn.close()
    assert got["cuts"] == []
    assert any("ADCs" in r["why"] and "n=16" in r["why"] for r in got["refused"])


def test_the_area_chain_is_never_refused_on_sample_size(tmp_path):
    """Metabolic's approval step rests on 48 programmes. pos_by_area.csv already carries
    it, so refusing it here would move the book for no new evidence."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    got = _resolve(conn, area="Metabolic", names=["MK-8748"], conditions_text="obesity")
    conn.close()
    assert got["pos"] == pytest.approx(0.636 * 0.875, abs=1e-4)
    assert "Metabolic" in got["basis"]


def test_a_biomarker_cut_is_taken_only_from_a_hand_entered_row(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    without = _resolve(conn, conditions_text="EGFR-mutant lung cancer")
    with_row = _resolve(conn, conditions_text="EGFR-mutant lung cancer",
                        biomarker_selected=True)
    conn.close()
    assert not any(c["cut"] == "biomarker" for c in without["cuts"])
    assert any(c["cut"] == "biomarker" for c in with_row["cuts"])
    assert with_row["high"] == pytest.approx(0.682 * 0.960, abs=1e-4)


def test_prevalence_cuts_rare_and_chronic_and_leaves_the_middle_alone(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    rare = _resolve(conn, area="Haematology", prevalence_us=100_000,
                    conditions_text="sickle cell")
    chronic = _resolve(conn, area="Metabolic", prevalence_us=100_000_000,
                       conditions_text="obesity")
    middle = _resolve(conn, area="Metabolic", prevalence_us=500_000,
                      conditions_text="obesity")
    vaccine = _resolve(conn, area=None, prevalence_us=80_000_000, names=["VLA15"],
                       conditions_text="Lyme disease")
    conn.close()
    prevalence = lambda got: [c["group"] for c in got["cuts"] if c["cut"] == "prevalence"]
    assert prevalence(rare) == ["Rare"]
    assert prevalence(chronic) == ["Chronic high prevalence"]
    assert prevalence(middle) == []
    assert prevalence(vaccine) == []


def test_a_seamless_phase_2_3_is_read_at_the_phase_2_gate(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),),
                 phase="Phase 2/3")
    got = _resolve(conn, phase="Phase 2/3")
    conn.close()
    assert got["pos"] == pytest.approx(0.246 * 0.477 * 0.920, abs=1e-4)
    assert got["basis"].startswith("seamless Phase 2/3 read at the Phase 2 gate")


def test_outside_phase_2_or_3_it_does_not_apply(tmp_path):
    conn = _seed(tmp_path)
    assert _resolve(conn, phase="Phase 1") is None
    assert _resolve(conn, phase="Filed") is None
    conn.close()


def test_the_modality_is_read_off_the_row_first_and_the_stem_second():
    assert PG.modality_of("MK-1045", "small molecule")[0] == "Small molecule"
    assert PG.modality_of("MK-1045")[0] is None
    assert PG.modality_of("etentamig", "biologic")[0] == "Monoclonal antibody"
    assert PG.modality_of("olpasiran")[0] == "siRNA/RNAi"
    assert PG.modality_of("retatrutide")[0] == "Peptide"
    assert PG.modality_of("patritumab deruxtecan")[0] == "ADCs"


def test_the_gate_is_big_pharma_and_unmarketed_only(tmp_path, monkeypatch):
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    monkeypatch.setattr(PG, "big_pharma", lambda conn, cid: False)
    assert PG.for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY) is None
    monkeypatch.setattr(PG, "big_pharma", lambda conn, cid: True)
    got = PG.for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY)
    assert got and got["stage"] == "entering"
    assert PG.for_asset(conn, 7, area="Oncology", phase="Phase 1", today=TODAY) is None
    conn.execute("UPDATE assets SET is_marketed = 1 WHERE id = 7")
    assert PG.for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY) is None
    conn.close()


def test_the_forecast_takes_it_after_the_analysts_own_numbers_and_before_the_table():
    by_area = {("Oncology", "Phase 3"): {"pos": 0.439, "sample_size": "", "note": ""}}
    granular = {"pos": 0.92, "basis": "at the NDA/BLA gate"}
    assert forecast.pos({}, "Phase 3", {}, area="Oncology", by_area=by_area,
                        granular=granular) == (0.92, "at the NDA/BLA gate")
    assert forecast.pos({"pos": 0.5}, "Phase 3", {}, area="Oncology", by_area=by_area,
                        granular=granular) == (0.5, "stated")
    got, basis = forecast.pos({}, "Phase 3", {}, area="Oncology", by_area=by_area,
                              granular=None)
    assert got == pytest.approx(0.439) and "published likelihood" in basis


def test_an_accepted_application_leaves_only_the_approval_step(tmp_path):
    """The whole point of step one. An asset whose application the FDA has accepted has
    only the approval transition left, not the Phase 3 chain."""
    import applications
    conn = _seed(tmp_path, trials=(("NCT1", "Active not recruiting", "2026-08-01", 500,
                                    None),))
    _catalyst(conn, "XYZ-1234 PDUFA, Multiple myeloma", "2027-04-01")
    applications.resolve(conn, today=TODAY)
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "filed"
    assert got["pos"] == pytest.approx(0.920)
    assert got["basis"].startswith("filed, at the NDA/BLA gate")
    assert "2027-04-01" in got["evidence"]
    assert got["filing"]["lifts"] is True


def test_a_filing_for_a_disease_the_asset_does_not_carry_lifts_nothing(tmp_path):
    """Povetacicept's case, which is the guard that matters. The filing is reported so
    the reader sees it, and the probability does not move."""
    import applications
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    _catalyst(conn, "XYZ-1234 PDUFA, IgA Nephropathy", "2027-04-01")
    applications.resolve(conn, today=TODAY)
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "entering"
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert got["filing"]["lifts"] is False
    assert "not an indication this asset carries" in got["filing"]["why"]


def test_a_negative_readout_still_beats_an_accepted_application(tmp_path):
    import applications
    conn = _seed(tmp_path, trials=(("NCT1", "Completed", "2026-03-01", 500, None),),
                 readouts=(("XYZ-1234", 3, "negative", "2026-06-01"),))
    _catalyst(conn, "XYZ-1234 PDUFA, Multiple myeloma", "2027-04-01")
    applications.resolve(conn, today=TODAY)
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "negative" and got["pos"] == 0.0


def test_a_filing_on_a_molecule_the_company_already_markets_lifts_nothing(tmp_path):
    """A supplemental application says nothing about a first approval, and the filers
    that matter never write the word supplemental. Two guards stand in the way and the
    ambiguity one fires first, because a marketed sibling carries the same generic name
    that the filing names. Either way nothing lifts, which is the point."""
    import applications
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed) VALUES (8, 1, 'XYZ-1234', 'Etenta', 1)")
    _catalyst(conn, "XYZ-1234 PDUFA, Multiple myeloma", "2027-04-01")
    resolved = applications.resolve(conn, today=TODAY)
    got = _resolve(conn)
    conn.close()
    assert resolved["asset"] == 0
    assert "ambiguous" in resolved["refused"][0]["why"]
    assert got["stage"] == "entering"
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert got["filing"] is None


def test_the_supplement_guard_catches_a_marketed_sibling_the_matcher_let_through(tmp_path):
    """Where the filing names the development code, the matcher resolves it uniquely and
    the join against a marketed row is the only thing standing between a label expansion
    and a doubled valuation."""
    import applications
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    conn.execute("UPDATE assets SET internal_code = 'ABBV-383' WHERE id = 7")
    conn.execute("INSERT INTO assets (id, owner_company_id, generic_name, brand_name,"
                 " is_marketed) VALUES (8, 1, 'XYZ-1234', 'Etenta', 1)")
    _catalyst(conn, "ABBV-383 PDUFA, Multiple myeloma", "2027-04-01")
    applications.resolve(conn, today=TODAY)
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "entering"
    assert got["filing"]["lifts"] is False
    assert "same molecule already marketed" in got["filing"]["why"]


def test_an_unknown_stage_name_does_not_raise(tmp_path):
    """The stage note used to be a bare dict subscript, which would have raised a
    KeyError on the first asset to reach a stage added later."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    real = PG.stage_of
    PG.stage_of = lambda *a, **k: {"stage": "something_new", "gate": None,
                                   "pivotal": None, "filing": None,
                                   "evidence": "a stage from the future"}
    try:
        got = _resolve(conn)
    finally:
        PG.stage_of = real
        conn.close()
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert got["basis"].startswith("p3 to nda")


def test_the_point_is_the_central_tendency_of_every_rate_the_asset_belongs_to(tmp_path):
    """An antibody in a haematological cancer belongs to three published populations. The
    area chain alone made twenty-seven of the fifty-five modelled pipeline assets carry
    the identical 0.4388, however different their tumour type or modality."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    got = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma")
    conn.close()
    area = 0.477 * 0.920
    antibody = 0.681 * 0.954
    heme = 0.600 * 0.900
    expected = (area * antibody * heme) ** (1 / 3)
    assert got["pos"] == pytest.approx(expected, abs=1e-4)
    assert got["pos"] > area, "the cuts must actually move it"
    assert "central tendency" in got["basis"]


def test_the_point_always_falls_inside_its_own_band(tmp_path):
    """The geometric mean is bounded by the rates it averages, which is the whole reason
    it is safe: it never asserts a rate outside everything the report publishes."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    for names, conditions in ((["etentamig"], "Multiple Myeloma"),
                              (["nemtabrutinib"], "Chronic Lymphocytic Leukemia"),
                              (["pumitamig"], "PD-L1 positive lung cancer")):
        got = _resolve(conn, names=names, conditions_text=conditions)
        assert got["low"] - 1e-9 <= got["pos"] <= got["high"] + 1e-9, names
    conn.close()


def test_an_asset_qualifying_for_no_cut_keeps_the_area_rate(tmp_path):
    """A compound named by a code number, with no readable stem and no tumour type, has
    nothing to tell it apart from its area. That is the honest answer rather than a gap."""
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    got = _resolve(conn, names=["AZD5335"], conditions_text="solid tumours")
    conn.close()
    assert got["cuts"] == []
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert "central tendency" not in got["basis"]


def test_a_failed_phase_3_is_not_outweighed_by_the_rate_its_class_usually_achieves(tmp_path):
    """Volrustomig stopped one Phase 3 for futility with others open. Blending the
    bispecific antibody rate of 68% pulled its probability UP, from 0.4388 to 0.5340. Its
    own evidence outranks its class membership."""
    conn = _seed(tmp_path,
                 trials=(("NCT1", "Active not recruiting", "2026-03-01", 500, None),
                         ("NCT2", "Recruiting", "2029-01-01", 900, None)),
                 name="etentamig",
                 readouts=(("etentamig", 3, "negative", "2026-06-01"),))
    got = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma")
    conn.close()
    assert got["stage"] == "mixed"
    assert {c["group"] for c in got["cuts"]}, "it does qualify for cuts"
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4), "no class uplift"
    assert got["low"] == 0.0, "and the band still floors at nil"


def test_the_bispecific_infix_is_read_in_full():
    """-mig is the WHO infix for a bispecific immunoglobulin. Taking only -tamig and
    -amig missed volrustomig, rilvegostomig and tobemstomig, all of them bispecifics."""
    for name in ("volrustomig", "rilvegostomig", "tobemstomig", "surovatamig",
                 "pumitamig", "etentamig"):
        assert PG.modality_of(name)[0] == "Monoclonal antibody", name
