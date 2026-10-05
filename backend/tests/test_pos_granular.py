"""A big pharma Phase 2 or 3 asset is placed at its gate, with a band, not at its
phase's entry with a point."""

import datetime as dt
import json
import math

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


def test_a_positive_readout_rides_along_with_its_stage_and_never_into_the_placement(tmp_path):
    """The launch floor dates from the readout stage_of read, so the stage carries it;
    resolve's output has no such key, so nothing on the rNPV path changes shape."""
    conn = _seed(tmp_path, trials=(("NCT1", "Completed", "2026-03-01", 500, None),),
                 readouts=(("XYZ-1234", 3, "positive", "2026-06-01"),))
    where = PG.stage_of(conn, 7, 1, ["XYZ-1234"], TODAY)
    placed = _resolve(conn)
    conn.close()
    assert where["readout"] == {"event_date": "2026-06-01", "nct_id": None,
                                "accession": "000-0", "drug": "XYZ-1234",
                                "cite": "on 2026-06-01 (000-0)"}
    assert "readout" not in placed


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


def test_a_failed_phase_3_never_lifts_the_asset_above_where_it_entered(tmp_path):
    """The mixed stage keeps the area chain, which is right where the cuts sit above it.
    A peptide in metabolic disease is the other case: the peptide rate sits below the
    area's, so the bare chain would put the asset higher after a failed Phase 3 than it
    stood before one. The cap holds it at the point it carried entering the phase."""
    table = PG.transitions()
    area = (table[("area", "Metabolic", "p3_to_nda")]["pos"]
            * table[("area", "Metabolic", "nda_to_approval")]["pos"])
    peptide = (table[("modality", "Peptide", "p3_to_nda")]["pos"]
               * table[("modality", "Peptide", "nda_to_approval")]["pos"])
    assert peptide < area, "the fixture needs a cut below the area chain"
    trials = (("NCT1", "Recruiting", "2028-01-01", 500, None),)
    conn = _seed(tmp_path, trials=trials, name="xyzglutide")
    before = _resolve(conn, area="Metabolic", names=["xyzglutide"],
                      conditions_text="obesity")
    conn.execute("UPDATE trials SET overall_status = 'Active not recruiting',"
                 " primary_completion_date = '2026-03-01' WHERE nct_id = 'NCT1'")
    conn.execute("INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
                 " overall_status, primary_completion_date, enrollment, title,"
                 " conditions) VALUES ('NCT2', 7, 1, 'Phase 3', 'Recruiting',"
                 " '2029-01-01', 900, 'A study', '[\"Obesity\"]')")
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('000-9', 1, 'xyzglutide', 3, 'negative',"
                 " '2026-06-01')")
    conn.commit()
    got = _resolve(conn, area="Metabolic", names=["xyzglutide"], conditions_text="obesity")
    conn.close()
    assert before["stage"] == "entering" and got["stage"] == "mixed"
    entering = (area * peptide) ** 0.5
    assert before["pos"] == pytest.approx(entering, abs=1e-4)
    assert got["pos"] == pytest.approx(entering, abs=1e-4)
    assert got["pos"] <= before["pos"] < round(area, 4)
    assert got["low"] == 0.0
    assert "capped at the" in got["basis"]


def test_the_cap_leaves_a_mixed_asset_whose_cuts_sit_above_the_area_alone(tmp_path):
    """Volrustomig and ziltivekimab: the antibody rate sits above the area chain, so the
    cap does not bind, the point stays on the chain and the basis does not change."""
    conn = _seed(tmp_path,
                 trials=(("NCT1", "Active not recruiting", "2026-03-01", 500, None),
                         ("NCT2", "Recruiting", "2029-01-01", 900, None)),
                 name="etentamig",
                 readouts=(("etentamig", 3, "negative", "2026-06-01"),))
    got = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma")
    conn.close()
    assert got["pos"] == pytest.approx(0.477 * 0.920, abs=1e-4)
    assert "capped" not in got["basis"]


