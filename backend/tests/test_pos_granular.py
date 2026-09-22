"""A big pharma Phase 2 or 3 asset is placed at its gate, with a band, not at its
phase's entry with a point."""

import datetime as dt

import pytest

import db
import forecast
import pos_granular as PG

TODAY = dt.date(2026, 9, 22)


def _seed(tmp_path, trials=(), readouts=(), prevalence=None, unit="patients",
          name="etentamig", modality=None, phase="Phase 3"):
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


def _resolve(conn, **kw):
    args = dict(area="Oncology", phase="Phase 3", names=["etentamig"], company_id=1,
                prevalence_us=None, biomarker_selected=False,
                conditions_text="Multiple Myeloma", today=TODAY)
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
                 readouts=(("etentamig", 3, "positive", "2026-06-01"),))
    got = _resolve(conn)
    conn.close()
    assert got["pos"] == pytest.approx(0.920)
    assert got["stage"] == "positive" and "2026-06-01" in got["evidence"]


def test_a_negative_readout_with_no_open_study_is_nil(tmp_path):
    conn = _seed(tmp_path, trials=(("NCT1", "Completed", "2026-03-01", 500, None),),
                 readouts=(("etentamig", 3, "negative", "2026-06-01"),))
    got = _resolve(conn)
    conn.close()
    assert got["pos"] == 0.0 and got["stage"] == "negative"


def test_a_negative_readout_with_other_studies_open_keeps_the_gate_and_floors_the_band(tmp_path):
    """Volrustomig's lung study stopped for futility with three others recruiting to
    2030. One trial's answer is not the asset's."""
    conn = _seed(tmp_path, trials=(("NCT1", "Active not recruiting", "2026-03-01", 500, None),
                                   ("NCT2", "Recruiting", "2029-01-01", 900, None)),
                 readouts=(("etentamig", 3, "negative", "2026-06-01"),))
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
    assert got["low"] == got["pos"]
    assert got["high"] == pytest.approx(0.681 * 0.954, abs=1e-4)


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
