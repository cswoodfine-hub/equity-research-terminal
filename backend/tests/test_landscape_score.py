"""A drug's whole clinical record as two scores, and the reasons a drug has none.

The method is docs/design/clinical-scorecard-statistics.md; the numbered tests follow its
section 7.2 and the book guard its section 7.3."""

import json
import math
import os
import sys
import time
from pathlib import Path

import pytest

import landscape_score as S
import meta_stats as M

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "frontend"))

Z95 = M.z_of_level(95)
WEIGHT = ("Percent Change From Baseline in Body Weight", "percent change")
HBA1C = ("Change From Baseline in HbA1c", "percent")
BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament", "—")


# --- builders -------------------------------------------------------------------------------
def _row(aid, nct, delta, *, outcome=0, cat=None, cat_index=0, arm=None, n=100, n0=100,
         value=None, ref=0.0, ci=None, level=95.0, est=None, etype=None, p=None, method=None,
         param="LEAST_SQUARES_MEAN", disp=None, spread=None, ref_spread=None, lower=None,
         upper=None, ref_arm="Placebo", kind="placebo", names=True, control=False,
         ref_is_drug=False, h2h=None, weeks=52.0, time_frame=None, phase="Phase 3",
         analyses=None):
    """One arm of one trial against its comparator, with the keys landscape.endpoints
    passes. An analysis row is posted where an interval or a p-value is given."""
    if value is None and delta is not None:
        value = ref + delta
    if analyses is None:
        analyses = []
        if ci is not None or p is not None:
            analyses.append({"method": method, "param_type": etype,
                             "param_value": est if est is not None else delta,
                             "ci_pct": level if ci is not None else None,
                             "ci_lower": ci[0] if ci else None,
                             "ci_upper": ci[1] if ci else None, "p_value": p})
    return {"asset_id": aid, "name": f"D{aid}", "ticker": "T", "nct_id": nct, "phase": phase,
            "weeks": weeks, "time_frame": time_frame, "category": cat,
            "arm": arm or f"D{aid} 10 mg", "arm_is_drug": names, "n": n, "value": value,
            "value_text": None, "spread": spread, "dispersion": disp, "placebo": ref,
            "reference_kind": kind, "reference_arm": ref_arm, "placebo_n": n0, "delta": delta,
            "p_value": p, "estimate": est, "ci": list(ci) if ci else None,
            "outcome_index": outcome, "outcome_type": "PRIMARY", "category_index": cat_index,
            "param": param, "lower": lower, "upper": upper, "reference_spread": ref_spread,
            "reference_lower": None, "reference_upper": None, "arm_is_control": control,
            "arm_names_drug": names, "reference_is_drug": ref_is_drug, "head_to_head": h2h,
            "analyses": analyses}


def _z(aid, nct, z, measure=WEIGHT, **kw):
    """A result on a lower-is-better measure whose z is exactly ``z``: the sponsor's
    difference of -z with a 95% interval of width 2 z(95), so a standard error of 1."""
    return _row(aid, nct, -z, ci=(-z - Z95, -z + Z95), **kw)


def _group(key, title, unit, rows, param_type="LEAST_SQUARES_MEAN"):
    return {"key": key, "title": title, "unit": unit, "param_type": param_type, "rows": rows}


def _cand(aid, name=None, stage="Phase 3", boxed=None, classes=None, with_results=1,
          ticker="T", model=None):
    return {"asset_id": aid, "name": name or f"D{aid}", "ticker": ticker, "stage": stage,
            "is_marketed": stage == "Marketed", "boxed_warning": boxed,
            "classes": classes or [], "mechanisms": [], "with_results": with_results,
            "model": model}


def _counts(serious=(0, 0), withdrawn=(0, 0), deaths=(0, 0)):
    return {"serious": list(serious), "withdrawn": list(withdrawn), "deaths": list(deaths)}


def _arm_counts(title, is_control=False, **kw):
    return {"title": title, "is_control": is_control, **_counts(**kw)}


def _stratum(nct, arms, control, kind="placebo", title="Placebo", is_drug=False):
    return {"nct_id": nct, "phase": "Phase 3", "kind": kind if control else None,
            "arms": len(arms), "control_title": title if control else None,
            "control_is_drug": is_drug, "control": control, "arm_rows": arms}


def _plain(nct, n=500, serious=(25, 20), withdrawn=(15, 10), kind="placebo"):
    """A controlled stratum of n on each side with these events on drug and control."""
    return _stratum(nct, [_arm_counts("Drug", serious=(serious[0], n),
                                      withdrawn=(withdrawn[0], n), deaths=(1, n))],
                    _counts(serious=(serious[1], n), withdrawn=(withdrawn[1], n), deaths=(1, n)),
                    kind=kind)


def _safe(aid, strata):
    people = sum(sum(a["serious"][1] or a["withdrawn"][1] for a in s["arm_rows"])
                 for s in strata)
    return {"asset_id": aid, "trials": len(strata), "participants": people or None,
            "strata": strata}


def _land(groups, cands, safety=None):
    if safety is None:
        safety = [_safe(c["asset_id"], [_plain(f"S{c['asset_id']}")]) for c in cands]
    return {"candidates": cands, "endpoints": groups, "safety": safety}


def _by(sc):
    return {a["name"]: a for a in sc["assets"]}


def _general():
    """Four drugs on body weight against placebo with enough trials to rank it (five
    degrees of freedom), one with only a p-value, one with no posted result."""
    rows = [_row(1, "N1a", -20.0, ci=(-22.0, -18.0), arm="D1 10 mg"),
            _row(1, "N1a", -15.0, ci=(-17.0, -13.0), arm="D1 5 mg"),
            _row(1, "N1b", -18.0, ci=(-20.0, -16.0)), _row(1, "N1c", -19.0, ci=(-21.0, -17.0)),
            _row(2, "N2a", -12.0, ci=(-14.0, -10.0)), _row(2, "N2b", -10.0, ci=(-12.0, -8.0)),
            _row(2, "N2c", -9.0, ci=(-11.0, -7.0)),
            _row(3, "N3", -3.0, p="0.30", phase="Phase 2"),
            _row(5, "N5a", -8.0, ci=(-10.0, -6.0)), _row(5, "N5b", -6.0, ci=(-8.0, -4.0))]
    cands = [_cand(1, "Alpha", "Marketed", boxed="WARNING: RISK OF THYROID C-CELL TUMORS In rats"),
             _cand(2, "Beta"), _cand(3, "Gamma", "Phase 2"),
             _cand(4, "Delta", with_results=0, model={"pos": 0.6, "per_share": 2.0}),
             _cand(5, "Epsilon")]
    safety = [_safe(1, [_plain("N1a", 2000, (100, 120), (60, 30)),
                        _plain("N1b", 1500, (80, 90), (40, 20))]),
              _safe(2, [_plain("N2a", 800, (40, 40), (20, 20))]),
              _safe(3, [_plain("N3", 60, (3, 3), (6, 3))]),
              _safe(5, [_plain("N5a", 300, (20, 15), (9, 6))])]
    return _land([_group("w", *WEIGHT, rows)], cands, safety)


# --- p-values, direction and families (kept) ------------------------------------------------
@pytest.mark.parametrize("text, z", [
    ("0.05", 1.96), ("<0.001", 3.29), ("0.0001", 3.89), ("p=0.01", 2.58), ("<.0001", 3.89)])
def test_a_p_value_becomes_its_normal_deviate(text, z):
    assert S.p_to_z(text) == pytest.approx(z, abs=0.01)