def test_the_bispecific_infix_is_read_in_full():
    """-mig is the WHO infix for a bispecific immunoglobulin. Taking only -tamig and
    -amig missed volrustomig, rilvegostomig and tobemstomig, all of them bispecifics."""
    for name in ("volrustomig", "rilvegostomig", "tobemstomig", "surovatamig",
                 "pumitamig", "etentamig"):
        assert PG.modality_of(name)[0] == "Monoclonal antibody", name


# --- the gate split, the next gate and the legs ---------------------------------------

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")
MYELOMA = ("D009101", "Multiple Myeloma")
FOLLICULAR = ("D008224", "Lymphoma, Follicular")


def _rate(table, cut, group, gates):
    product = 1.0
    for gate in gates:
        product *= table[(cut, group, gate)]["pos"]
    return product


def _geomean(values):
    return math.exp(sum(math.log(v) for v in values) / len(values))


def _gate_seed(tmp_path, trials, phase="Phase 3", name="etentamig", readouts=(),
               modelled=True, stated=None):
    """An antibody modelled in multiple myeloma, its studies carrying their MeSH, so the
    next gate can tell a study in a modelled indication from one elsewhere."""
    conn = _seed(tmp_path, name=name, phase=phase, readouts=readouts)
    conn.execute("UPDATE indications SET mesh_id = ? WHERE id = 3", (MYELOMA[0],))
    conn.execute("INSERT INTO indications (id, name, mesh_id) VALUES"
                 " (4, 'Follicular lymphoma', ?)", (FOLLICULAR[0],))
    for nct, ph, status, completion, enrollment, term in trials:
        conn.execute(
            "INSERT INTO trials (nct_id, asset_id, sponsor_company_id, phase,"
            " overall_status, primary_completion_date, enrollment, title, conditions,"
            " mesh_terms) VALUES (?, 7, 1, ?, ?, ?, ?, 'A study', ?, ?)",
            (nct, ph, status, completion, enrollment, json.dumps([term[1]]),
             json.dumps({"meshes": [{"id": term[0], "term": term[1]}],
                         "ancestors": []})))
    if modelled:
        conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                     " key, value, unit) VALUES (7, 3, 'US', 'base',"
                     " 'penetration_peak_pct', 0.1, 'pct')")
    if stated is not None:
        conn.execute("INSERT INTO assumptions (asset_id, indication_id, region, scenario,"
                     " key, value) VALUES (7, NULL, 'US', 'base', 'pos', ?)", (stated,))
    conn.commit()
    return conn


def _placed(conn, phase="Phase 3", area="Oncology"):
    gathered = PG._gather(conn, 7, area=area, phase=phase, big=True)
    return gathered, PG.resolve(conn, 7, **PG._resolve_args(gathered), today=TODAY)


def _house_style(text):
    assert "—" not in text and "–" not in text, text
    assert not any(word in text.lower() for word in BANNED), text


def test_the_gates_multiply_back_to_the_unrounded_point(tmp_path):
    """Each gate is the geometric mean of the area rate and every qualifying cut's rate
    there. A geometric mean of products is the product of geometric means, so the
    split multiplies back to the central tendency of the chains, unrounded."""
    table = PG.transitions()
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    cases = (
        (dict(), [("area", "Oncology")]),
        (dict(names=["etentamig"]), [("area", "Oncology"),
                                     ("modality", "Monoclonal antibody")]),
        (dict(names=["etentamig"], conditions_text="Multiple Myeloma"),
         [("area", "Oncology"), ("modality", "Monoclonal antibody"),
          ("oncology", "Hematologic")]),
        (dict(names=["etentamig"], conditions_text="Multiple Myeloma", phase="Phase 2"),
         [("area", "Oncology"), ("modality", "Monoclonal antibody"),
          ("oncology", "Hematologic")]),
    )
    for kw, groups in cases:
        got = _resolve(conn, **kw)
        gates = tuple(g["gate"] for g in got["gates"])
        assert gates == tuple(s["gate"] for s in got["chain"])
        expected = _geomean([_rate(table, cut, group, gates) for cut, group in groups])
        assert math.prod(g["pos"] for g in got["gates"]) == pytest.approx(expected,
                                                                         abs=1e-12), kw
        assert round(expected, 4) == got["pos"]
        for g in got["gates"]:
            assert g["pos"] == pytest.approx(
                _geomean([table[(cut, group, g["gate"])]["pos"] for cut, group in groups]),
                abs=1e-15)
            assert g["label"] == PG.GATE_LABELS[g["gate"]] and g["implied"] is False
    conn.close()


