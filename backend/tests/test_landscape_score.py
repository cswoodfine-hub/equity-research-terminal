"""A drug's whole clinical record as two scores, and the reasons a drug has none."""

import sys
from pathlib import Path

import pytest

import landscape_score as S

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frontend"))


@pytest.mark.parametrize("text, z", [
    ("0.05", 1.96), ("<0.001", 3.29), ("0.0001", 3.89), ("p=0.01", 2.58), ("<.0001", 3.89)])
def test_a_p_value_becomes_its_normal_deviate(text, z):
    assert S.p_to_z(text) == pytest.approx(z, abs=0.01)


def test_a_p_value_that_is_not_one_scores_nothing_and_a_bound_above_never_wins():
    assert S.p_to_z(None) is None
    assert S.p_to_z("NA") is None
    assert S.p_to_z("1.4") is None
    assert S.p_to_z(">0.05") < S.Z_WIN          # "not significant" is never read as a win
    # A zero is read at the floor: it says no more than "beyond the table".
    assert S.Z_FULL < S.p_to_z("0") <= S.Z_CAP


@pytest.mark.parametrize("title, unit, want", [
    ("Overall Survival (OS)", "Months", 1),
    ("Percent Change From Baseline in Body Weight", "percent change", -1),
    ("Percentage of Participants Who Achieve ≥5% Body Weight Reduction", "participants", 1),
    ("Change in HbA1c", "percentage point", -1),
    ("Time to First Exacerbation", "days", 1),
    ("Percentage of Participants Who Died", "Percentage of Participants", -1),
    ("Participants With Change to Normoglycemia", "Participants", 1),
    ("Number of Participants With Adverse Events", "Participants", 0),      # safety, not efficacy
    ("Serum Concentration at Week 12", "ng/mL", 0),
    ("Progression-Free Survival", "Patients with a progression event", None),  # name and unit disagree
    ("Change in KCCQ Clinical Summary Score", "Score on a scale", None),       # direction not knowable
])
def test_the_direction_that_helps_the_patient_is_read_from_the_measure(title, unit, want):
    assert S.benefit_direction(title, unit) == want


def _row(aid, nct, delta, p, phase="Phase 3", arm_is_drug=True):
    return {"asset_id": aid, "nct_id": nct, "delta": delta, "p_value": p, "phase": phase,
            "arm_is_drug": arm_is_drug, "arm": f"arm {aid}", "reference_kind": "placebo"}


def _land():
    weight = {"key": "w", "title": "Percent Change From Baseline in Body Weight",
              "unit": "percent change",
              "rows": [_row(1, "N1", -20.0, "<0.001"), _row(1, "N1", -15.0, "<0.001"),
                       _row(2, "N2", -12.0, "<0.001"), _row(3, "N3", -3.0, "0.30", "Phase 2")]}
    responders = {"key": "r", "title": "Percentage of Participants Who Achieve ≥5% Weight Loss",
                  "unit": "percentage of participants",
                  "rows": [_row(1, "N1", 40.0, "<0.001"), _row(2, "N2", 30.0, "0.04")]}
    score = {"key": "q", "title": "Change in KCCQ Score", "unit": "Score on a scale",
             "rows": [_row(2, "N2", 4.0, "0.01")]}
    cands = [
        {"asset_id": 1, "name": "Alpha", "ticker": "AAA", "stage": "Marketed", "is_marketed": True,
         "boxed_warning": "WARNING: RISK OF THYROID C-CELL TUMORS In rats", "with_results": 1},
        {"asset_id": 2, "name": "Beta", "ticker": "BBB", "stage": "Phase 3", "with_results": 1},
        {"asset_id": 3, "name": "Gamma", "ticker": "BBB", "stage": "Phase 2", "with_results": 1},
        {"asset_id": 4, "name": "Delta", "ticker": "AAA", "stage": "Phase 3", "with_results": 0,
         "model": {"pos": 0.6, "per_share": 2.0}},
    ]
    safety = [
        {"asset_id": 1, "participants": 5000, "withdrawn_rate": 0.06, "placebo_withdrawn_rate": 0.03,
         "serious_rate": 0.05, "placebo_serious_rate": 0.06, "deaths_rate": 0.001,
         "placebo_deaths_rate": 0.002},
        {"asset_id": 2, "participants": 900, "withdrawn_rate": 0.04, "placebo_withdrawn_rate": 0.04,
         "serious_rate": 0.07, "placebo_serious_rate": 0.05},
        {"asset_id": 3, "participants": 60, "withdrawn_rate": 0.10, "placebo_withdrawn_rate": 0.05,
         "serious_rate": None, "placebo_serious_rate": None},
    ]
    return {"candidates": cands, "endpoints": [weight, responders, score], "safety": safety}


