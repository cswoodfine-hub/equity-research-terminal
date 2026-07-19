"""The revenue mix donut: which products get their own slice and which are bracketed.

Lives here so ``cd backend && pytest -q`` stays the one test command. Figures are
synthetic.

A pie is only readable while the slices are few and different in size, so the whole
point of this module is the bracketing rule. That is what the tests cover, along with
the arithmetic that must not drift: the slices have to account for the total exactly.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "frontend"))

import revenue_mix  # noqa: E402


def _products(*pairs):
    return [{"brand_name": name, "value": value} for name, value in pairs]


def test_the_biggest_products_get_their_own_slice():
    drivers, tail = revenue_mix.split(
        _products(("Big", 10e9), ("Mid", 5e9), ("Small", 2e9)))
    assert [p["brand_name"] for p in drivers] == ["Big", "Mid", "Small"]
    assert tail == []


def test_beyond_the_top_slices_everything_is_bracketed():
    products = _products(*[(f"P{i}", (20 - i) * 1e9) for i in range(10)])
    drivers, tail = revenue_mix.split(products, top=6)
    assert len(drivers) == 6
    assert len(tail) == 4


def test_a_sliver_is_bracketed_however_high_it_ranks():
    """Under 2% a wedge is a hairline, and a circle of hairlines compares nothing."""
    drivers, tail = revenue_mix.split(
        _products(("Big", 100e9), ("Sliver", 1e9)), top=6, min_share=0.02)
    assert [p["brand_name"] for p in drivers] == ["Big"]
    assert [p["brand_name"] for p in tail] == ["Sliver"]


def test_products_are_ordered_largest_first():
    drivers, _ = revenue_mix.split(_products(("A", 1e9), ("B", 9e9), ("C", 5e9)))
    assert [p["brand_name"] for p in drivers] == ["B", "C", "A"]


def test_products_with_no_value_are_left_out():
    drivers, tail = revenue_mix.split(
        [{"brand_name": "Known", "value": 5e9},
         {"brand_name": "Unknown", "value": None},
         {"brand_name": "Zero", "value": 0}])
    assert [p["brand_name"] for p in drivers] == ["Known"]
    assert tail == []


def test_nothing_to_draw_renders_nothing():
    assert revenue_mix.render([]) == ""
    assert revenue_mix.render([{"brand_name": "None", "value": None}]) == ""
    assert revenue_mix.caption([]) == ""


def test_the_slices_account_for_the_whole_total():
    """The bracketed slice carries the tail's value, so the circle is complete."""
    products = _products(*[(f"P{i}", (20 - i) * 1e9) for i in range(10)])
    drivers, tail = revenue_mix.split(products, top=6)
    total = sum(p["value"] for p in products)
    assert sum(p["value"] for p in drivers) + sum(p["value"] for p in tail) == total


def test_the_donut_states_the_total_and_names_the_tail():
    products = _products(*[(f"P{i}", (20 - i) * 1e9) for i in range(10)])
    svg = revenue_mix.render(products, "USD", 2025)
    assert "other, 4 products" in svg
    assert "USD bn" in svg
    # Six drivers plus the bracket, each with a legend swatch and a wedge.
    assert svg.count("<path") == 7


def test_a_single_product_still_draws_a_ring():
    svg = revenue_mix.render(_products(("Only", 4e9)), "USD")
    assert svg.startswith("<svg") and "<path" in svg


def test_the_caption_says_what_is_missing():
    caption = revenue_mix.caption(_products(("Big", 30e9), ("Small", 10e9)), "USD", 2025)
    assert "FY2025" in caption
    assert "75%" in caption                    # Big's share, stated plainly
    assert "not total company revenue" in caption


def test_the_caption_counts_the_bracketed_products():
    products = _products(*[(f"P{i}", (20 - i) * 1e9) for i in range(10)])
    assert "4 smallest are bracketed" in revenue_mix.caption(products, "USD")


def test_a_singular_tail_reads_singular():
    products = _products(("A", 50e9), ("B", 20e9), ("C", 10e9), ("D", 5e9),
                         ("E", 4e9), ("F", 3e9), ("G", 2e9))
    svg = revenue_mix.render(products, "USD")
    assert "other, 1 product<" in svg