def test_a_capped_mixed_stage_splits_back_to_its_point(tmp_path):
    """The mixed point is the capped area chain, so its first gate has no published rate:
    it is what the point leaves over the gates that follow, which are the ones a passed
    readout would place the asset at."""
    table = PG.transitions()
    conn = _seed(tmp_path, name="xyzglutide",
                 trials=(("NCT1", "Active not recruiting", "2026-03-01", 500, None),
                         ("NCT2", "Recruiting", "2029-01-01", 900, None)),
                 readouts=(("xyzglutide", 3, "negative", "2026-06-01"),))
    args = dict(area="Metabolic", names=["xyzglutide"], conditions_text="obesity")
    got = _resolve(conn, **args)
    passed = _resolve(conn, **args, at_gate="nda_to_approval")
    conn.close()
    gates = ("p3_to_nda", "nda_to_approval")
    entering = _geomean([_rate(table, "area", "Metabolic", gates),
                         _rate(table, "modality", "Peptide", gates)])
    assert got["stage"] == "mixed" and "capped" in got["basis"]
    assert math.prod(g["pos"] for g in got["gates"]) == pytest.approx(entering, abs=1e-12)
    assert got["gates"][0]["implied"] is True
    assert got["gates"][1:] == passed["gates"]


def test_an_uncapped_mixed_stage_splits_back_to_its_area_chain(tmp_path):
    conn = _seed(tmp_path, name="etentamig",
                 trials=(("NCT1", "Active not recruiting", "2026-03-01", 500, None),
                         ("NCT2", "Recruiting", "2029-01-01", 900, None)),
                 readouts=(("etentamig", 3, "negative", "2026-06-01"),))
    got = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma")
    conn.close()
    assert got["stage"] == "mixed"
    assert math.prod(g["pos"] for g in got["gates"]) == pytest.approx(0.477 * 0.920,
                                                                     abs=1e-12)


def test_a_negative_stage_has_no_gates(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Completed", "2026-03-01", 500, None),),
                 readouts=(("XYZ-1234", 3, "negative", "2026-06-01"),))
    got = _resolve(conn)
    conn.close()
    assert got["stage"] == "negative" and got["gates"] == []


def test_at_gate_places_the_asset_past_its_gate_by_the_same_cut_rule(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Recruiting", "2028-01-01", 500, None),))
    nda = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma",
                   at_gate="nda_to_approval")
    entry = _resolve(conn, names=["etentamig"], conditions_text="Multiple Myeloma",
                     phase="Phase 2", at_gate="p3_to_nda")
    with pytest.raises(ValueError):
        _resolve(conn, at_gate="p1_to_p2")
    conn.close()
    assert nda["stage"] == "if_met"
    assert nda["pos"] == round((0.920 * 0.954 * 0.900) ** (1 / 3), 4)
    assert nda["basis"].startswith("at the NDA/BLA gate: ")
    assert nda["evidence"] == "if its Phase 3 readout passes"
    assert entry["basis"].startswith("at Phase 3 entry: ")
    assert [g["gate"] for g in entry["gates"]] == ["p3_to_nda", "nda_to_approval"]