def test_a_p_value_that_is_not_one_scores_nothing_and_a_bound_above_gives_no_z():
    assert S.p_to_z(None) is None
    assert S.p_to_z("NA") is None
    assert S.p_to_z("1.4") is None
    assert S.p_to_z(">0.05") is None      # nothing is made up from the middle of the bound
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
    ("Number of Participants Who Experienced an AE", "Participants", 0),
    ("Participants Meeting Marked Abnormality Criteria", "Participants", 0),
    ("Serum Concentration at Week 12", "ng/mL", 0),
    ("Progression-Free Survival", "Patients with a progression event", None),  # name and unit disagree
    ("Change in KCCQ Clinical Summary Score", "Score on a scale", 1),     # the instrument: higher is better
])
def test_the_direction_that_helps_the_patient_is_read_from_the_measure(title, unit, want):
    assert S.benefit_direction(title, unit) == want


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


def test_10_a1c_is_hba1c():
    fam = lambda title: S.measure_family({"title": title, "unit": "percent", "param_type": "MEAN"})
    assert fam("Change From Baseline in Hemoglobin A1C (A1C)") == "change in HbA1c"
    assert fam("Change in A1C") == "change in HbA1c"
    assert fam("Change From Baseline in HbA1c") == "change in HbA1c"


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


def test_drugs_that_word_a_measure_differently_share_one_cell():
    groups = [_group("a", "Percent Change in Body Weight", "percent change",
                     [_z(1, "N1", 4.0)]),
              _group("b", "Change in Body Weight (%)", "Percentage of body weight",
                     [_z(2, "N2", 3.0)]),
              _group("c", "Relative Change in Body Weight", "Percentage (%) change",
                     [_z(3, "N3", 2.0)])]
    built = S._build(_land(groups, [_cand(i) for i in (1, 2, 3)]))
    cell = built["pooled"][("percent change in body weight", "placebo alone")]
    assert sorted(cell) == [1, 2, 3]


# --- one result per drug, trial and outcome -------------------------------------------------
def test_1_doses_are_tested_together_and_sized_on_the_top_arm():
    rows = [_row(1, "N1", -20.0, ci=(-22.0, -18.0), arm="Alpha 10 mg"),
            _row(1, "N1", -10.0, ci=(-12.0, -8.0), arm="Alpha 5 mg")]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1, "Alpha")])))["Alpha"]["efficacy"]
    assert ef["endpoints"] == 1 and ef["trials"] == 1          # the trial counts once
    assert ef["top"]["effect"] == pytest.approx(15.0, abs=1e-3)
    assert ef["top"]["se"] == pytest.approx(0.8837, abs=1e-3)
    assert ef["top"]["arms"] == 2
    lead = ef["pooled"][0]
    assert lead["effect"] == pytest.approx(19.593, abs=1e-3)   # 20 - 0.5642 x 0.7215
    assert lead["se"] == pytest.approx(1.0204, abs=1e-3)
    assert lead["top_dose"] == 1
    assert any("several doses" in n for n in ef["notes"])


def test_2_a_complement_is_never_the_result():
    title = "Number of Participants Who Achieved ≥5% Weight Loss"
    rows = [_row(1, "N1", -40.0, value=40.0, ref=80.0, cat="No", cat_index=0,
                 param="COUNT_OF_PARTICIPANTS"),
            _row(1, "N1", 40.0, value=60.0, ref=20.0, cat="Yes", cat_index=1,
                 param="COUNT_OF_PARTICIPANTS")]
    ef = _by(S.scorecard(_land([_group("r", title, "Participants", rows, "COUNT_OF_PARTICIPANTS")],
                                [_cand(1)])))["D1"]["efficacy"]
    assert ef["top"]["effect"] == pytest.approx(40.0)          # 60 of 100 against 20 of 100
    assert ef["routes"] == {"counts": 1}
    assert ef["wins"] == 1


def test_3_a_baseline_is_not_scored():
    groups = [_group("w", *WEIGHT, [_z(1, "N1", 3.0)]),
              _group("b", "Baseline Body Weight", "kg", [_row(1, "N1", -2.0, p="0.01")], "MEAN")]
    ef = _by(S.scorecard(_land(groups, [_cand(1)])))["D1"]["efficacy"]
    assert ef["endpoints"] == 1 and ef["unscored"] == 0


def test_4_a_control_arm_is_never_pooled_and_an_untested_arm_is_left_out():
    rows = [_row(1, "N1", -10.0, ci=(-12.0, -8.0), arm="D1 10 mg"),
            _row(1, "N1", -30.0, arm="D1 cohort B"),                       # no analysis row
            _row(1, "N1", -25.0, ci=(-27.0, -23.0), arm="Standard of care", control=True)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]["efficacy"]
    assert ef["top"]["arms"] == 1
    assert ef["top"]["effect"] == pytest.approx(10.0)


def test_5_a_total_arm_is_dropped():
    rows = [_row(1, "N1", -10.0, ci=(-12.0, -8.0), n=100, arm="D1 5 mg"),
            _row(1, "N1", -14.0, ci=(-16.0, -12.0), n=100, arm="D1 10 mg"),
            _row(1, "N1", -12.0, ci=(-13.5, -10.5), n=200, arm="D1 5 mg and 10 mg")]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]["efficacy"]
    assert ef["top"]["arms"] == 2
    assert ef["top"]["effect"] == pytest.approx(12.0)


def test_6_the_interval_outranks_the_p_value():
    # VERTIS CV: a non-inferiority p-value beside an interval that includes 1.
    row = _row(1, "N1", 0.5, value=20.0, ref=19.5, param="MEDIAN", est=0.97,
               etype="Hazard Ratio (HR)", ci=(0.848, 1.114), level=95.6, p="<0.001")
    ef = _by(S.scorecard(_land([_group("os", "Overall Survival (OS)", "Months", [row], "MEDIAN")],
                                [_cand(1)])))["D1"]["efficacy"]
    assert ef["z"] == pytest.approx(0.45, abs=0.01)
    assert ef["wins"] == 0
    assert ef["routes"] == {"hazard ratio interval": 1}


def test_7_an_arm_spread_is_read_and_a_least_squares_mean_with_a_standard_deviation_is_not():
    row = _row(1, "N1", -0.34, value=-1.56, ref=-1.22, n=225, n0=222, param="MEAN",
               disp="Standard Deviation", spread=1.09, ref_spread=1.16)
    ef = _by(S.scorecard(_land([_group("h", *HBA1C, [row], "MEAN")], [_cand(1)])))["D1"]["efficacy"]
    assert ef["z"] == pytest.approx(3.19, abs=0.01)
    assert ef["routes"] == {"arm spread": 1}
    ls = _row(1, "N1", -1.0, value=-2.0, ref=-1.0, n=45, n0=45, param="LEAST_SQUARES_MEAN",
              disp="Standard Deviation", spread=0.1, ref_spread=0.1)
    sc = S.scorecard(_land([_group("h", *HBA1C, [ls])], [_cand(1)]))
    ef = _by(sc)["D1"]["efficacy"]
    assert ef["score"] is None and ef["unscored_why"] == {"nothing to test": 1}


def test_8_a_rate_is_not_a_share():
    row = _row(1, "N1", -2.0, value=3.0, ref=5.0, param="NUMBER")
    g = _group("e", "Rate of Hypoglycaemia Episodes", "Episodes per 100 patient-years", [row],
               "NUMBER")
    ef = _by(S.scorecard(_land([g], [_cand(1)])))["D1"]["efficacy"]
    assert "counts" not in ef["routes"]
    assert ef["unscored_why"] == {"nothing to test": 1}


def test_9_a_family_fixes_the_sign_and_events_are_lower_is_better():
    assert S.benefit_direction("Change From Baseline to Week 26 in HbA1c Bayesian Dose Response",
                               "percentage of HbA1c") == -1
    title = "Percentage of Participants With Invasive Disease-Free Survival (IDFS) Event"
    row = _row(1, "N1", -1.6, value=7.1, ref=8.7, n=2400, n0=2404, param="NUMBER")
    ef = _by(S.scorecard(_land([_group("e", title, "percentage of participants", [row], "NUMBER")],
                                [_cand(1)])))["D1"]["efficacy"]
    assert ef["z"] == pytest.approx(2.06, abs=0.01)             # fewer events: for the drug
    assert ef["routes"] == {"counts": 1}


