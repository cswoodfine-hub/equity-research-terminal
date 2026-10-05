"""The Medicare growth split (docs/design/medicare-demand-split.md).

The identity is tested on live CMS rows saved in ``fixtures/cms_demand_split.json``
(captured 2026-10-05), so a change in what CMS serves shows up here first. No network.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

import cms
import demand_split as ds

_FIX = Path(__file__).resolve().parent / "fixtures" / "cms_demand_split.json"
_DATA = json.loads(_FIX.read_text())


def _row(part: str, name: str) -> dict:
    rows = _DATA["part_d" if part == "D" else "part_b"]
    return next(r for r in rows if r["Brnd_Name"] == name)


def _series(part: str, name: str) -> list[dict]:
    """The fixture row as the split reads it, one record per year."""
    return [{"year": r["year"], "spending": r["total_spending"], "claims": r["total_claims"],
             "beneficiaries": r["total_beneficiaries"], "units": r["total_dosage_units"]}
            for r in cms.parse_row(_row(part, name), part)]


def _year(series, year):
    return next(r for r in series if r["year"] == year)


# --- the fixture holds the anchor values -----------------------------------------------
def test_fixture_is_the_live_payload_with_every_column():
    eliquis = _row("D", "Eliquis")
    assert eliquis["Mftr_Name"] == "Overall"
    for col in ("Tot_Spndng_2024", "Tot_Clms_2024", "Tot_Benes_2024", "Tot_Dsg_Unts_2024",
                "Avg_Spnd_Per_Clm_2024", "Outlier_Flag_2024",
                "Chg_Avg_Spnd_Per_Dsg_Unt_23_24", "CAGR_Avg_Spnd_Per_Dsg_Unt_20_24"):
        assert col in eliquis
    prolia = _row("B", "Prolia*")
    assert prolia["HCPCS_Cd"] == "J0897" and "Avg_DY24_ASP_Price" in prolia
    assert _row("B", "Keytruda")["HCPCS_Cd"] == "J9271"
    assert _row("D", "Tremfya*") and _row("D", "Tremfya Pen")


def test_parse_row_gives_the_eliquis_totals():
    s = _series("D", "Eliquis")
    y23, y24 = _year(s, 2023), _year(s, 2024)
    assert y23["spending"] == 18_273_451_967 and y24["spending"] == 20_774_929_225
    assert y23["beneficiaries"] == 3_927_848 and y24["beneficiaries"] == 4_424_796
    assert y23["claims"] == 21_195_452 and y24["claims"] == 24_061_332


# --- the identity --------------------------------------------------------------------
def test_eliquis_2024_splits_into_the_anchor_factors():
    s = _series("D", "Eliquis")
    st = ds.step(_year(s, 2023), _year(s, 2024))
    assert st["from"] == 2023 and st["to"] == 2024
    assert st["spend"] == pytest.approx(0.136894, abs=5e-6)
    assert st["patients"] == pytest.approx(0.126518, abs=5e-6)
    assert st["intensity"] == pytest.approx(0.0077, abs=5e-5)
    assert st["price"] == pytest.approx(0.0015, abs=5e-5)
    assert st["units_per_claim"] == pytest.approx(0.0129, abs=5e-5)
    assert st["price_per_unit"] == pytest.approx(-0.0112, abs=5e-5)
    product = (1 + st["patients"]) * (1 + st["intensity"]) * (1 + st["price"])
    assert product == pytest.approx(1.136891, abs=5e-6)
    assert product == pytest.approx(1 + st["spend"], abs=1e-9)
    pts = ds.points(st)
    assert pts["patients"] * 100 == pytest.approx(12.71, abs=0.005)
    assert pts["intensity"] * 100 == pytest.approx(0.82, abs=0.005)
    assert pts["price"] * 100 == pytest.approx(0.16, abs=0.005)


@pytest.mark.parametrize("part,name", [("D", "Eliquis"), ("D", "Tremfya*"),
                                       ("B", "Keytruda"), ("B", "Prolia*")])
def test_every_step_multiplies_back_and_its_points_add_up(part, name):
    s = _series(part, name)
    for prev, cur in zip(s, s[1:]):
        st = ds.step(prev, cur)
        product = (1 + st["patients"]) * (1 + st["intensity"]) * (1 + st["price"])
        assert product == pytest.approx(1 + st["spend"], abs=1e-9)
        assert sum(ds.points(st).values()) == pytest.approx(st["spend"], abs=1e-9)
        per_unit = (1 + st["units_per_claim"]) * (1 + st["price_per_unit"])
        assert per_unit == pytest.approx(1 + st["price"], abs=1e-9)


def test_the_span_cagrs_multiply_and_hold_the_anchor():
    s = _series("D", "Eliquis")
    sp = ds.span(s, 2020, 2024)
    assert sp["years"] == 4
    assert sp["spend"] == pytest.approx(0.2025, abs=5e-5)
    assert sp["patients"] == pytest.approx(0.1376, abs=5e-5)
    assert sp["intensity"] == pytest.approx(-0.0082, abs=5e-5)
    assert sp["price"] == pytest.approx(0.0658, abs=5e-5)
    product = (1 + sp["patients"]) * (1 + sp["intensity"]) * (1 + sp["price"])
    assert product == pytest.approx(1 + sp["spend"], abs=1e-9)
    assert sum(sp["points"].values()) == pytest.approx(sp["spend"], abs=1e-9)


def test_span_needs_both_end_years():
    s = _series("D", "Tremfya Pen")                    # a 2024 row only
    assert ds.span(s, 2020, 2024) is None
    assert ds.span(_series("D", "Eliquis"), 2024, 2024) is None


# --- the edges -----------------------------------------------------------------------
def _yr(year, s, c, b, u=None):
    return {"year": year, "spending": s, "claims": c, "beneficiaries": b, "units": u}


def test_a_missing_patient_count_splits_into_claims_and_price():
    st = ds.step(_yr(2023, 1000.0, 100, 50), _yr(2024, 1210.0, 110, None))
    assert st["patients"] is None and st["intensity"] is None
    assert st["claims"] == pytest.approx(0.10) and st["price"] == pytest.approx(0.10)
    assert ds.factors_of(st) == ("claims", "price")
    pts = ds.points(st)
    assert set(pts) == {"claims", "price"}
    assert sum(pts.values()) == pytest.approx(st["spend"], abs=1e-12)


def test_a_flat_year_does_not_divide_by_zero():
    st = ds.step(_yr(2023, 1000.0, 100, 50, 300.0), _yr(2024, 1000.0, 110, 55, 330.0))
    assert st["spend"] == 0.0
    pts = ds.points(st)
    assert pts["patients"] == pytest.approx(math.log(1.1))
    assert sum(pts.values()) == pytest.approx(0.0, abs=1e-12)


def test_nothing_missing_reads_as_zero():
    st = ds.step(_yr(2023, None, None, None), _yr(2024, 100.0, 0, 0, 0))
    for key in ("spend", "claims", "patients", "intensity", "price", "units_per_claim",
                "price_per_unit"):
        assert st[key] is None
    assert ds.points(st) is None
    assert ds.factors_of(st) is None
    unit_less = ds.step(_yr(2023, 10.0, 2, 1, None), _yr(2024, 12.0, 2, 1, 0.0))
    assert unit_less["units_per_claim"] is None and unit_less["price_per_unit"] is None


def test_combine_weights_each_part_by_its_prior_spend():
    # Prolia-shaped, $mm: Part D 673.7 to 772, Part B 2190 to 2431.
    d = ds.step(_yr(2023, 673.7, 403.6, 255.6), _yr(2024, 772.0, 450.9, 285.0))
    b = ds.step(_yr(2023, 2190.0, 1311.5, 680.1), _yr(2024, 2431.0, 1339.3, 700.7))
    out = ds.combine([{"part": "D", "prior_spend": 673.7, "step": d},
                      {"part": "B", "prior_spend": 2190.0, "step": b}])
    w_d = 673.7 / (673.7 + 2190.0)
    assert out["weights"]["D"] == pytest.approx(w_d) and w_d == pytest.approx(0.235, abs=5e-4)
    assert out["spend"] == pytest.approx(w_d * d["spend"] + (1 - w_d) * b["spend"])
    assert out["spend"] == pytest.approx((772.0 + 2431.0) / (673.7 + 2190.0) - 1)
    assert d["spend"] == pytest.approx(0.146, abs=5e-4)
    assert b["spend"] == pytest.approx(0.110, abs=5e-4)
    assert sum(out["by_part"].values()) == pytest.approx(out["spend"], abs=1e-12)
    assert sum(out["points"].values()) == pytest.approx(out["spend"], abs=1e-12)
    assert "beneficiaries" not in out and "patients_total" not in out