def test_the_legs_at_phase_3_entry_average_back_to_today(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2028-01-01", 500, MYELOMA),))
    gathered, placement = _placed(conn)
    got = PG.legs(conn, 7, placement, gathered, TODAY)
    passed = PG.resolve(conn, 7, **PG._resolve_args(gathered), today=TODAY,
                        at_gate="nda_to_approval")
    conn.close()
    assert gathered["modelled_mesh"] == [MYELOMA[0]]
    assert got["gate"] == "p3_to_nda" and got["label"] == "Phase 3 readout"
    assert got["pos_success"] == round((0.920 * 0.954 * 0.900) ** (1 / 3), 4)
    assert got["pos_failure"] == 0.0
    assert got["p_gate"] * got["pos_success"] == pytest.approx(placement["pos"], abs=1e-12)
    assert placement["pos"] == pytest.approx(got["p_gate_published"] * got["pos_success"],
                                             abs=1e-4)
    assert got["p_gate_published"] == placement["gates"][0]["pos"]
    assert got["evidence"] == {"p_gate": "published", "success": "published",
                               "failure": "convention"}
    assert got["trial"]["nct_id"] == "NCT1" and got["date"] == "2028-01-01"
    assert got["held"] is None and got["stated"] is False
    # The split's tail is the success placement's own gates, unrounded, so the split
    # meets today's four-place probability to rounding while p_gate meets it exactly.
    assert got["gates"][1:] == passed["gates"]
    assert math.prod(g["pos"] for g in got["gates"]) == pytest.approx(placement["pos"],
                                                                      abs=1e-4)
    assert "BIO/Informa/QLS" in got["basis"] and "nil" in got["basis"]
    _house_style(got["basis"])


def test_a_met_phase_3_readout_lands_on_the_success_leg(tmp_path):
    """The model's own reaction: record the readout and the asset is re-placed by its
    own chain exactly where the leg said it would be."""
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2028-01-01", 500, MYELOMA),))
    gathered, placement = _placed(conn)
    leg = PG.legs(conn, 7, placement, gathered, TODAY)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('000-9', 1, 'etentamig', 3, 'positive',"
                 " '2026-09-01')")
    conn.commit()
    _, after = _placed(conn)
    conn.close()
    assert after["stage"] == "positive"
    assert after["pos"] == leg["pos_success"]


def test_a_phase_2_readout_succeeds_to_phase_3_entry(tmp_path):
    conn = _gate_seed(tmp_path, phase="Phase 2", trials=(
        ("NCT1", "Phase 2", "Recruiting", "2027-06-01", 120, MYELOMA),))
    gathered, placement = _placed(conn, phase="Phase 2")
    got = PG.legs(conn, 7, placement, gathered, TODAY)
    conn.execute("UPDATE asset_indications SET phase = 'Phase 3' WHERE asset_id = 7")
    conn.commit()
    _, entered = _placed(conn, phase="Phase 3")
    conn.close()
    assert got["gate"] == "p2_to_p3" and got["label"] == "Phase 2 readout"
    assert got["trial"]["nct_id"] == "NCT1" and got["held"] is None
    assert got["pos_success"] == entered["pos"], "the model's own reaction to a pass"
    assert got["p_gate"] * got["pos_success"] == pytest.approx(placement["pos"], abs=1e-12)


def test_a_seamless_phase_2_3_is_gated_at_its_phase_2_readout(tmp_path):
    conn = _gate_seed(tmp_path, phase="Phase 2/3", trials=(
        ("NCT1", "Phase 2/3", "Recruiting", "2027-06-01", 300, MYELOMA),))
    gathered, placement = _placed(conn, phase="Phase 2/3")
    got = PG.legs(conn, 7, placement, gathered, TODAY)
    _, entered = _placed(conn, phase="Phase 3")
    conn.close()
    assert got["gate"] == "p2_to_p3" and got["trial"]["nct_id"] == "NCT1"
    assert got["pos_success"] == entered["pos"]


def test_after_a_positive_readout_the_gate_is_the_fda_decision(tmp_path):
    import applications
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Completed", "2026-03-01", 500, MYELOMA),),
        readouts=(("etentamig", 3, "positive", "2026-06-01"),))
    gathered, placement = _placed(conn)
    got = PG.legs(conn, 7, placement, gathered, TODAY)
    _catalyst(conn, "etentamig PDUFA, Multiple myeloma", "2027-04-01")
    applications.resolve(conn, today=TODAY)
    gathered, filed = _placed(conn)
    dated = PG.legs(conn, 7, filed, gathered, TODAY)
    conn.close()
    assert got["gate"] == "nda_to_approval" and got["label"] == "FDA decision"
    assert got["pos_success"] == 1.0 and got["p_gate"] == placement["pos"]
    assert got["trial"] is None and got["date"] is None
    assert "no accepted application" in got["why"]
    assert got["evidence"]["success"] == "convention"
    assert filed["stage"] == "filed" and dated["date"] == "2027-04-01"