def test_efficacy_is_strength_wins_and_size_against_peers():
    sc = S.scorecard(_land())
    by = {a["name"]: a for a in sc["assets"]}
    alpha = by["Alpha"]["efficacy"]
    # Two endpoints, each at the p < 0.001 bound: full strength, both won, largest effect.
    assert alpha["endpoints"] == 2
    assert alpha["parts"]["strength"] == pytest.approx(100, abs=0.5)
    assert alpha["parts"]["wins"] == 100
    assert alpha["parts"]["size"] == 100                     # -20 is the largest loss of weight
    assert by["Gamma"]["efficacy"]["parts"]["size"] == 0
    assert by["Gamma"]["efficacy"]["parts"]["wins"] == 0     # p = 0.30 is not a win
    # The best dose per trial is the one scored: -20, never -15.
    assert alpha["top"]["delta"] in (-20.0, 40.0)
    # Beta's KCCQ result has a p-value but no knowable direction: counted, not scored.
    assert by["Beta"]["efficacy"]["unscored"] == 1
    assert by["Beta"]["efficacy"]["endpoints"] == 2


def test_safety_is_the_excess_over_control_less_a_boxed_warning():
    by = {a["name"]: a for a in S.scorecard(_land())["assets"]}
    alpha, beta = by["Alpha"]["safety"], by["Beta"]["safety"]
    # +3 points stopping is 75 - 15 = 60; -1 point serious is 80; mean 70, less 10 boxed.
    assert alpha["parts"] == {"staying_on": pytest.approx(60), "serious": pytest.approx(80)}
    assert alpha["score"] == pytest.approx(60)
    assert any("boxed warning" in line for line in alpha["lines"])
    assert any("Deaths, reported and not scored" in line for line in alpha["lines"])
    # The same as control is 75; +2 points serious is 65.
    assert beta["score"] == pytest.approx(70)
    # One rate is enough; a record on 60 people is scored and flagged.
    gamma = by["Gamma"]["safety"]
    assert gamma["parts"] == {"staying_on": pytest.approx(50)}
    assert any("Read with care" in line for line in gamma["lines"])


def test_overall_weighs_the_evidence_so_one_small_trial_does_not_lead():
    sc = S.scorecard(_land())
    placed = [a for a in sc["assets"] if a["placed"]]
    assert [a["name"] for a in placed] == ["Alpha", "Beta", "Gamma"]
    assert [a["rank"] for a in placed] == [1, 2, 3]
    alpha = placed[0]
    assert alpha["evidence"]["score"] == pytest.approx(25 * 3.699 - 25 + 20, abs=0.1)
    assert alpha["evidence"]["confidence"] == "high"
    assert alpha["overall"] == pytest.approx(
        (alpha["efficacy"]["score"] + alpha["safety"]["score"] + alpha["evidence"]["score"]) / 3)
    assert placed[2]["evidence"]["confidence"] == "low"          # 60 people


def test_a_drug_with_no_posted_result_is_listed_and_never_scored():
    sc = S.scorecard(_land())
    delta = next(a for a in sc["assets"] if a["name"] == "Delta")
    assert delta["placed"] is False and delta["overall"] is None
    assert delta["efficacy"]["score"] is None and delta["safety"]["score"] is None
    assert delta["why_not"] == "no posted results"
    assert (sc["placed"], sc["total"]) == (3, 4)