def test_11_survival_needs_a_hazard_ratio():
    row = _row(1, "N1", 0.1, value=5.8, ref=5.7, param="MEDIAN",
               disp="95% Confidence Interval", lower=5.1, upper=6.5)
    sc = S.scorecard(_land([_group("pfs", "Progression-Free Survival", "Months", [row], "MEDIAN")],
                           [_cand(1)]))
    d = _by(sc)["D1"]
    assert d["efficacy"]["score"] is None
    assert d["efficacy"]["unscored_why"] == {"no hazard ratio": 1}
    assert d["why_not"] == "time-to-event results with no hazard ratio posted"
    assert "ratio of medians" not in json.dumps(sc)


def test_12_a_result_is_the_drugs_only_where_its_arm_names_it_and_the_comparator_does_not():
    cands = [_cand(1, "Sitagliptin"), _cand(2, "Pembrolizumab"), _cand(3, "Nivolumab"),
             _cand(4, "Insulin icodec"), _cand(5, "Dulaglutide")]
    rows = [_z(1, "N1", 3.0, ref_arm="Placebo + Sitagliptin", ref_is_drug=True),
            _z(2, "N2", 3.0, ref_arm="Pembro + Placebo (Maintenance Phase)"),
            _z(3, "N3", 3.0, ref_arm="Arm B: Nivo Placebo + Chemo"),
            _z(4, "N4", 3.0, ref_arm="Insulin Glargine", kind="comparator"),
            _z(5, "N5", 3.0, arm="Orforglipron 12 mg", names=False)]
    by = _by(S.scorecard(_land([_group("h", *HBA1C, rows)], cands)))
    assert by["Sitagliptin"]["efficacy"]["unscored_why"] == {"in both arms": 1}
    assert by["Pembrolizumab"]["efficacy"]["unscored_why"] == {"in both arms": 1}
    assert by["Nivolumab"]["efficacy"]["endpoints"] == 1
    assert by["Insulin icodec"]["efficacy"]["endpoints"] == 1
    assert by["Dulaglutide"]["efficacy"]["unscored_why"] == {"not its arm": 1}
    assert by["Dulaglutide"]["why_not"] == "no result on an arm that is the drug's alone"
    toks = S.name_tokens({"name": "Pembrolizumab"})
    assert S.names_drug_short("Pembro + Placebo", toks)
    assert not S.names_drug_short("Arm B: Nivo Placebo + Chemo", S.name_tokens({"name": "Nivolumab"}))
    assert not S.names_drug_short("Insulin Glargine", S.name_tokens({"name": "Insulin icodec"}))


# --- strength and wins ------------------------------------------------------------------------
def test_13_strength_is_the_mean_trial_z():
    two_trials = [_z(1, "N1", 2.77), _z(1, "N2", 2.62)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, two_trials)], [_cand(1)])))["D1"]["efficacy"]
    assert ef["parts"]["strength"] == pytest.approx(81.9, abs=0.05)
    one_trial = [_group("w", *WEIGHT, [_z(1, "N1", 2.77)]),
                 _group("h", *HBA1C, [_z(1, "N1", 2.62, outcome=1)])]
    ef = _by(S.scorecard(_land(one_trial, [_cand(1)])))["D1"]["efficacy"]
    assert ef["parts"]["strength"] == pytest.approx(81.9, abs=0.05)
    assert ef["trials"] == 1 and ef["endpoints"] == 2
    ten = [_z(1, f"N{i}", 6.0) for i in range(10)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, ten)], [_cand(1)])))["D1"]["efficacy"]
    assert ef["parts"]["strength"] == 100.0 and ef["z"] == pytest.approx(5.0)


def test_14_wins_allow_for_the_number_of_tests():
    from statistics import NormalDist
    zs = [NormalDist().inv_cdf(1 - p) for p in
          (0.0006, 0.0031, 0.0193, 0.0199, 0.0421, 0.1049, 0.1666)]
    # Seven endpoints of one trial: corrected for the seven that trial tested.
    rows = [_z(1, "N1", z, outcome=i) for i, z in enumerate(zs)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]["efficacy"]
    assert (ef["wins"], ef["wins_unadjusted"], ef["endpoints"]) == (2, 4, 7)
    assert ("4 endpoints cleared p = 0.05 before allowing for the number each trial tested."
            in ef["notes"])
    assert ef["lines"][0].startswith(
        "Won 2 of 7 endpoints in 1 trial, allowing for the number each trial tested")
    # The same seven results from seven trials: each trial controls its own error rate.
    rows = [_z(1, f"N{i}", z) for i, z in enumerate(zs)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]["efficacy"]
    assert (ef["wins"], ef["wins_unadjusted"], ef["endpoints"]) == (4, 4, 7)
    # Results against the drug loosen nothing.
    rows = [_z(1, "N1", -3.29, outcome=i) for i in range(4)] + [_z(1, "N1", 2.054, outcome=9)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]["efficacy"]
    assert ef["wins"] == 0
    # A lone posted "<0.05" is a win.
    legacy = {"asset_id": 1, "nct_id": "N1", "delta": -3.0, "p_value": "<0.05", "phase": "Phase 3",
              "arm_is_drug": True, "arm": "D1", "reference_kind": "placebo"}
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, [legacy])], [_cand(1)])))["D1"]["efficacy"]
    assert ef["wins"] == 1 and ef["routes"] == {"p-value bound": 1}
    # Wins are the mean over trials of each trial's share won.
    groups = [_group("w", *WEIGHT, [_z(1, "A", 5.0), _z(1, "B", 5.0)]),
              _group("h", *HBA1C, [_z(1, "A", 0.5, outcome=1)])]
    ef = _by(S.scorecard(_land(groups, [_cand(1)])))["D1"]["efficacy"]
    assert ef["wins"] == 2 and ef["parts"]["wins"] == pytest.approx(75.0)


# --- averaging and size ------------------------------------------------------------------------
def test_15_one_between_trial_variance_per_measure():
    rows = [_z(1, "A1", 10.0), _z(1, "A2", 14.0), _z(1, "A3", 18.0), _z(2, "B1", 12.0)]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1), _cand(2)])))
    a, b = ef["D1"]["efficacy"]["pooled"][0], ef["D2"]["efficacy"]["pooled"][0]
    assert a["tau2"] == pytest.approx(15.0) and a["tau2_df"] == 2
    assert b["se"] ** 2 == pytest.approx(1.0 + 15.0)
    assert b["se"] > a["se"]
    assert (b["own_lo"], b["own_hi"]) == pytest.approx((12.0 - Z95, 12.0 + Z95))
    assert (a["participants"], b["participants"]) == (300, 100)


def test_people_behind_an_average_are_never_a_partial_count():
    rows = [_z(1, "A1", 10.0), _z(1, "A2", 14.0, n=None)]
    entry = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]
    pooled = entry["efficacy"]["pooled"][0]
    assert pooled["k"] == 2 and pooled["participants"] is None


def test_16_the_control_key():
    for title in ("Placebo + Docetaxel 75 mg/m^2", "Placebo/Docetaxel", "Docetaxel"):
        assert S.control_key(title, "placebo") == "docetaxel"
    assert S.control_key("Chemotherapy", "control") is None
    assert S.control_key("Physician's Choice", "control") is None
    assert S.control_key("Placebo", "placebo") == "placebo alone"
    rows = ([_z(i, f"L{i}", 2.0, ref_arm="Placebo + Letrozole") for i in (1, 2, 3)]
            + [_z(i, f"P{i}", 2.0) for i in (4, 5, 6)])
    built = S._build(_land([_group("w", *WEIGHT, rows)], [_cand(i) for i in range(1, 7)]))
    cells = {k[1]: sorted(v) for k, v in built["pooled"].items()}
    assert cells == {"letrozole": [1, 2, 3], "placebo alone": [4, 5, 6]}
    assert _by(built["out"])["D1"]["efficacy"]["pooled"][0]["control"] == "Letrozole"


