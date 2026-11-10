"""Refusals read into a calendar, with the condition kept verbatim."""

import refusal_calendar as R


def _seed(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding="utf-8")


HDR = "ticker,brand,indication,region,scenario,key,year,value,text_value,unit,source,note\n"


def test_a_seed_with_rows_is_a_model_and_one_without_is_a_refusal(tmp_path):
    _seed(tmp_path, "aaa_model.csv", "# X (AAA). modelled.\n" + HDR + "AAA,X,,US,base,pos,,1.0,,,,\n")
    _seed(tmp_path, "aaa_gone.csv", "# Y (AAA). $5mm, and NOT YET VALUABLE: one year.\n"
          "# What would settle it: the FY2026 figure.\n" + HDR)
    out = R.build(tmp_path)
    assert [r["brand"] for r in out["rows"]] == ["Y"]


def test_the_trigger_is_kept_verbatim_and_dated_to_its_own_year_not_a_later_mention(tmp_path):
    """Neuraceq's condition is the FY2026 10-K; the same sentence goes on to say what is
    computable today from FY2025, and the earlier year must not win."""
    _seed(tmp_path, "lnth_n.csv", "# Neuraceq (LNTH). $51.4mm, and NOT YET VALUABLE: no pair.\n"
          "# What would settle it: the FY2026 10-K, which gives the first full year, being\n"
          "# the $51.4mm of FY2025 plus the first half of 2026.\n" + HDR)
    row = R.build(tmp_path)["rows"][0]
    assert row["settles"].startswith("the FY2026 10-K")
    assert row["window"]["year"] == 2026 and row["window"]["from"] == "2027-02-01"


def test_a_divestiture_has_no_settling_condition_and_is_never_dated(tmp_path):
    _seed(tmp_path, "lnth_t.csv", "# TechneLite (LNTH). $86.8mm, and NOT VALUABLE: sold.\n"
          "# DIVESTED to SHINE on 2026-01-01.\n" + HDR)
    out = R.build(tmp_path)
    assert out["rows"][0]["settles"] is None and out["rows"][0]["window"] is None
    assert out["totals"]["never"] == 1