def test_the_map_draws_every_scored_drug_and_labels_the_open_company():
    import components.charts as CH
    sc = S.scorecard(_land())
    points = [{"name": a["name"], "ticker": a["ticker"], "x": a["efficacy"]["score"],
               "y": a["safety"]["score"], "evidence": a["evidence"]["score"],
               "stage": a["stage"], "boxed": a["boxed"], "rank": a["rank"], "tip": a["name"]}
              for a in sc["assets"] if a["placed"]]
    svg = CH.score_map(points, highlight="AAA")
    assert svg.count("<title>") == 3
    assert ">Alpha</text>" in svg and 'font-weight="700"' in svg
    assert "stroke-dasharray=\"2 2\"" in svg                 # the boxed warning ring
    assert CH.score_map([]) == ""


def test_one_measure_worded_many_ways_is_one_family_and_a_subgroup_stays_out():
    fam = lambda title, unit, param="MEAN": S.measure_family(
        {"title": title, "unit": unit, "param_type": param})
    assert fam("Percent Change From Baseline in Body Weight at Week 72", "percent change") \
        == fam("Change in Body Weight (%)", "Percentage of body weight") \
        == "percent change in body weight"
    assert fam("Change in Body Weight", "kg") is None               # another unit, another measure
    assert fam("Overall Survival (OS)", "Months") == fam("OS: ITT", "days") == "overall survival"
    assert fam("Progression-Free Survival (PFS)", "Weeks") == "progression-free survival"
    assert fam("Overall Survival (OS) in Participants With a TPS of ≥50%", "Months") is None
    assert fam("Number of Participants Who Achieved Body Weight Reduction ≥5%", "Participants",
               "COUNT_OF_PARTICIPANTS") == "share losing 5% or more of body weight"


def test_a_familys_results_share_one_scale():
    months = {"title": "Overall Survival", "unit": "Months", "param_type": "MEDIAN"}
    weeks = {"title": "Progression-Free Survival", "unit": "Weeks", "param_type": "MEDIAN"}
    counts = {"title": "Participants Losing 5%", "unit": "Participants",
              "param_type": "COUNT_OF_PARTICIPANTS"}
    assert S.comparable_delta({"delta": 3.0}, months) == 3.0
    assert S.comparable_delta({"delta": 8.69}, weeks) == pytest.approx(2.0, abs=0.01)
    # A count is a share of its own arm: 80 of 100 against 30 of 120 is 55 points.
    row = {"delta": 50.0, "value": 80.0, "n": 100, "placebo": 30.0, "placebo_n": 120}
    assert S.comparable_delta(row, counts) == pytest.approx(55.0)
    assert S.comparable_delta({"delta": 50.0, "value": 80.0, "n": None, "placebo": 30.0,
                               "placebo_n": 120}, counts) is None   # never guessed


def test_drugs_that_word_a_measure_differently_are_ranked_together():
    def group(key, title, unit, aid, delta):
        return {"key": key, "title": title, "unit": unit, "param_type": "MEAN",
                "rows": [_row(aid, f"N{aid}", delta, "<0.001")]}
    land = {"candidates": [{"asset_id": i, "name": f"D{i}", "ticker": "T", "stage": "Phase 3",
                            "with_results": 1} for i in (1, 2, 3)],
            "endpoints": [group("a", "Percent Change in Body Weight", "percent change", 1, -20.0),
                          group("b", "Change in Body Weight (%)", "Percentage of body weight", 2, -10.0),
                          group("c", "Relative Change in Body Weight", "Percentage (%) change", 3, -5.0)],
            "safety": [{"asset_id": i, "participants": 500, "withdrawn_rate": 0.05,
                        "placebo_withdrawn_rate": 0.05} for i in (1, 2, 3)]}
    by = {a["name"]: a["efficacy"]["parts"].get("size") for a in S.scorecard(land)["assets"]}
    assert by == {"D1": 100.0, "D2": 50.0, "D3": 0.0}