def test_17_a_measure_is_ranked_only_on_five_degrees_of_freedom():
    rows = [_z(1, "A1", 10.0), _z(1, "A2", 11.0), _z(2, "B1", 6.0), _z(2, "B2", 7.0),
            _z(3, "C1", 3.0)]
    cands = [_cand(i) for i in range(1, 7)]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], cands)))
    for name in ("D1", "D2", "D3"):
        ef = by[name]["efficacy"]
        assert "size" not in ef["parts"] and ef["size_basis"] is None
        assert ef["pooled"][0]["ranked"] is False and ef["pooled"][0]["rank"] is None
    assert by["D3"]["efficacy"]["lines"][2] == (
        "Size against peers not known: how far trials differ on percent change in body "
        "weight rests on too few trials to compare drugs, so efficacy is strength and wins alone.")
    # Three more drugs of two trials each on the measure, against metformin: 5 degrees.
    more = [_z(i, f"M{i}{j}", 4.0 + j, ref_arm="Metformin", kind="comparator")
            for i in (4, 5, 6) for j in (1, 2)]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows + more)], cands)))
    for name in ("D1", "D2", "D3"):
        ef = by[name]["efficacy"]
        assert ef["size_basis"] == "ranked" and "size" in ef["parts"]
        assert ef["pooled"][0]["tau2_df"] == 5 and ef["pooled"][0]["of"] == 3
    assert by["D1"]["efficacy"]["pooled"][0]["rank"] == 1


def test_18_a_result_stated_twice_counts_once(monkeypatch):
    monkeypatch.setattr(S, "TAU_DF_MIN", 1)
    share = ("Percentage of Participants Losing ≥5% Body Weight", "percentage of participants")
    w = [_z(1, "A1", 9.0), _z(1, "A2", 10.0), _z(2, "B1", 6.0), _z(3, "C1", 4.0),
         _z(4, "D1", 3.0)]
    s = [_row(1, "A1", 40.0, value=60.0, ref=20.0, param="NUMBER", outcome=1),
         _row(1, "A2", 35.0, value=55.0, ref=20.0, param="NUMBER", outcome=1),
         _row(2, "B1", 30.0, value=50.0, ref=20.0, param="NUMBER", outcome=1),
         _row(3, "C1", 20.0, value=40.0, ref=20.0, param="NUMBER", outcome=1)]
    groups = [_group("w", *WEIGHT, w), _group("s", *share, s, "NUMBER")]
    ef = _by(S.scorecard(_land(groups, [_cand(i) for i in range(1, 5)])))["D1"]["efficacy"]
    counted = [(e["measure"], e["counted"]) for e in ef["pooled"] if e["ranked"]]
    assert counted == [("percent change in body weight", True),
                       ("share losing 5% or more of body weight", False)]
    assert ("Also posted share losing 5% or more of body weight against placebo, from most of "
            "the same trials, so not counted a second time.") in ef["notes"]


def test_19_the_class_average_applies_only_at_four():
    glp = ["GLP-1 agonist"]
    rows = [_z(i, f"N{i}", 2.0 + i) for i in range(1, 7)]
    cands = [_cand(i, classes=glp if i <= 4 else ["SGLT2 inhibitor"]) for i in range(1, 7)]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], cands)))
    for i in range(1, 7):
        entry = by[f"D{i}"]["efficacy"]["pooled"][0]
        if i <= 4:
            assert entry["prior"] == {"label": "GLP-1 agonist", "n": 4, "mean": pytest.approx(
                entry["prior"]["mean"])}
            assert 0 < entry["weight"] <= 1 / 3 + 1e-12
        else:
            assert entry["prior"] is None and entry["weight"] == 0.0
    three = [_cand(i, classes=glp if i <= 3 else None) for i in range(1, 7)]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], three)))
    assert all(by[f"D{i}"]["efficacy"]["pooled"][0]["prior"] is None for i in range(1, 7))


def test_20_equal_effects_share_a_rank_and_a_coin_toss_cannot_be_separated(monkeypatch):
    monkeypatch.setattr(S, "TAU_DF_MIN", 1)
    rows = [_z(1, "A1", 10.0), _z(2, "B1", 10.0), _z(3, "C1", 5.0), _z(3, "C2", 5.2)]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(i) for i in (1, 2, 3)])))
    a, b = by["D1"]["efficacy"]["pooled"][0], by["D2"]["efficacy"]["pooled"][0]
    assert a["rank"] == b["rank"] == 1
    assert a["tied_with"] == [2] and b["tied_with"] == [1]
    assert by["D1"]["efficacy"]["lines"][2] == (
        "Size of effect: cannot be separated from 1 of the 2 other drugs tested against placebo "
        "on percent change in body weight.")


def _h2h_land():
    """Alpha leads on body weight against placebo, Beta is second and holds a trial against
    Alpha, Gamma ran 56 weeks, Delta was tested only against a control no trial shares,
    Epsilon ran 12 weeks, too short to compare with the others."""
    rows = [_z(1, "A1", 20.0, weeks=52.0), _z(1, "A2", 20.4, weeks=72.0),
            _z(2, "B1", 15.0, weeks=60.0),
            _row(2, "B2", 4.0, ci=(4.0 - Z95, 4.0 + Z95), ref_arm="Alpha 10 mg",
                 kind="comparator", h2h=1, weeks=60.0),
            _z(3, "C1", 5.0, weeks=56.0),
            _z(4, "D1", 3.0, ref_arm="Chemotherapy", kind="control"),
            _z(5, "E1", 4.0, weeks=12.0)]
    cands = [_cand(1, "Alpha"), _cand(2, "Beta"), _cand(3, "Gamma"), _cand(4, "Delta"),
             _cand(5, "Epsilon")]
    return _land([_group("w", *WEIGHT, rows)], cands)


def test_21_a_head_to_head_trial_outranks_the_indirect_gap(monkeypatch):
    monkeypatch.setattr(S, "TAU_DF_MIN", 1)
    by = _by(S.scorecard(_h2h_land()))
    beta = by["Beta"]["efficacy"]
    assert beta["lines"][2] == (
        "Size of effect: 2nd of 3 drugs tested against placebo on percent change in body "
        "weight, in trials of 52 to 72 weeks, among those whose trials ran about as long; head "
        "to head in one trial, 4.0 percentage points behind Alpha (95% interval 2.0 to 6.0).")
    versus = next(e for e in beta["pooled"] if e["lead"])["versus"]
    assert versus["direct"]["nct_ids"] == ["B2"]
    assert versus["direct"]["diff"] == pytest.approx(-4.0)
    alpha = by["Alpha"]["efficacy"]
    assert alpha["lines"][2].endswith(
        "head to head in one trial, 4.0 percentage points ahead of Beta (95% interval 2.0 to 6.0).")
    # Epsilon's 12 weeks are compared with no one, and no one is compared with them.
    eps = by["Epsilon"]["efficacy"]
    assert eps["size_basis"] == "not comparable" and eps["parts"]["size"] == 50.0
    assert eps["lines"][2] == (
        "Size against peers not known: its trials, 12 weeks, ran for a different length from "
        "those of the other drugs tested against placebo on percent change in body weight, so "
        "its size counts at 50, what the average drug scores against its peers.")
    for name in ("Alpha", "Beta", "Gamma"):
        lead = next(e for e in by[name]["efficacy"]["pooled"] if e["lead"])
        assert lead["of"] == 3 and lead["peers_all"] == 3


