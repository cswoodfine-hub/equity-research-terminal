"""The landscape read for you: one measure, each drug's best result, its cost, a verdict."""

import pytest

import landscape_overview as O


def _row(aid, name, arm, value, placebo, weeks=72, n=300, drug=True, kind="placebo"):
    return {"asset_id": aid, "name": name, "ticker": "T", "arm": arm, "value": value,
            "placebo": placebo, "delta": value - placebo, "arm_is_drug": drug,
            "weeks": weeks, "n": n, "phase": "Phase 3", "nct_id": f"NCT{aid}",
            "reference_kind": kind, "reference_arm": "Placebo"}


def test_the_direction_of_benefit_is_the_way_most_drugs_moved_it():
    weight = [_row(1, "A", "a", -20, -2), _row(2, "B", "b", -15, -3)]
    survival = [_row(1, "A", "a", 24, 12), _row(2, "B", "b", 20, 15)]
    assert O.direction(weight) == -1
    assert O.direction(survival) == 1
    assert O.direction([]) is None


def test_each_drug_keeps_its_best_arm_and_the_best_drug_leads():
    group = {"rows": [_row(1, "Zepbound", "5 mg", -15, -2),
                      _row(1, "Zepbound", "15 mg", -22, -2),
                      _row(2, "Wegovy", "2.4 mg", -15, -2, n=30)]}
    ranked = O.best_arms(group, -1)
    assert [r["name"] for r in ranked] == ["Zepbound", "Wegovy"]
    assert ranked[0]["arm"] == "15 mg" and ranked[0]["benefit"] == pytest.approx(20)
    assert ranked[1]["flags"] == ["small arm (n=30)"]


def test_a_boxed_warning_is_read_as_its_heading_without_the_brand():
    text = ("WARNING: RISK OF THYROID C-CELL TUMORS In both male and female rats, "
            "tirzepatide causes thyroid C-cell tumors.")
    assert O._boxed_headline(text) == "Risk of thyroid C-cell tumors"
    assert O._boxed_headline("WARNING: SEVERE HYPOGLYCEMIA SYMLIN is used with insulin",
                             ["Symlin"]) == "Severe hypoglycemia"


def _land():
    rows = [_row(1, "Zepbound", "15 mg", -22.9, -2.4), _row(2, "Wegovy", "2.4 mg", -16.9, -2.4)]
    return {
        "indication": {"name": "Obesity"},
        "candidates": [
            {"asset_id": 1, "name": "Zepbound", "ticker": "LLY", "stage": "Marketed",
             "is_marketed": True, "mechanisms": [{"value": "GLP-1 agonist"}],
             "boxed_warning": "WARNING: RISK OF THYROID C-CELL TUMORS text", "model": None},
            {"asset_id": 2, "name": "Wegovy", "ticker": "NVO", "stage": "Marketed",
             "is_marketed": True, "mechanisms": [], "boxed_warning": None, "model": None},
            {"asset_id": 3, "name": "Retatrutide", "ticker": "LLY", "stage": "Phase 3",
             "is_marketed": False, "mechanisms": [], "boxed_warning": None,
             "model": {"per_share": 33.78, "pos": 0.88}}],
        "endpoints": [{"key": "k", "title": "Percent Change From Baseline in Body Weight at "
                                            "Week 72", "unit": "percent change",
                       "rows": rows}],
        "safety": [{"asset_id": 1, "name": "Zepbound", "participants": 630,
                    "withdrawn_rate": 0.062, "placebo_withdrawn_rate": 0.026},
                   {"asset_id": 2, "name": "Wegovy", "participants": 1300,
                    "withdrawn_rate": 0.070, "placebo_withdrawn_rate": 0.031}],
        "pool": {"claimants": 2, "pool": 107592242, "uncrowded_share": 0.58,
                 "crowded_share": 0.42, "peak_year": 2040}}


def test_the_verdict_leads_with_a_bottom_line_and_says_what_each_part_means():
    o = O.overview(_land())
    kinds = [c["kind"] for c in o["cards"]]
    assert kinds[0] == "bottom_line"
    assert set(kinds) >= {"efficacy", "tolerability", "warnings", "stage", "crowding"}
    assert all(c["meaning"] for c in o["cards"])
    eff = next(c for c in o["cards"] if c["kind"] == "efficacy")
    assert eff["headline"] == "Zepbound: 20.5 percentage points better than placebo"
    assert "lower is better" in eff["meaning"] and "not a head-to-head win" in eff["meaning"]
    assert "Zepbound shows the biggest effect" in o["cards"][0]["headline"]
    stage = next(c for c in o["cards"] if c["kind"] == "stage")
    assert "an 88% chance of approval" in stage["detail"]
    tol = next(c for c in o["cards"] if c["kind"] == "tolerability")
    assert tol["headline"] == "Zepbound easiest · Wegovy hardest"
    assert o["endpoint"]["measure"] == "percent change in body weight"


def test_a_pool_nobody_crowds_says_nothing():
    land = _land()
    land["pool"]["uncrowded_share"] = 0.002
    assert "crowding" not in {c["kind"] for c in O.overview(land)["cards"]}


def test_a_dual_mechanism_is_named_as_one_short_label():
    tirz = {"mechanisms": [{"value": "Gastric inhibitory polypeptide receptor agonist"},
                           {"value": "Glucagon-like peptide 1 receptor agonist"}]}
    assert O.mechanism_label(tirz) == "GIP + GLP-1 agonist"
    assert O.mechanism_label({"mechanisms": [], "classes": ["GLP-1 Receptor Agonist [EPC]"]}) \
        == "GLP-1 Receptor Agonist"
    assert O.mechanism_label({"mechanisms": [{"value": "Programmed cell death protein 1 "
                                                        "inhibitor"}]}) == "PD-1 inhibitor"