def test_a_mixed_stage_succeeds_to_the_nda_step_with_implied_odds(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Active not recruiting", "2026-03-01", 500, MYELOMA),
        ("NCT2", "Phase 3", "Recruiting", "2029-01-01", 900, MYELOMA)),
        readouts=(("etentamig", 3, "negative", "2026-06-01"),))
    gathered, placement = _placed(conn)
    got = PG.legs(conn, 7, placement, gathered, TODAY)
    conn.close()
    assert placement["stage"] == "mixed"
    assert got["pos_success"] == round((0.920 * 0.954 * 0.900) ** (1 / 3), 4)
    assert got["p_gate_published"] is None and got["evidence"]["p_gate"] == "implied"
    assert abs(placement["gates"][0]["pos"] - got["p_gate"]) < 1e-4
    assert got["trial"]["nct_id"] == "NCT2" and got["held"] is None
    assert got["basis"].startswith("implied, not published")
    _house_style(got["basis"])


def test_a_negative_stage_or_a_nil_in_force_has_no_legs(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Completed", "2026-03-01", 500, MYELOMA),),
        readouts=(("etentamig", 3, "negative", "2026-06-01"),))
    gathered, placement = _placed(conn)
    assert placement["stage"] == "negative"
    assert PG.legs(conn, 7, placement, gathered, TODAY) is None
    assert PG.next_gate(conn, 7, placement, gathered["modelled_mesh"], TODAY) is None
    conn.execute("DELETE FROM trial_readouts")
    conn.commit()
    gathered, placement = _placed(conn)
    assert PG.legs(conn, 7, placement, gathered, TODAY, stated_pos=0.0) is None
    conn.close()


def test_the_reading_out_gate_is_the_passed_trial_and_a_miss_is_held(tmp_path):
    """The study stage_of named as due is the gate, and where another Phase 3 stays open
    the model's mixed rule would hold the asset after a miss. The held point is exactly
    what the model gives once that miss is recorded."""
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Active not recruiting", "2026-08-01", 900, MYELOMA),
        ("NCT2", "Phase 3", "Recruiting", "2029-01-01", 400, FOLLICULAR)))
    gathered, placement = _placed(conn)
    gate = PG.next_gate(conn, 7, placement, gathered["modelled_mesh"], TODAY)
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome,"
                 " event_date) VALUES ('000-9', 1, 'etentamig', 3, 'negative',"
                 " '2026-09-30')")
    conn.commit()
    _, missed = _placed(conn)
    conn.close()
    assert placement["stage"] == "reading_out"
    assert gate["trial"]["nct_id"] == "NCT1" and gate["due"] is True
    assert gate["date"] == "2026-08-01"
    held = gate["held"]
    assert held["open"] == 1 and held["ncts"] == ["NCT2"]
    assert held["indications"] == [FOLLICULAR[1]], "the mixed rule counts any indication"
    assert missed["stage"] == "mixed" and missed["pos"] == held["pos"]
    _house_style(held["note"])


def test_only_a_study_in_a_modelled_indication_is_the_gate(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2027-01-01", 500, FOLLICULAR),
        ("NCT2", "Phase 3", "Recruiting", "2028-06-01", 500, MYELOMA)))
    gathered, placement = _placed(conn)
    got = PG.next_gate(conn, 7, placement, gathered["modelled_mesh"], TODAY)
    assert got["trial"]["nct_id"] == "NCT2", "the sooner study is in another disease"
    conn.execute("DELETE FROM trials WHERE nct_id = 'NCT2'")
    conn.commit()
    gathered, placement = _placed(conn)
    alone = PG.next_gate(conn, 7, placement, gathered["modelled_mesh"], TODAY)
    conn.close()
    assert alone["trial"] is None and alone["date"] is None
    assert alone["why"] == ("1 open Phase 3 study, none in an indication the forecast "
                            "values")