def test_22_an_unknown_size_counts_at_the_average_where_others_are_ranked(monkeypatch):
    monkeypatch.setattr(S, "TAU_DF_MIN", 1)
    by = _by(S.scorecard(_h2h_land()))
    # Size is a mean chance of beating peers: over one cell's drugs it averages 50.
    ranked = [e for a in by.values() for e in a["efficacy"]["pooled"] if e["counted"]]
    assert sum(e["score"] for e in ranked) / len(ranked) == pytest.approx(50.0)
    delta = by["Delta"]
    ef = delta["efficacy"]
    assert ef["parts"]["size"] == 50.0 and ef["size_basis"] == "not comparable"
    assert ef["score"] == pytest.approx(
        (ef["parts"]["strength"] + ef["parts"]["wins"] + 50.0) / 3)
    assert ef["lines"][2] == ("Size against peers not known: its control arm names no regimen "
                              "another trial shares, so its size counts at 50, what the average "
                              "drug scores against its peers.")
    assert delta["rank_line"].endswith(
        "with its size of effect not comparable with peers and counted at 50, the average.")


# --- safety -----------------------------------------------------------------------------------
DARA = [(186, 346, 117, 354), (289, 364, 262, 365), (205, 283, 148, 281), (142, 197, 131, 195),
        (29, 96, 22, 98), (56, 193, 38, 196)]


def test_23_safety_is_averaged_trial_by_trial_against_each_trials_control():
    strata = [_stratum(f"T{i}", [_arm_counts("Daratumumab + Rd", serious=(x1, n1))],
                       _counts(serious=(x0, n0)), kind="control", title="Rd")
              for i, (x1, n1, x0, n0) in enumerate(DARA)]
    rows = [_z(1, "T0", 3.0, ref_arm="Rd", kind="control")]
    sc = S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1, "Daratumumab")],
                           [_safe(1, strata)]))
    f = _by(sc)["Daratumumab"]["safety"]["serious"]
    assert f["rd"] == pytest.approx(0.1293, abs=1e-4)
    assert f["se_own"] == pytest.approx(0.016715, abs=1e-6)
    assert f["dispersion"] == pytest.approx(14.501981 / 5, abs=1e-5)
    assert f["se"] == pytest.approx(f["se_own"] * math.sqrt(f["dispersion"]))
    assert f["drug_rate"] - f["control_rate"] == pytest.approx(f["rd"], abs=1e-12)
    assert f["kind"] == "active"

    # Placebo and active strata: the kind with more people is scored, the other reported.
    mixed = [_plain("P1", 31, serious=(11, 0)),
             _plain("A1", 300, serious=(30, 30), kind="control"),
             _plain("A2", 291, serious=(29, 30), kind="control")]
    sc = S.scorecard(_land([_group("w", *WEIGHT, [_z(1, "A1", 3.0)])], [_cand(1)],
                           [_safe(1, mixed)]))
    s = _by(sc)["D1"]["safety"]
    assert s["serious"]["kind"] == "active" and s["serious"]["k"] == 2
    assert s["other_control"]["serious"]["kind"] == "placebo"
    note = next(n for n in s["notes"]
                if n.startswith("Serious adverse events:") and "not scored" in n)
    assert note.startswith("Serious adverse events: 35.5 points more than placebo in 1 trial")
    # The reported kind is widened like the scored one where its kind has a spread to
    # measure; one placebo trial has none.
    assert s["other_control"]["serious"]["dispersion"] is None

    # A switch or extension arm is never the drug's; a stated period takes its own arms.
    upa = _stratum("NCT02706847", [
        _arm_counts("Upadacitinib 15 mg: Weeks 1-12", serious=(9, 164), deaths=(0, 164)),
        _arm_counts("Upadacitinib 30 mg: Weeks 1-12", serious=(12, 165), deaths=(1, 165)),
        _arm_counts("Upadacitinib 15 mg: Weeks 1-260", serious=(87, 236), deaths=(9, 236)),
        _arm_counts("Upadacitinib 30 mg: Weeks 1-260/Switch", serious=(71, 240), deaths=(5, 240)),
        _arm_counts("Upadacitinib 15 mg After Switch", serious=(21, 138), deaths=(2, 138))],
        _counts(serious=(0, 169), deaths=(0, 169)), title="Placebo: Weeks 1-12")
    got = S.stratum_counts(upa)
    assert got["serious"] == (21, 329, 0, 169) and got["deaths"] == (1, 329, 0, 169)
    assert got["withdrawn"] is None
    for title in ("Placebo to Upadacitinib", "Open-label extension"):
        st = _stratum("X", [_arm_counts(title, serious=(5, 50))], _counts(serious=(1, 50)))
        assert S.stratum_counts(st) is None
    named = _stratum("X", [_arm_counts("Drug", serious=(5, 50))], _counts(serious=(1, 50)),
                     title="Drug + placebo", is_drug=True)
    assert S.stratum_counts(named) is None

    # No controlled trial: no safety score.
    open_only = _stratum("O1", [_arm_counts("Drug", serious=(5, 50))], None)
    sc = S.scorecard(_land([_group("w", *WEIGHT, [_z(1, "O1", 3.0)])], [_cand(1)],
                           [_safe(1, [open_only])]))
    d = _by(sc)["D1"]
    assert d["safety"]["score"] is None and d["placed"] is False
    assert d["why_not"] == "no controlled trial with safety counts"


def test_24_the_two_parts_count_equally_and_a_thin_part_is_left_out():
    # Withdrawals posted for 270 people against 16,073 for serious events: under a
    # quarter, so left out of the score and named, never quietly outweighed.
    strata = [_stratum("W", [_arm_counts("Drug", withdrawn=(54, 270))],
                       _counts(withdrawn=(19, 250))),
              _stratum("S", [_arm_counts("Drug", serious=(2893, 16073))],
                       _counts(serious=(2000, 10000)))]
    sc = S.scorecard(_land([_group("w", *WEIGHT, [_z(1, "W", 3.0)])], [_cand(1)],
                           [_safe(1, strata)]))
    s = _by(sc)["D1"]["safety"]
    assert s["parts"] == {"serious": pytest.approx(85.0, abs=0.01)}
    assert s["part_weights"] == {"serious": 1.0}
    assert s["score"] == pytest.approx(85.0, abs=0.01)
    assert ("Stopped for side effects left out of the score: posted for 270 people, under a "
            "quarter of the 16,073 behind serious adverse events.") in s["notes"]
    assert s["withdrawn"]["n_drug"] == 270          # still reported
    # Both parts behind enough people: they count equally.
    strata[0] = _stratum("W", [_arm_counts("Drug", withdrawn=(1080, 5400))],
                         _counts(withdrawn=(380, 5000)))
    sc = S.scorecard(_land([_group("w", *WEIGHT, [_z(1, "W", 3.0)])], [_cand(1)],
                           [_safe(1, strata)]))
    s = _by(sc)["D1"]["safety"]
    assert s["part_weights"] == {"staying_on": 0.5, "serious": 0.5}
    assert s["score"] == pytest.approx((s["parts"]["staying_on"] + s["parts"]["serious"]) / 2)
    assert "Stopped for side effects and serious adverse events count equally." in s["notes"]


