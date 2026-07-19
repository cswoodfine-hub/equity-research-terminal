"""The exclusivity cliff panel, in both of the states it has to hold.

Lives here so ``cd backend && pytest -q`` stays the one test command. Every figure is
synthetic; nothing in this file is a claim about any company.

The panel exists to keep two things visible at once: what the cliff costs, and how much
of that cost is actually known. Those tests are the ones that matter, because the
failure mode is silent, a thin table rendering as a small cliff.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import cliff  # noqa: E402


def _bucket(year, covered=(), uncovered=0):
    return {"year": year, "products": len(covered) + uncovered,
            "revenue": float(sum(covered)),
            "covered": [{"revenue": v} for v in covered],
            "uncovered": [{"revenue": None}] * uncovered}


def _exposure(buckets, **kwargs):
    covered = sum(len(b["covered"]) for b in buckets)
    uncovered = sum(len(b["uncovered"]) for b in buckets)
    payload = {"buckets": buckets, "products_covered": covered,
               "products_uncovered": uncovered,
               "products_at_risk": covered + uncovered,
               "revenue_at_risk": sum(b["revenue"] for b in buckets),
               "currency": "USD", "mixed_currency": False,
               "coverage": covered / (covered + uncovered) if covered + uncovered else None}
    payload.update(kwargs)
    return payload


def _filled(svg):
    return svg.count('fill="#F2545B"') + svg.count('fill="#f2545b"')


def _hollow(svg):
    return svg.count('fill="none" stroke=')


def test_nothing_at_risk_renders_nothing():
    assert cliff.render(_exposure([_bucket(2026), _bucket(2027)])) == ""
    assert cliff.render({}) == ""


def test_every_product_gets_a_mark_priced_or_not():
    """The comb is one mark per product. A missing mark is a hidden product."""
    svg = cliff.render(_exposure([_bucket(2029, covered=(4e9,), uncovered=3),
                                  _bucket(2031, uncovered=2)]))
    # One bar plus one covered mark are filled; the five unpriced ones are hollow.
    assert _hollow(svg) == 5
    assert _filled(svg) >= 2


def test_an_unpriced_cliff_says_so_rather_than_drawing_an_empty_axis():
    svg = cliff.render(_exposure([_bucket(2029, uncovered=4)]))
    assert "counts products rather than money" in svg
    assert _hollow(svg) == 4
    assert _filled(svg) == 0          # no bar, because nothing is priced


def test_empty_years_stay_on_the_axis():
    """Dropping them would leave labels reading 29, later, which loses the timing."""
    buckets = [_bucket(2026 + i) for i in range(6)]
    buckets[3] = _bucket(2029, uncovered=2)
    svg = cliff.render(_exposure(buckets))
    for year in ("26", "27", "28", "29", "30", "31"):
        assert f">{year}</text>" in svg


def test_the_register_collapses_when_there_is_no_revenue_and_grows_when_there_is():
    unpriced = cliff.render(_exposure([_bucket(2029, uncovered=2)]))
    priced = cliff.render(_exposure([_bucket(2029, covered=(4e9,), uncovered=1)]))
    assert _height(priced) > _height(unpriced)


def _height(svg):
    box = svg.split('viewBox="0 0 ', 1)[1].split('"', 1)[0]
    return float(box.split()[1])


def test_caption_states_coverage_when_partly_priced():
    caption = cliff.caption(_exposure([_bucket(2029, covered=(4e9,), uncovered=3)]))
    assert "4.00bn USD" in caption
    assert "1 of the 4 products" in caption
    assert "understate" in caption          # the gap is named, not glossed


def test_caption_is_explicit_when_nothing_is_priced():
    caption = cliff.caption(_exposure([_bucket(2029, uncovered=4)]))
    assert "none has a revenue figure on file" in caption
    assert "count rather than a sum" in caption


def test_caption_refuses_to_total_mixed_currencies():
    exposure = _exposure([_bucket(2029, covered=(4e9,))], mixed_currency=True,
                         currency=None)
    assert "not converted" in cliff.caption(exposure)


def test_caption_is_empty_when_nothing_is_at_risk():
    assert cliff.caption(_exposure([_bucket(2026)])) == ""


def test_a_billions_figure_carries_the_true_minus():
    assert cliff._fmt(4.2e9, "USD") == "4.20bn USD"
    assert cliff._fmt(-4.2e9).startswith("−")
    assert cliff._fmt(None) == "—"
