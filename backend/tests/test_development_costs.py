"""The published development costs: transcribed from the source's own table, every row
sourced, priced in its own year, and a bad row refused rather than read."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import development as D

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sertkaya2024_table1.xml"
AREAS = ("Anti-infective", "Cardiovascular", "Central nervous system", "Dermatology",
         "Endocrine", "Gastrointestinal", "Genitourinary system", "Hematology", "Oncology",
         "Respiratory system", "Ophthalmology", "Pain and anesthesia", "Immunomodulation",
         "All")


def _table1():
    """{(section, row): [14 values]} from the saved PMC XML of Sertkaya 2024 Table 1."""
    root = ET.parse(FIXTURE).getroot()
    out, section = {}, None
    for tr in root.iter("tr"):
        cells = [" ".join("".join(c.itertext()).split()) for c in tr if c.tag in ("td", "th")]
        if len(cells) > 1 and all(c == "" for c in cells[1:]):
            section = cells[0]
        elif section:
            out[(section, cells[0])] = [c.replace(" ", "") for c in cells[1:]]
    return out


def test_the_loader_returns_the_published_figures():
    t = D.costs_table()
    spot = {("Oncology", "3", "per_patient_usd"): 93145,
            ("Hematology", "3", "per_patient_usd"): 118473,
            ("Endocrine", "3", "per_patient_usd"): 48753,
            ("All", "2", "per_patient_usd"): 58618,
            ("All", "3", "programme_oop_musd"): 89.3,
            ("Ophthalmology", "3", "programme_oop_musd"): 173.0,
            ("All", "review", "review_oop_musd"): 2.6}
    for (area, phase, measure), value in spot.items():
        assert t[("sertkaya2024", area, phase, measure)]["value"] == value
    dimasi = t[("dimasi2016", "All", "3", "phase_mean_musd")]
    assert dimasi["value"] == 255.4 and dimasi["n"] == 42 and dimasi["price_year"] == 2013
    assert t[("dimasi2016", "All", "2", "phase_mean_musd")]["value"] == 58.6


def test_every_figure_matches_the_source_table_it_was_read_from():
    """All 14 columns of each measure against Table 1 as PMC serves it, so the seven
    areas no one cross-checked by hand are pinned with the rest."""
    t, table1 = D.costs_table(), _table1()
    rows = {("2", "per_patient_usd"): ("Per-patient cost (2018), $", "Phase 2"),
            ("3", "per_patient_usd"): ("Per-patient cost (2018), $", "Phase 3"),
            ("2", "programme_oop_musd"): ("Out-of-pocket estimates (millions), $", "Phase 2"),
            ("3", "programme_oop_musd"): ("Out-of-pocket estimates (millions), $", "Phase 3"),
            ("2", "duration_months"): ("Phase durations, mo", "Phase 2"),
            ("3", "duration_months"): ("Phase durations, mo", "Phase 3")}
    for (phase, measure), key in rows.items():
        for area, printed in zip(AREAS, table1[key]):
            assert t[("sertkaya2024", area, phase, measure)]["value"] == float(printed), (
                area, phase, measure)
    assert set(table1[("Out-of-pocket estimates (millions), $", "FDA review")]) == {"2.6"}


def test_every_row_is_sourced_graded_and_priced_in_its_year():
    t = D.costs_table()
    assert len(t) == 6 * 14 + 1 + 2
    for key, row in t.items():
        assert row["source"] and row["grade"] == "analogue", key
        assert row["price_year"] == (2018 if key[0] == "sertkaya2024" else 2013), key
        assert ("PMC11214120" in row["source"] or "jhealeco.2016.01.012" in row["source"]), key


def test_the_header_states_the_four_caveats_and_the_corrected_arithmetic():
    header = "".join(line for line in D.COSTS.read_text(encoding="utf-8").splitlines(True)
                     if line.startswith("#"))
    assert "93,145 per patient x 293 patients per trial x 1.63" in header
    assert "$44.5mm against 37.7 printed" in header
    assert "no price index" in header and "Phase 1 is deliberately absent" in header
    assert "long-term animal" in header and "fail within" in header
    assert round(93145 * 293 * 1.63 / 1e6, 1) == 44.5


def test_the_dimasi_ratio_is_its_mean_over_sertkayas_all_row():
    ratio = D.dimasi_ratio(D.costs_table())
    assert ratio["2"] == pytest.approx(58.6 / 21.0)
    assert ratio["3"] == pytest.approx(255.4 / 89.3)


@pytest.mark.parametrize("bad", [
    "sertkaya2024,Oncology,3,per_patient_usd,not a number,2018,,analogue,a source",
    "sertkaya2024,Oncology,3,per_patient_usd,93145,2018,,analogue,",
    "sertkaya2024,Oncology,3,per_patient_usd,93145,,,analogue,a source",
])
def test_a_bad_row_is_refused(tmp_path, bad):
    path = tmp_path / "costs.csv"
    path.write_text("# a comment\nsource_id,area,phase,measure,value,price_year,n,grade,source\n"
                    "sertkaya2024,All,review,review_oop_musd,2.6,2018,,analogue,a source\n"
                    + bad + "\n", encoding="utf-8")
    with pytest.raises(D.CostTableError):
        D.costs_table(path)


def test_the_area_map_says_how_it_read_each_area():
    assert D.cost_area("Oncology")[0] == "Oncology"
    assert D.cost_area("Metabolic") == ("Endocrine", "Metabolic read as Sertkaya's Endocrine:"
                                        " Sertkaya has no metabolic class, so the endocrine"
                                        " rates stand in for it")
    for area in ("Renal and hepatic", "Healthy volunteers", None):
        assert D.cost_area(area)[0] == "All"
    t = D.costs_table()
    for area in D.AREA_TO_SOURCE.values():
        assert ("sertkaya2024", area, "3", "per_patient_usd") in t, area