# --- the whole ----------------------------------------------------------------------------------
def test_efficacy_safety_and_evidence_come_together():
    sc = S.scorecard(_general())
    by = _by(sc)
    alpha = by["Alpha"]
    assert alpha["efficacy"]["parts"]["strength"] == 100.0
    assert alpha["efficacy"]["parts"]["wins"] == 100.0
    assert alpha["efficacy"]["size_basis"] == "ranked"
    assert alpha["efficacy"]["pooled"][0]["rank"] == 1
    # Gamma has only a p-value on a posted difference: tested, never averaged for size.
    gamma = by["Gamma"]["efficacy"]
    assert gamma["routes"] == {"p-value": 1} and gamma["parts"]["wins"] == 0
    assert gamma["size_basis"] == "not comparable" and gamma["parts"]["size"] == 50.0
    # The boxed warning is ten points off the people-weighted parts.
    s = alpha["safety"]
    raw = sum(s["parts"][k] * s["part_weights"][k] for k in s["parts"]) / sum(s["part_weights"].values())
    assert s["score"] == pytest.approx(raw - 10)
    assert any("FDA boxed warning, 10 points off" in n for n in s["notes"])
    assert alpha["evidence"]["score"] == pytest.approx(25 * math.log10(3500) - 25 + 20)
    assert alpha["overall"] == pytest.approx(
        (alpha["efficacy"]["score"] + s["score"] + alpha["evidence"]["score"]) / 3)
    assert by["Gamma"]["evidence"]["confidence"] == "low"                  # 60 people
    assert any("Read with care: 60 people" in n for n in by["Gamma"]["safety"]["notes"])


def test_a_drug_with_no_posted_result_is_listed_and_never_scored():
    sc = S.scorecard(_general())
    delta = _by(sc)["Delta"]
    assert delta["placed"] is False and delta["overall"] is None
    assert delta["efficacy"]["score"] is None and delta["safety"]["score"] is None
    assert delta["why_not"] == "no posted results"
    assert delta["rank_range"] is None
    assert (sc["placed"], sc["total"]) == (4, 5)


def test_25_every_rank_sits_inside_its_range_and_the_redraw_repeats():
    land = _general()
    sc = S.scorecard(land)
    placed = [a for a in sc["assets"] if a["placed"]]
    assert [a["rank"] for a in placed] == list(range(1, len(placed) + 1))
    for a in placed:
        lo, hi = a["rank_range"]
        assert lo <= a["rank"] <= hi
    again = S.scorecard(land)
    assert [a["rank_range"] for a in again["assets"]] == [a["rank_range"] for a in sc["assets"]]
    small = S.scorecard(land, draws=200)
    assert small["simulation"] == {"draws": 200, "seed": S.SEED, "level": 95.0}
    for a in sc["assets"]:
        assert "interval" not in a["efficacy"] and "interval" not in a["safety"]
    json.dumps(sc, allow_nan=False)


@pytest.mark.parametrize("build", [_general, _h2h_land])
def test_26_the_words_are_few_and_in_house_style(build, monkeypatch):
    monkeypatch.setattr(S, "TAU_DF_MIN", 1)
    sc = S.scorecard(build())
    for a in sc["assets"]:
        if not a["placed"]:
            continue
        assert len(a["efficacy"]["lines"]) <= 3 and len(a["safety"]["lines"]) <= 1
        for text in (a["efficacy"]["lines"] + a["efficacy"]["notes"] + a["safety"]["lines"]
                     + a["safety"]["notes"] + [a["rank_line"]]):
            assert text.endswith("."), text
            assert not any(b in text.lower() for b in BANNED), text
    for text in sc["method"].values():
        assert not any(b in text.lower() for b in BANNED)


def test_27_an_old_row_is_read_by_its_p_value_and_its_interval_is_not():
    legacy = {"asset_id": 1, "nct_id": "N1", "delta": -20.0, "p_value": "0.001",
              "ci": [-30.0, -10.0], "estimate": -20.0, "phase": "Phase 3",
              "arm_is_drug": True, "arm": "D1", "reference_kind": "placebo"}
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, [legacy])], [_cand(1)])))["D1"]["efficacy"]
    assert ef["routes"] == {"p-value": 1}
    assert ef["z"] == pytest.approx(3.2905, abs=1e-3)


def test_the_map_draws_every_scored_drug_and_labels_the_open_company():
    import components.charts as CH
    sc = S.scorecard(_general())
    points = [{"name": a["name"], "ticker": a["ticker"], "x": a["efficacy"]["score"],
               "y": a["safety"]["score"], "evidence": a["evidence"]["score"],
               "stage": a["stage"], "boxed": a["boxed"], "rank": a["rank"], "tip": a["name"]}
              for a in sc["assets"] if a["placed"]]
    for p, t in zip(points, ("AAA", "BBB", "BBB", "BBB")):
        p["ticker"] = t
    points[0]["name"] = "Alpha"
    points[1]["tip"] = "Beta (BBB), Marketed. Overall 70, rank 2 (could sit 2 to 3): efficacy 80."
    svg = CH.score_map(points, highlight="AAA")
    assert svg.count("<title>") == 4
    assert "rank 2 (could sit 2 to 3): efficacy 80.</title>" in svg
    assert ">Alpha</text>" in svg and 'font-weight="700"' in svg
    assert "stroke-dasharray=\"2 2\"" in svg                 # the boxed warning ring
    # A score has no interval (specification 2.11, 5.5): the only lines are the grid's.
    assert svg.count("<line") == 10
    assert CH.score_map([]) == ""


# --- the book guard (specification 7.3) ---------------------------------------------------------
GUARD = {367: "obesity", 20: "lung", 371: "breast", 1: "type 2 diabetes", 383: "arthritis",
         101: "myeloma"}


@pytest.mark.parametrize("indication", sorted(GUARD))
def test_the_book_guard(book, indication, capsys):
    import db
    import landscape as L
    land = L.landscape(str(db.DB_PATH), indication, verdict_for=lambda t: {"modelled": []})
    assert land is not None
    started = time.time()
    built = S._build(land)
    took = time.time() - started
    sc = built["out"]
    json.dumps(sc, allow_nan=False)
    assert took < 2.0
    placed = [a for a in sc["assets"] if a["placed"]]
    names = {a["asset_id"]: a["name"] for a in sc["assets"]}
    for a in placed:
        lo, hi = a["rank_range"]
        assert lo <= a["rank"] <= hi, a["name"]
        for part in ("withdrawn", "serious", "deaths"):
            f = a["safety"][part]
            if f:
                assert abs(f["drug_rate"] - f["control_rate"] - f["rd"]) <= 1e-12
        assert len(a["efficacy"]["lines"]) + len(a["safety"]["lines"]) <= 4
        for text in a["efficacy"]["lines"] + a["safety"]["lines"]:
            assert text.endswith(".") and not any(b in text.lower() for b in BANNED), text
    for cell, by in built["pooled"].items():
        for aid, e in by.items():
            assert e["se"] > 0
            ys = built["trial_level"][(cell, aid)]["y"]
            if e["k"] >= 2 and e["q"]:
                i2 = max(0.0, (e["q"] - (e["k"] - 1)) / e["q"])
                assert not (i2 > 0.95 and min(ys) < 0 < max(ys)), (names[aid], cell)
    for r in built["results"]:
        assert "ratio of medians" not in r["route"]
        if r.get("z") is not None and "arm spread" in r["route"]:
            assert abs(r["z"]) <= 40, (names[r["asset_id"]], r["nct_id"])
    order = [a["name"] for a in placed]
    if indication == 367:
        assert len(placed) >= 8
        assert set(order[:2]) == {"Semaglutide", "Tirzepatide"}
        cell = built["pooled"][("percent change in body weight", "placebo alone")]
        tirz = next(e for aid, e in cell.items() if names[aid] == "Tirzepatide")
        assert 14 <= tirz["effect"] <= 22 and tirz["k"] >= 5
    if indication == 1:
        cell = built["pooled"][("change in HbA1c", "placebo alone")]
        first = max(cell, key=lambda aid: cell[aid]["shrunk"])
        assert names[first] == "Tirzepatide"
        assert cell[first]["effect"] == pytest.approx(1.73, abs=0.01) and cell[first]["k"] == 5
    if indication == 20:
        assert {"Osimertinib", "Pembrolizumab"} <= set(order[:3])
        pembro = next(aid for aid, n in names.items() if n == "Pembrolizumab")
        assert {s["why"] for s in built["skipped"]
                if s["asset_id"] == pembro and s["nct_id"] == "NCT03976362"} == {"in both arms"}
    if indication == 101:
        with capsys.disabled():
            print("\nmyeloma:", [(a["rank"], a["name"], round(a["safety"]["score"]))
                                 for a in placed])