def test_an_asset_with_no_indication_rows_is_matched_on_its_lead(tmp_path):
    """The launch-mode seeds carry no indication row; the lead indication stands in."""
    conn = _gate_seed(tmp_path, modelled=False, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2028-01-01", 500, MYELOMA),))
    gathered, placement = _placed(conn)
    got = PG.next_gate(conn, 7, placement, gathered["modelled_mesh"], TODAY)
    conn.close()
    assert gathered["modelled_mesh"] == [MYELOMA[0]]
    assert got["trial"]["nct_id"] == "NCT1"


def test_a_stated_probability_below_the_success_leg_implies_the_gate_odds(tmp_path):
    conn = _gate_seed(tmp_path, stated=0.6, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2028-01-01", 500, MYELOMA),))
    _, placement = _placed(conn)
    got = PG.legs_for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY,
                            big=True)
    conn.close()
    assert got["stated"] is True and got["placed"] is None
    assert got["pos_now"] == 0.6
    assert got["p_gate"] == pytest.approx(0.6 / got["pos_success"], abs=1e-15)
    assert got["p_gate_published"] == placement["gates"][0]["pos"]
    assert got["evidence"]["p_gate"] == "implied"
    assert got["basis"].startswith("implied, not published")
    _house_style(got["basis"])


def test_a_stated_probability_past_its_success_leg_reads_as_a_filing(tmp_path):
    """Povetacicept's case: a stated 0.884 on an asset the book holds at Phase 2, above
    the 58% it would carry entering Phase 3. The analyst has priced a filing, so the
    asset is read at the FDA decision with the stated figure as its odds."""
    conn = _gate_seed(tmp_path, stated=0.95, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2028-01-01", 500, MYELOMA),))
    got = PG.legs_for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY,
                            big=True)
    conn.close()
    assert got["placed"] == "stated PoS implies a filing"
    assert got["gate"] == "nda_to_approval" and got["label"] == "FDA decision"
    assert got["pos_success"] == 1.0 and got["p_gate"] == 0.95
    assert got["p_gate_published"] is None
    assert got["evidence"]["p_gate"] == "implied"
    assert got["passed_gate"] == "p3_to_nda" and got["pos_success_at_gate"] < 0.95
    assert got["basis"].startswith("stated PoS implies a filing")
    _house_style(got["basis"])


# --- a resolved readout catalyst is evidence -------------------------------------------

def _readout(conn, nct, status, kind="data readout", on="2026-09-20 10:00:00", cid=None):
    """A readout catalyst on the asset's own trial, resolved by hand as the stake view
    resolves it: status set and updated_at stamped, nothing else written."""
    conn.execute("INSERT INTO catalysts (id, company_id, asset_id, catalyst_type,"
                 " expected_date, title, description, is_curated, source_url, status,"
                 " updated_at) VALUES (?, 1, 7, ?, '2026-09-30', 'Phase 3, a study', ?,"
                 " 0, ?, ?, ?)",
                 (cid, kind, nct, f"https://clinicaltrials.gov/study/{nct}", status, on))
    conn.commit()


def test_a_met_readout_catalyst_lands_the_asset_on_its_success_leg(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2026-10-30", 500, MYELOMA),))
    gathered, placement = _placed(conn)
    leg = PG.legs(conn, 7, placement, gathered, TODAY)
    _readout(conn, "NCT1", "met", cid=812)
    _, after = _placed(conn)
    conn.close()
    assert placement["stage"] == "entering"
    assert after["stage"] == "positive" and after["pos"] == leg["pos_success"]
    assert after["evidence"] == ("Phase 3 read out positive on 2026-09-20, resolved met "
                                 "by hand (catalyst 812, NCT1)")
    _house_style(after["basis"])


def test_a_missed_readout_catalyst_with_nothing_else_open_is_nil(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2026-10-30", 500, MYELOMA),))
    _readout(conn, "NCT1", "missed")
    gathered, after = _placed(conn)
    assert after["stage"] == "negative" and after["pos"] == 0.0
    assert PG.legs(conn, 7, after, gathered, TODAY) is None
    conn.close()


def test_a_missed_readout_catalyst_with_another_study_open_is_held_where_it_said(tmp_path):
    """The miss is held, not nil, while another Phase 3 is open, and lands exactly on the
    held point the leg named beforehand. The study that missed is not counted among the
    open ones although the registry still lists it recruiting to a later date."""
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2026-12-01", 900, MYELOMA),
        ("NCT2", "Phase 3", "Recruiting", "2029-01-01", 400, FOLLICULAR)))
    gathered, placement = _placed(conn)
    gate = PG.next_gate(conn, 7, placement, gathered["modelled_mesh"], TODAY)
    _readout(conn, "NCT1", "missed")
    gathered, after = _placed(conn)
    regate = PG.next_gate(conn, 7, after, gathered["modelled_mesh"], TODAY)
    conn.close()
    assert gate["trial"]["nct_id"] == "NCT1" and gate["held"]["ncts"] == ["NCT2"]
    assert after["stage"] == "mixed" and after["pos"] == gate["held"]["pos"]
    assert after["pos"] <= placement["pos"]
    assert "NCT2" in after["evidence"] and "1 Phase 3 still listed open" in after["evidence"]
    # The study that answered is never the gate again; the one left is in another disease.
    assert regate["trial"] is None and "none in an indication" in regate["why"]


def test_a_missed_study_still_listed_open_is_not_counted_as_remaining(tmp_path):
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2027-06-01", 900, MYELOMA),))
    _readout(conn, "NCT1", "missed")
    _, after = _placed(conn)
    conn.close()
    assert after["stage"] == "negative", "NCT1 answered; it is not still asking"


def test_only_a_resolved_phase_3_readout_counts(tmp_path):
    """A Phase 2 readout or an advisory committee resolved by hand is not Phase 3
    evidence, and neither is a readout still pending."""
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2027-06-01", 900, MYELOMA),
        ("NCT5", "Phase 2", "Recruiting", "2026-10-01", 120, MYELOMA)))
    _readout(conn, "NCT5", "met")
    _readout(conn, "NCT1", "met", kind="AdCom")
    _readout(conn, "NCT1", "pending")
    _, after = _placed(conn)
    conn.close()
    assert after["stage"] == "entering"


