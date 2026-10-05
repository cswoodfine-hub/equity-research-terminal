"""The Medicare growth split chart: one column per year, factors stacked by sign, the
spend dot they add up to, the tracked median as a tick, and a null drawn as a gap."""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

from components import charts, tokens  # noqa: E402

LABELS = {"patients": "Patients", "intensity": "Fills per patient", "price": "Cost per fill"}

# Eliquis 2023 to 2024 and a step with a falling price, as the API returns them.
ELIQUIS = {"from": 2023, "to": 2024, "spend": 0.136891, "patients": 0.126518,
           "intensity": 0.0077, "price": 0.0015, "like_for_like": True,
           "points": {"patients": 0.1271, "intensity": 0.0082, "price": 0.0016}}
FALLING = {"from": 2022, "to": 2023, "spend": 0.05, "patients": 0.08, "intensity": 0.01,
           "price": -0.0374, "like_for_like": True,
           "points": {"patients": 0.0786, "intensity": 0.0102, "price": -0.0388}}


def _parse(svg: str):
    return ET.fromstring(svg)


def _rects(svg: str, cls: str) -> list[dict]:
    return [dict(re.findall(r'(\w[\w-]*)="([^"]*)"', m))
            for m in re.findall(rf'<rect ([^>]*class="{cls}"[^>]*)>', svg)]


def _zero_y(svg: str) -> float:
    return float(re.search(r'<line [^>]*y1="([\d.]+)"[^>]*class="zero"', svg).group(1))


def test_one_group_per_step_and_valid_svg():
    svg = charts.growth_split([FALLING, ELIQUIS], factor_labels=LABELS)
    _parse(svg)
    assert svg.count('class="split-step"') == 2
    assert svg.count('class="spend"') == 2
    assert "Fills per patient" in svg and "Cost per fill" in svg


def test_a_negative_price_sits_below_the_zero_line():
    svg = charts.growth_split([FALLING], factor_labels=LABELS)
    price = _rects(svg, "seg seg-price")[0]
    assert float(price["y"]) >= _zero_y(svg) - 0.01
    patients = _rects(svg, "seg seg-patients")[0]
    assert float(patients["y"]) + float(patients["height"]) <= _zero_y(svg) + 0.01


def test_segments_take_the_fixed_factor_colours():
    svg = charts.growth_split([ELIQUIS])
    assert _rects(svg, "seg seg-patients")[0]["fill"] == tokens.PURPLE_BOOK
    assert _rects(svg, "seg seg-price")[0]["fill"] == tokens.ORANGE_BOOK
    assert "Patients +12.7% (12.7 pts)" in svg


def test_null_patients_draw_two_segments():
    two = {"from": 2023, "to": 2024, "spend": 0.21, "patients": None, "intensity": None,
           "claims": 0.10, "price": 0.10, "points": {"claims": 0.105, "price": 0.105}}
    svg = charts.growth_split([two], factor_labels=LABELS)
    assert len(re.findall(r'class="seg seg-', svg)) == 2
    assert not _rects(svg, "seg seg-patients")


def test_a_flagged_step_uses_the_hatch():
    flagged = {**ELIQUIS, "like_for_like": False}
    svg = charts.growth_split([flagged])
    hatch_id = re.findall(r'<pattern id="([^"]+)"', svg)[1]
    nlfl = _rects(svg, "nlfl")
    assert len(nlfl) == 2 and all(r["fill"] == f"url(#{hatch_id})" for r in nlfl)
    assert not _rects(charts.growth_split([ELIQUIS]), "nlfl")


def test_the_baseline_tick_only_when_given():
    base = [{"from": 2023, "to": 2024, "spend": 0.068, "n": 231}]
    assert 'class="baseline"' in charts.growth_split([ELIQUIS], baseline=base)
    assert "231 brands" in charts.growth_split([ELIQUIS], baseline=base)
    assert 'class="baseline"' not in charts.growth_split([ELIQUIS])


def test_a_step_with_no_split_is_a_gap_not_a_zero():
    bare = {"from": 2023, "to": 2024, "spend": 0.05, "points": None}
    svg = charts.growth_split([bare])
    assert 'class="nullband"' in svg and 'class="seg ' not in svg


def test_a_provisional_step_is_hollow():
    svg = charts.growth_split([{**ELIQUIS, "provisional": True}])
    assert all(r["fill"] == "none" for r in _rects(svg, "seg seg-patients"))


def test_empty_steps_draw_nothing():
    assert charts.growth_split([]) == ""
    assert charts.growth_split([{"from": 2023, "to": 2024, "spend": None}]) == ""