# --- review round: fixes, each with the case that found it ---------------------------------
@pytest.mark.parametrize("title, unit, sign", [
    ("Sum of Pain Intensity Difference (SPID)", "units on a scale", 1),
    ("Sum of Pain Relief and Pain Intensity Difference (SPRID)", "units on a scale", 1),
    ("Weighted Mean FEV1 Over 0-24 Hours", "Liters", 1),
    ("Change in KCCQ Total Symptom Score", "units on a scale", 1),
    ("Time From Randomization to the Occurrence of a Bipolar Event", "days", 1),
    ("Duration of Flare-Free Maintenance", "days", 1),
    ("Time to First Perceptible Pain Relief", "minutes", -1),
    ("Percentage of Participants With Local Reactions", "percentage of participants", -1),
    ("Number of Participants With TIMI Major Bleeding", "participants", -1),
    ("Number of Participants With Clinically Significant Hypoglycemia", "participants", -1),
    ("Number of Subjects With CIN2+ Associated With HPV-16/18", "participants", -1),
    ("Number of Participants With Elevated Temperature", "participants", -1),
    ("Percentage of Participants Achieving HbA1c <7%", "percentage of participants", 1),
    ("Percentage of Participants With Seroconversion", "percentage of participants", 1),
    ("Number of Participants With Visit", "participants", None),
])
def test_28_the_measure_fixes_its_direction_before_any_word_list(title, unit, sign):
    assert S.benefit_direction(title, unit) == sign


def test_29_a_time_to_an_event_is_read_from_a_hazard_ratio_alone():
    g = {"title": "Time to First Asthma Exacerbation", "unit": "days"}
    assert S.is_survival(g)
    # Arm means of censored times give no result, however far apart.
    row = _row(1, "N1", 105.0, value=155.0, ref=50.0, param="MEAN",
               disp="Standard Error", spread=14.7, ref_spread=3.8)
    sc = S.scorecard(_land([_group("t", g["title"], g["unit"], [row], "MEAN")], [_cand(1)]))
    assert _by(sc)["D1"]["efficacy"]["unscored_why"] == {"no hazard ratio": 1}
    # A hazard ratio of 1.5 on a time to relief (a good event) favours the drug.
    good = _row(1, "N1", -5.0, value=20.0, ref=25.0, ci=(1.2, 1.875), est=1.5,
                etype="Hazard Ratio")
    eff = S.row_effect(good, {"title": "Time to Pain Relief", "unit": "days"}, -1)
    assert eff["effect"] == pytest.approx(math.log(1.5))


def test_30_an_analysis_set_is_not_a_subgroup():
    for title in ("Least Squares (LS) Mean Percent Change in Body Weight - Evaluable Population",
                  "Percent Change in Body Weight (ITT Population)"):
        assert S.family_of({"title": title, "unit": "percent change"}) == (
            "percent change in body weight")
    assert S.family_of({"title": "Percent change in body weight in the PD-L1 positive "
                                 "population", "unit": "percent change"}) is None
    assert S.clean_measure("LS Mean Percent Change in Body Weight - Evaluable Population") == (
        "LS mean percent change in body weight")
    assert S.clean_measure("Progression-free Survival (PFS) Rate at Week 13") == (
        "progression-free survival (PFS) rate")


def test_31_a_non_inferiority_result_is_left_out_unless_it_shows_the_drug_better():
    ni = ("Change in HbA1c [Noninferiority Analysis]", "percent")
    rows = [_z(1, "A", 0.3, measure=ni), _z(1, "B", 3.0, measure=ni), _z(1, "C", 2.5)]
    ef = _by(S.scorecard(_land([_group("n", *ni, rows[:2]), _group("w", *WEIGHT, rows[2:])],
                               [_cand(1)])))["D1"]["efficacy"]
    assert ef["non_inferiority"] == 1 and ef["endpoints"] == 2 and ef["wins"] == 2
    assert any(n.startswith("1 result from trials built to show the drug is no worse")
               for n in ef["notes"])
    only = _by(S.scorecard(_land([_group("n", *ni, rows[:1])], [_cand(1)])))["D1"]
    assert only["efficacy"]["score"] is None
    assert only["why_not"] == "only results from trials built to show it no worse than a comparator"


def test_32_a_worse_result_prints_its_interval_the_right_way_round():
    rows = [_row(1, "A", 0.2, ci=(0.1, 0.3), ref_arm="Insulin Lispro", kind="comparator")]
    ef = _by(S.scorecard(_land([_group("h", *HBA1C, rows)], [_cand(1)])))["D1"]["efficacy"]
    # Under 1, two places, so a small difference never prints as 0.0.
    assert ef["lines"][1].startswith("0.20 percentage points worse than Insulin Lispro")
    assert ef["lines"][1].endswith("(95% interval 0.10 to 0.30).")


def test_33_an_unreadable_safety_stratum_is_left_out_and_the_redraw_still_lines_up():
    land = _general()
    bad = _plain("N1c", 400, (20, 20), (10, 10))
    bad["arm_rows"][0]["withdrawn"] = [450, 400]      # more withdrew than were at risk
    for s in land["safety"]:
        if s["asset_id"] == 1:
            s["strata"].append(bad)
    alpha = _by(S.scorecard(land))["Alpha"]["safety"]
    assert alpha["withdrawn"]["trials"] == ["N1a", "N1b"] and alpha["withdrawn"]["k"] == 2
    assert alpha["serious"]["trials"] == ["N1a", "N1b", "N1c"]


def test_34_one_dispersion_per_part_and_kind_across_every_drug_with_two_strata():
    # D1 is scored against placebo; D2 against active comparators, but its two placebo
    # trials disagree and widen D1's placebo figure all the same.
    d1 = [_plain("P1", 400, serious=(20, 20)), _plain("P2", 400, serious=(22, 20))]
    d2 = ([_plain(f"A{i}", 900, serious=(40, 40), kind="control") for i in (1, 2)]
          + [_plain("Q1", 200, serious=(40, 10)), _plain("Q2", 200, serious=(10, 10))])
    rows = [_z(1, "P1", 3.0), _z(2, "A1", 3.0, ref_arm="Metformin", kind="comparator")]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1), _cand(2)],
                               [_safe(1, d1), _safe(2, d2)])))
    fits = [M.mantel_haenszel_rd([s["serious"] for s in map(S.stratum_counts, d1)]),
            M.mantel_haenszel_rd([s["serious"] for s in map(S.stratum_counts, d2[2:])])]
    phi = M.dispersion(fits)
    assert phi > 1.0
    assert by["D1"]["safety"]["serious"]["dispersion"] == pytest.approx(phi)
    other = by["D2"]["safety"]["other_control"]["serious"]
    assert other["kind"] == "placebo" and other["dispersion"] == pytest.approx(phi)
    assert other["se"] == pytest.approx(other["se_own"] * math.sqrt(phi))


def test_35_a_placebo_arm_named_for_its_period_or_age_is_placebo_alone():
    for title in ("Placebo 13 to 15 Years Old", "Double-blind Placebo", "Placebo Twice a Day",
                  "RSV Season 1: Placebo", "Panel C: Matched Placebo", "Placebo in DBTP",
                  "Placebo Followed by Tanezumab 5 mg", "Placebo - AIN457A 75mg"):
        assert S.control_key(title, "placebo") == "placebo alone", title
    assert S.control_key("Placebo/Glimepiride", "placebo", "Ertugliflozin 15 mg") == "placebo alone"
    assert S.control_key("Placebo/Docetaxel", "placebo", "Ramucirumab/Docetaxel") == "docetaxel"
    assert S.control_label("x", ["Pemetrexed and Platinum Chemotherapy Followed by and "
                                 "Pemetrexed"]) == "Pemetrexed and Platinum Chemotherapy and Pemetrexed"
    assert S.control_label("x", ["Ustekinumab 2 x or"]) == "Ustekinumab 2"