def test_a_resolved_readout_outside_the_modelled_indications_moves_nothing(tmp_path):
    """The indication guard: a positive Phase 3 in another disease must not lift the
    forecast built on this one, and without the modelled indications nothing counts."""
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2027-06-01", 900, MYELOMA),
        ("NCT2", "Phase 3", "Recruiting", "2026-10-01", 400, FOLLICULAR)))
    _readout(conn, "NCT2", "met")
    _, after = _placed(conn)
    _readout(conn, "NCT1", "met")
    gathered, placed = _placed(conn)
    blind = PG.resolve(conn, 7, **{**PG._resolve_args(gathered), "modelled_mesh": None},
                       today=TODAY)
    conn.close()
    assert after["stage"] == "entering"
    assert placed["stage"] == "positive" and "NCT1" in placed["evidence"]
    assert blind["stage"] == "entering"


def test_for_asset_reads_the_resolved_readout_on_the_rnpv_path(tmp_path):
    """assumptions.load calls for_asset, which gathers the modelled indications and
    hands them through: the forecast sees a resolved readout, guard and all."""
    conn = _gate_seed(tmp_path, trials=(
        ("NCT1", "Phase 3", "Recruiting", "2027-06-01", 900, MYELOMA),))
    real = PG.big_pharma
    PG.big_pharma = lambda *a, **k: True
    try:
        before = PG.for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY)
        _readout(conn, "NCT1", "met")
        after = PG.for_asset(conn, 7, area="Oncology", phase="Phase 3", today=TODAY)
    finally:
        PG.big_pharma = real
    conn.close()
    assert before["stage"] == "entering" and after["stage"] == "positive"
