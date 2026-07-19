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

    assert products["Mounjaro"]["value"] == pytest.approx(22.966e9)
    assert products["Zepbound"]["value"] == pytest.approx(13.542e9)
    assert products["Verzenio"]["value"] == pytest.approx(5.723e9)


def test_the_unit_travels_with_the_value():
    """Novo reports in DKK and Sanofi in EUR. A DKK figure stored as USD is wrong by
    a factor of six, so the unit is read from the row and never assumed."""
    products = extract_products(_rows(), LLY_ADSH, "20251231")
    assert products["Mounjaro"]["unit"] == "USD"

    rows = [{"adsh": "X", "tag": "Revenue", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "127090000000", "uom": "DKK",
             "segments": "ProductsAndServices=Ozempic;"}]
    assert extract_products(rows, "X", "20251231")["Ozempic"]["unit"] == "DKK"


def test_the_ifrs_product_axis_is_read_too():
    """20-F filers tag ProductsAndServices, not ProductOrService. Missing it returned
    nothing at all for five of the sixteen companies."""
    rows = [{"adsh": "X", "tag": "RevenueFromSaleOfGoods", "ddate": "20251231",
             "qtrs": "4", "coreg": "", "value": "8400000000", "uom": "USD",
             "segments": "ProductsAndServices=Farxiga;"}]
    assert extract_products(rows, "X", "20251231")["Farxiga"]["value"] == 8.4e9


def test_a_product_inside_one_segment_is_read_at_that_level():
    """Merck tags every product inside a business segment and never on its own.
    Rejecting the row outright returned nothing for Merck, JNJ and Novo."""
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "31640000000", "uom": "USD",
             "segments": "BusinessSegments=Pharmaceutical;"
                         "ConsolidationItems=Operating;ProductOrService=Keytruda;"}]
    assert extract_products(rows, "X", "20251231")["Keytruda"]["value"] == 31.64e9


def test_a_product_spread_across_segments_is_skipped():
    """Two segments at the shallowest level would have to be added, and a hierarchy
    like JNJ's nests, so summing would double count."""
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "100", "uom": "USD",
             "segments": "BusinessSegments=A;ProductOrService=Split;"},
            {"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "200", "uom": "USD",
             "segments": "BusinessSegments=B;ProductOrService=Split;"}]
    assert extract_products(rows, "X", "20251231") == {}


def test_the_shallowest_level_wins_over_a_deeper_one():
    """A product total and its geographic split both present: the total wins."""
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "500", "uom": "USD",
             "segments": "ProductOrService=Solo;"},
            {"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "9999", "uom": "USD",
             "segments": "BusinessSegments=A;ProductOrService=Solo;"}]
    assert extract_products(rows, "X", "20251231")["Solo"]["value"] == 500


def test_category_members_are_not_treated_as_products():
    """The filing tags therapeutic areas and roll-ups on the same axis as products."""
    products = extract_products(_rows(), LLY_ADSH, "20251231")

    for rollup in ("Product", "OtherProductTotal", "CollaborationandOtherRevenue"):
        assert rollup not in products
    # The area aggregates survive extraction but never match an asset by brand name,
    # which is the second filter. What matters here is that no roll-up total does.
    assert (products["Mounjaro"]["value"]
            < products.get("CardiometabolicHealth", {}).get("value", float("inf")))


def test_rows_carrying_a_third_axis_are_skipped():
    """A product-by-arrangement row is a slice of the product, not its total."""
    rows = [{"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "370000000", "uom": "USD",
             "segments": "ProductOrService=Jardiance;TypeOfArrangement=OneTimePayment;"},
            {"adsh": "X", "tag": "Revenues", "ddate": "20251231", "qtrs": "4",
             "coreg": "", "value": "3432000000", "uom": "USD",
             "segments": "ProductOrService=Jardiance;"}]
    # Both levels are present, so the un-dimensioned total wins and the arrangement
    # slice never stands in for the product.
    assert extract_products(rows, "X", "20251231")["Jardiance"]["value"] == 3.432e9


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


# --- groupings must not be counted as products ---------------------------
def test_a_product_is_kept_and_a_grouping_is_not():
    """Filers put products and the categories containing them on the same axis, so
    Novo tags Ozempic and TotalDiabetesCare, which contains it."""
    from fetchers.product_revenue_sec import is_aggregate

    for product in ("Keytruda", "Ozempic", "Lynparza", "Rotateq", "Eliquis",
                    "Gardasil Gardasil 9", "Verzenio", "Nucala"):
        assert not is_aggregate(product), product
    for grouping in ("TotalDiabetesCare", "CardiometabolicHealth", "Oncology",
                     "GrowthBrands", "LegacyBrands", "OtherPharmaceutical",
                     "ExcludingComirnatyAndPaxlovid", "Top20Products",
                     "RestOfPortfolio", "SalesRevenueGross", "NetProductSales",
                     "Livestock", "AllOtherProducts", "SpecialtyMedicine"):
        assert is_aggregate(grouping), grouping


def test_a_revenue_type_prefix_is_stripped_from_the_name():
    """Merck reports partnered products as AllianceRevenueLynparza."""
    from fetchers.product_revenue_sec import display_name

    assert display_name("AlliancerevenueLynparza") == "Lynparza"
    assert display_name("AllianceRevenueReblozyl") == "Reblozyl"


def test_concatenated_brands_are_spaced_not_split():
    """The filing reports one number against several brands, so the row stays one row."""
    from fetchers.product_revenue_sec import display_name

    assert display_name("GardasilGardasil9") == "Gardasil Gardasil 9"
    assert display_name("Pneumovax23") == "Pneumovax 23"