def test_36_a_drug_tested_instead_of_a_regimen_is_never_averaged_with_one_added_to_it():
    assert S.comparison_key("Docetaxel", "comparator", "Pembrolizumab 2 mg/kg") == (
        "docetaxel head to head")
    assert S.comparison_key("Placebo + Docetaxel", "placebo", "Ramucirumab + Docetaxel") == (
        "docetaxel")
    assert S.comparison_key("Metformin", "comparator", "Sita/Met FDC") == "metformin"


def test_37_a_share_posted_as_a_fraction_is_put_in_percentage_points():
    row = _row(1, "N1", -0.09, value=0.47, ref=0.56, param="NUMBER", ci=(-0.26, 0.07))
    g = {"title": "Local Regional Control Rate at 2 Years", "unit": "Proportion of Participants"}
    eff = S.row_effect(row, g, 1)
    assert eff["scale"] == "share" and eff["effect"] == pytest.approx(-9.0)
    assert eff["se"] == pytest.approx(100 * 0.33 / (2 * Z95))


def test_38_rates_and_intervals_stay_inside_what_is_possible():
    fit = M.mantel_haenszel_rd([(0, 50, 2, 45), (0, 30, 1, 30)])
    assert fit["drug_rate"] == 0.0 and fit["control_rate"] > 0
    strata = [_stratum("T1", [_arm_counts("Drug", serious=(0, 50))],
                       _counts(serious=(2, 45)))]
    s = _by(S.scorecard(_land([_group("w", *WEIGHT, [_z(1, "T1", 3.0)])], [_cand(1)],
                              [_safe(1, strata)])))["D1"]["safety"]
    line = s["lines"][0]
    assert "(0.0% against 4.4%)" in line and "-0.0" not in line
    assert line.startswith("Serious adverse events: 4.4 points fewer than placebo")
    # The interval's lower end cannot run below the control rate taken away.
    assert "95% interval 4.4 fewer to" in line


def test_39_an_outcomes_trials_serious_events_are_set_aside():
    cvot = _group("cv", "Time to First Occurrence of MACE (Cardiovascular Death, Non-fatal "
                        "Myocardial Infarction or Non-fatal Stroke)", "months",
                  [_row(1, "CV1", 1.0, ci=(0.2, 1.8), est=0.8, etype="Hazard Ratio")])
    strata = [_plain("CV1", 4000, serious=(800, 900)), _plain("W1", 500, serious=(30, 20))]
    s = _by(S.scorecard(_land([cvot, _group("w", *WEIGHT, [_z(1, "W1", 3.0)])], [_cand(1)],
                              [_safe(1, strata)])))["D1"]["safety"]
    assert s["serious"]["trials"] == ["W1"] and s["set_aside"] == ["CV1"]
    assert any(n.startswith("Serious adverse events leave out 1 outcomes trial (CV1)")
               for n in s["notes"])
    assert set(s["withdrawn"]["trials"]) == {"CV1", "W1"}       # withdrawals still count


def test_40_a_safety_score_on_a_small_share_of_the_people_treated_is_flagged():
    strata = [_plain("T1", 300)]
    safe = _safe(1, strata)
    safe["participants"] = 11128
    s = _by(S.scorecard(_land([_group("w", *WEIGHT, [_z(1, "T1", 3.0)])], [_cand(1)],
                              [safe])))["D1"]["safety"]
    assert s["read_with_care"] == ("Read with care: the safety score rests on 300 of the "
                                   "11,128 people treated in its trials (3%).")


def test_41_strength_and_wins_from_few_trials_move_toward_the_drugs_mean():
    rows = [_z(1, "A1", 5.0)]
    for aid in (2, 3, 4, 5):
        rows += [_z(aid, f"T{aid}{j}", z) for j, z in enumerate((1.0, 2.5, 0.5, 2.0))]
    by = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)],
                               [_cand(i) for i in range(1, 6)])))
    one = by["D1"]["efficacy"]
    assert one["z"] == pytest.approx(5.0) and one["z_weight"] > 0.3
    assert one["z_counted"] < 5.0 and one["wins_counted"] < 100.0
    assert one["parts"]["wins"] < 100.0 and one["score"] < 100.0
    # Strength still clears 3.29 after the move, so only the wins note is printed.
    assert not any(n.startswith("Strength counted at z") for n in one["notes"])
    assert any(n.startswith("Wins counted at") and "since its one trial says less on its own"
               in n for n in one["notes"])
    many = by["D2"]["efficacy"]
    assert many["z_weight"] < one["z_weight"]


def test_42_an_unranked_drug_is_quoted_on_its_largest_result():
    rows = [_z(1, "A1", 1.0, n=40, ref_arm="Docetaxel", kind="comparator"),
            _z(1, "B1", 4.0, n=900, ref_arm="Chemotherapy", kind="control")]
    ef = _by(S.scorecard(_land([_group("w", *WEIGHT, rows)], [_cand(1)])))["D1"]["efficacy"]
    assert "than Chemotherapy" in ef["lines"][1] or "than its control arm" in ef["lines"][1]


def test_43_a_result_with_no_control_arm_is_counted_not_dropped():
    row = _row(1, "S1", None, value=-5.0, ref=None, kind=None, ref_arm=None)
    row["reference_kind"] = None
    d = _by(S.scorecard(_land([_group("w", *WEIGHT, [row])], [_cand(1)])))["D1"]
    assert d["efficacy"]["unscored_why"] == {"no control": 1}
    assert d["why_not"] == "results posted, none against a control arm the book can identify"


def test_44_a_boxed_warning_reads_as_a_clause():
    assert S._boxed_text("HEPATOTOXICITY Hepatotoxicity may be severe, and in some cases, "
                         "fatal", ["Tukysa"]) == "Hepatotoxicity may be severe, and in some cases, fatal"
    assert S._boxed_text("Severe hypoglycemia symlin", ["Symlin"]) == "Severe hypoglycemia"


def test_the_regimen_is_read_from_the_drugs_own_arms_and_never_guessed():
    """How a drug was given, for the table beside the chart: doses its arm titles name, the
    schedule, the form and the trial length; a column the arms do not state is null."""
    rows = [
        {"arm": "Tirzepatide 5 mg", "arm_description": "Tirzepatide administered SC once weekly",
         "arm_names_drug": True, "weeks": 72.0, "outcome_type": "PRIMARY"},
        {"arm": "Tirzepatide 15 mg", "arm_description": "Tirzepatide 15 mg once weekly; placebo "
         "orally daily", "arm_names_drug": True, "weeks": 72.0, "outcome_type": "PRIMARY"},
        {"arm": "Placebo", "arm_description": "Placebo 2 mg daily", "arm_names_drug": False,
         "arm_is_drug": False, "weeks": 72.0, "outcome_type": "PRIMARY"},
    ]
    cand = {"name": "Tirzepatide", "generic": "Tirzepatide", "route": ["SUBCUTANEOUS"]}
    reg = S.regimen(rows, cand, weeks=None, participants=2539)
    assert reg["dose"] == "5\u201315 mg"                  # never the placebo arm's 2 mg
    assert reg["frequency"] == "weekly"                   # never the placebo's "daily"
    assert reg["form"] == "SC"
    assert reg["duration"] == "72 wk"
    assert reg["participants"] == 2539
    bare = S.regimen([{"arm": "Drug X", "arm_names_drug": True}], {"name": "Drug X"})
    assert (bare["dose"], bare["frequency"], bare["form"], bare["duration"]) == (None,) * 4
    assert all(bare["why"][k] for k in ("dose", "frequency", "form", "duration"))
