"""Product revenue extraction from the SEC Financial Statement Data Sets, no network.

The fixture is a real slice of num.txt: every full-year revenue row of Lilly's FY2025
10-K, headers included. It is the payload the fetcher actually reads, so a change in
the source's shape fails here rather than silently producing nothing.
"""

import csv
from pathlib import Path

import pytest

from fetchers.product_revenue_sec import (
    extract_products,
    parse_segments,
    quarters_back,
    worldwide,
)

FIXTURES = Path(__file__).parent / "fixtures"
LLY_ADSH = "0000059478-26-000013"


def _rows():
    with (FIXTURES / "fsds_num_lly.txt").open() as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# --- pure helpers ---------------------------------------------------------
def test_segments_parse_into_axes():
    assert parse_segments("Geographical=US;ProductOrService=Zepbound;") == {
        "Geographical": "US", "ProductOrService": "Zepbound"}
    assert parse_segments("") == {}
    assert parse_segments(None) == {}


def test_a_row_with_no_geography_is_already_worldwide():
    assert worldwide({None: 5.0}) == 5.0
    # And it wins outright, rather than being added to the parts.
    assert worldwide({None: 5.0, "US": 3.0}) == 5.0


def test_complementary_regions_may_be_summed():
    assert worldwide({"US": 13.484, "NonUs": 0.058}) == pytest.approx(13.542)


def test_an_unrecognised_split_yields_nothing():
    """Europe and International may overlap, and a wrong total is worse than none."""
    assert worldwide({"Europe": 3.0, "International": 4.0}) is None
    assert worldwide({"US": 3.0}) is None      # a part on its own is not a total


def test_quarters_run_backwards_across_a_year_boundary():
    import datetime as dt
    assert quarters_back(5, dt.date(2026, 2, 10)) == [
        "2026q1", "2025q4", "2025q3", "2025q2", "2025q1"]


# --- against the real payload --------------------------------------------
def test_worldwide_product_revenue_matches_the_filing():
    """Mounjaro is 13.651bn US plus 9.315bn non-US, as filed."""
    products = extract_products(_rows(), LLY_ADSH, "20251231")

    assert products["Mounjaro"] == pytest.approx(22.966e9)
    assert products["Zepbound"] == pytest.approx(13.542e9)
    assert products["Verzenio"] == pytest.approx(5.723e9)


def test_category_members_are_not_treated_as_products():
    """The filing tags therapeutic areas and roll-ups on the same axis as products."""
    products = extract_products(_rows(), LLY_ADSH, "20251231")

    for rollup in ("Product", "OtherProductTotal", "CollaborationandOtherRevenue"):
        assert rollup not in products
    # The area aggregates survive extraction but never match an asset by brand name,
    # which is the second filter. What matters here is that no roll-up total does.
    assert products["Mounjaro"] < products.get("CardiometabolicHealth", float("inf"))


def test_rows_carrying_a_third_axis_are_skipped():
    """A product-by-arrangement row is a slice of the product, not its total."""
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "370000000",
             "segments": "ProductOrService=Jardiance;TypeOfArrangement=OneTimePayment;"}]
    assert extract_products(rows, "X", "20251231") == {}


def test_only_the_requested_filing_and_period_are_read():
    rows = _rows()
    assert extract_products(rows, "other-adsh", "20251231") == {}
    assert extract_products(rows, LLY_ADSH, "20241231") == {}


def test_a_quarterly_row_is_not_a_year():
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "1",
             "coreg": "", "value": "1000", "segments": "ProductOrService=Zepbound;"}]
    assert extract_products(rows, "X", "20251231") == {}


def test_a_coregistrant_row_is_skipped():
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "SUBSIDIARY", "value": "1000",
             "segments": "ProductOrService=Zepbound;"}]
    assert extract_products(rows, "X", "20251231") == {}
