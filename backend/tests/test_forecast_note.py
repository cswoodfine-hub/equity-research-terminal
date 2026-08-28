"""The written half of the forecast. Rules only, so every sentence is checkable.

insights.py earns its model call because it reads a month of unstructured change and has
to choose what matters. Here the facts are already chosen and already numeric, so a model
could only paraphrase them, and paraphrase is where invented numbers come from.
"""

import forecast_note


def _verdict(**over):
    v = {"ok": True, "name": "Casgevy", "per_share": 4.45, "close": 547.29,
         "pct_of_price": 0.00813, "owner_rnpv": 1147.0,
         "peak_revenue": 1512.0, "peak_year": 2031,
         "loe_year": 2035, "loe_basis": "reference product exclusivity (12y)",
         "terminal_share": 0.37, "wacc": 0.0985, "wacc_basis": "CAPM from components",
         "pos": 0.8075, "pos_basis": "composite factors",
         "spread": {"bear": {"per_share": 1.42}, "base": {"per_share": 4.45},
                    "bull": {"per_share": 8.91}},
         "levers": [{"lever": "net price", "span": 1889.0},
                    {"lever": "discount rate", "span": 774.0}],
         "next_catalyst": {"catalyst_type": "data readout",
                           "expected_date": "2027-11-14"},
         "has_range": True, "unsourced": []}
    v.update(over)
    return v


def test_the_headline_puts_the_asset_against_the_share_price():
    line = forecast_note.write(_verdict())["headline"]
    assert "$4.45" in line and "$547.29" in line and "0.8%" in line


def test_it_says_what_it_is_worth_when_there_is_no_price():
    line = forecast_note.write(_verdict(close=None, pct_of_price=None))["headline"]
    assert "$4.45" in line and "547" not in line


def test_it_declines_to_go_per_share_without_a_share_count():
    line = forecast_note.write(_verdict(per_share=None))["headline"]
    assert "no diluted share count" in line.lower()


def test_the_body_carries_the_peak_the_range_and_the_lever():
    body = " ".join(forecast_note.write(_verdict())["body"])
    assert "$1.5bn in 2031" in body
    assert "$1.42 to $8.91" in body and "6.3x" in body
    # Half the span, either way. 944.5 formats to 944: Python rounds halves to even.
    assert "net price" in body and "$944mm" in body


def test_a_terminal_heavy_valuation_says_so():
    body = " ".join(forecast_note.write(_verdict())["body"])
    assert "37% of the NPV is terminal value" in body


def test_a_normal_terminal_share_is_not_flagged():
    body = " ".join(forecast_note.write(_verdict(terminal_share=0.12))["body"])
    assert "terminal value" not in body


def test_unsourced_assumptions_are_named_as_the_analyst_s_risk():
    body = " ".join(forecast_note.write(
        _verdict(unsourced=["net_price_per_patient", "beta"]))["body"])
    assert "no source" in body and "net_price_per_patient" in body


def test_a_blocked_forecast_says_what_is_missing_instead():
    out = forecast_note.write({"ok": False, "name": "Retatrutide",
                               "missing": ["penetration_peak_pct"]})
    assert out["ok"] is False
    assert "Retatrutide" in out["headline"]
    assert "penetration_peak_pct" in " ".join(out["body"])


def test_nothing_at_all_is_still_handled():
    assert forecast_note.write(None)["ok"] is False


def test_it_describes_rather_than_recommends():
    """What a share is worth against what it costs is the model's output. What to do
    about it is not this product's business."""
    text = " ".join([forecast_note.write(_verdict())["headline"]]
                    + forecast_note.write(_verdict())["body"]).lower()
    for word in ("buy", "sell", "overweight", "underweight", "we recommend",
                 "price target", "upside to"):
        assert word not in text


def test_a_scenario_that_only_inherits_is_not_a_range():
    """A scenario inherits base and restates only what it changes. One with no rows of
    its own is base wearing another name, and a range drawn across it would claim work
    nobody did."""
    body = " ".join(forecast_note.write(_verdict(has_range=False))["body"])
    assert "no bear or bull case on file" in body
    assert "$1.42 to $8.91" not in body


def test_a_real_range_is_still_reported():
    body = " ".join(forecast_note.write(_verdict(has_range=True))["body"])
    assert "$1.42 to $8.91" in body
    assert "no bear or bull case" not in body


def test_a_course_priced_drug_implies_courses_not_patients():
    """Journavx treats acute pain and its label says use has not been studied beyond 14
    days. Calling the count it implies "patients" would be a quiet lie."""
    body = " ".join(forecast_note.write(
        _verdict(implied_patients=256344, price_basis="course"))["body"])
    assert "256,344 courses" in body
    assert "patients" not in body


def test_a_yearly_price_still_implies_patients():
    body = " ".join(forecast_note.write(
        _verdict(implied_patients=39201))["body"])
    assert "39,201 patients" in body
