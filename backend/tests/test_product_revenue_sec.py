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

    assert display_name("Pneumovax23") == "Pneumovax 23"
    # A member the case rule can space is still spaced, where nothing curates it.
    assert display_name("FooBar9") == "Foo Bar 9"


def test_a_shouted_multi_brand_member_gets_a_curated_name():
    """GardasilGardasil9 splits itself on the case boundary. TRIKAFTAKAFTRIO has none,
    and no rule can say where Trikafta ends and Kaftrio begins, so the five that arrive
    this way are written down instead."""
    from fetchers.product_revenue_sec import display_name
    assert display_name("TRIKAFTAKAFTRIO") == "Trikafta / Kaftrio"
    assert display_name("MINJUVIMONJUVI") == "Minjuvi / Monjuvi"
    # Case and spacing in the filed label do not matter.
    assert display_name("trikaftakaftrio") == "Trikafta / Kaftrio"


def test_curation_does_not_disturb_the_rules():
    from fetchers.product_revenue_sec import display_name
    assert display_name("AlliancerevenueLynparza") == "Lynparza"
    assert display_name("Trikafta") == "Trikafta"


def test_merck_group_lines_read_as_the_groups_they_are():
    """Merck reports four of its lines against several brands at once and never splits
    them. Spacing the concatenation left "Gardasil Gardasil 9" and, where the case rule
    had nothing to work on, "Pro Quad MMRIIVarivax", which reads as neither a product nor
    a group. The slash is what says one number covers several brands."""
    from fetchers.product_revenue_sec import display_name

    assert display_name("GardasilGardasil9") == "Gardasil / Gardasil 9"
    assert display_name("ProQuadMMRIIVarivax") == "ProQuad / M-M-R II / Varivax"
    assert display_name("IsentressIsentressHD") == "Isentress / Isentress HD"
    # A revenue-type prefix still comes off a curated member's own label.
    assert display_name("AdempasVerquvo") == "Adempas / Verquvo"


def test_a_member_that_is_the_sum_of_others_is_a_grouping():
    """Gilead tags its HIV franchise beside the products inside it, both at the same
    level and both looking like products. Keeping both counted 20.7bn twice, which the
    sum-past-revenue guard then answered by discarding the whole company."""
    from fetchers.product_revenue_sec import drop_groupings

    rows = [{"ticker": "GILD", "fiscal_year": 2025, "member": m, "value": v}
            for m, v in (("HIVProductSales", 20752e6), ("HIVProductsBiktarvy", 14334e6),
                         ("HIVProductsDescovy", 2758e6), ("HIVProductsGenvoya", 1498e6),
                         ("HIVProductsOdefsey", 1167e6), ("HIVProductsSymtuzaRevenueShare", 495e6),
                         ("Trodelvy", 1397e6))]
    kept = {r["member"] for r in drop_groupings(rows)}
    assert "HIVProductSales" not in kept
    assert "HIVProductsBiktarvy" in kept and "Trodelvy" in kept


def test_a_grouping_is_found_where_the_members_name_it():
    """United Therapeutics tags Tyvaso at exactly TyvasoDPI plus NebulizedTyvaso."""
    from fetchers.product_revenue_sec import drop_groupings

    rows = [{"ticker": "UTHR", "fiscal_year": 2025, "member": m, "value": v}
            for m, v in (("Tyvaso", 1878e6), ("TyvasoDPI", 1292e6),
                         ("NebulizedTyvaso", 586e6), ("Remodulin", 527e6))]
    kept = {r["member"] for r in drop_groupings(rows)}
    assert kept == {"TyvasoDPI", "NebulizedTyvaso", "Remodulin"}


def test_one_product_inside_another_is_not_a_grouping():
    """Keytruda Qlex is a form of Keytruda and is nothing like the whole of it. A single
    member sharing a name proves nothing, which is why two are required."""
    from fetchers.product_revenue_sec import drop_groupings

    rows = [{"ticker": "MRK", "fiscal_year": 2025, "member": m, "value": v}
            for m, v in (("Keytruda", 31641e6), ("KeytrudaQlex", 40e6))]
    assert len(drop_groupings(rows)) == 2


def test_members_that_do_not_add_up_are_all_kept():
    from fetchers.product_revenue_sec import drop_groupings

    rows = [{"ticker": "X", "fiscal_year": 2025, "member": m, "value": v}
            for m, v in (("AlphaProducts", 900e6), ("AlphaProductsOne", 100e6),
                         ("AlphaProductsTwo", 120e6))]
    assert len(drop_groupings(rows)) == 3


def _novo_row(geography, ddate, member, value, segment="ObesityAndDiabetesCare"):
    return {"adsh": "novo", "qtrs": "4", "ddate": ddate, "coreg": "",
            "tag": "RevenueFromContractWithCustomerExcludingAssessedTax",
            "value": str(value), "uom": "DKK",
            "segments": f"GeographicalAreas={geography};ProductsAndServices={member};"
                        f"Segments={segment};"}


# Novo's premix insulin, its two members, and one product that has nothing to do with
# either, as filed in three geographies. The categories carry no hint in their names
# that they contain anything, which is the whole difficulty.
_PREMIX = {
    "US":   {"PremixInsulin": 570, "NovoMixAndNovoLogMix": 320, "Ryzodeg": 250, "Ozempic": 88470},
    "CN":   {"PremixInsulin": 4100, "NovoMixAndNovoLogMix": 2600, "Ryzodeg": 1500, "Ozempic": 6200},
    "EUCAN": {"PremixInsulin": 1800, "NovoMixAndNovoLogMix": 900, "Ryzodeg": 900, "Ozempic": 21000},
}


def test_a_grouping_is_found_where_only_the_arithmetic_says_so():
    """LongActingInsulin and Tresiba read as two products of equal standing. Nothing in
    either name says one contains the other, and Novo's did: 47bn of insulin categories
    were counted twice, which put every year past reported revenue and lost the company."""
    from fetchers.product_revenue_sec import grouping_members

    rows = [_novo_row(geo, ddate, member, value)
            for ddate in ("20241231", "20251231")
            for geo, members in _PREMIX.items()
            for member, value in members.items()]
    assert grouping_members(rows, "novo") == {"PremixInsulin"}


def test_a_coincidence_in_one_column_is_not_a_grouping():
    """The test is worthless read against a single column: with twenty products on the
    page some subset adds up to almost anything, and Novo's 2025 column alone names
    Ozempic as a grouping of Wegovy and three others. Six cells and it does not."""
    from fetchers.product_revenue_sec import grouping_members

    # Ozempic is the sum of the other two in the United States and nowhere else.
    rows = [_novo_row(geo, ddate, member, value)
            for ddate in ("20241231", "20251231")
            for geo, members in (
                ("US", {"Ozempic": 900, "Wegovy": 600, "Rybelsus": 300}),
                ("CN", {"Ozempic": 900, "Wegovy": 100, "Rybelsus": 200}),
                ("EUCAN", {"Ozempic": 900, "Wegovy": 400, "Rybelsus": 100}))
            for member, value in members.items()]
    assert grouping_members(rows, "novo") == set()


def test_too_few_cells_to_judge_decides_nothing():
    """A filer that reports one column has no evidence to offer, and guessing from it
    called Tagrisso a grouping of four smaller AstraZeneca products."""
    from fetchers.product_revenue_sec import grouping_members

    rows = [_novo_row("US", "20251231", m, v)
            for m, v in (("Ozempic", 900), ("Wegovy", 600), ("Rybelsus", 300))]
    assert grouping_members(rows, "novo") == set()


def test_a_grouping_does_not_reach_across_segments():
    """A grouping is made of the lines printed beneath it. Novo's rare disease lines add
    up to its insulin categories often enough to matter, and belong to neither."""
    from fetchers.product_revenue_sec import grouping_members

    rows = [_novo_row(geo, ddate, member, value, segment)
            for ddate in ("20241231", "20251231")
            for geo in ("US", "CN", "EUCAN")
            for member, value, segment in (
                ("PremixInsulin", 900, "ObesityAndDiabetesCare"),
                ("NovoSeven", 600, "RareDisease"),
                ("HaemophiliaA", 300, "RareDisease"))]
    assert grouping_members(rows, "novo") == set()


def _azn_row(tag, member, value, geography=None, ddate="20251231"):
    seg = f"ProductsAndServices={member};"
    if geography:
        seg = f"MarketsOfCustomers={geography};" + seg
    return {"adsh": "azn", "qtrs": "4", "ddate": ddate, "coreg": "", "tag": tag,
            "value": str(value), "uom": "USD", "segments": seg}


def test_alliance_revenue_is_added_to_the_product_it_belongs_to():
    """A partnered medicine earns AstraZeneca two different things and it tags them
    separately. Enhertu is 977 of RevenueFromSaleOfGoods and 1,798 of AllianceRevenue in
    FY2025, and AstraZeneca's own table calls the 2,775 Product Revenue. Reading only the
    tags that begin with "Revenue" took the 977 and called it the year."""
    from fetchers.product_revenue_sec import extract_products

    rows = [_azn_row("RevenueFromSaleOfGoods", "Enhertu", 977e6),
            _azn_row("AllianceRevenue", "Enhertu", 1798e6),
            _azn_row("RevenueFromSaleOfGoods", "Tezspire", 458e6),
            _azn_row("AllianceRevenue", "Tezspire", 673e6)]
    found = extract_products(rows, "azn")
    assert found["Enhertu"]["value"] == 2775e6
    assert found["Tezspire"]["value"] == 1131e6


def test_an_expense_carrying_a_product_axis_is_still_not_revenue():
    """Lilly and Biogen tag research and development against a product, and Biogen and
    Vertex tag cost of goods. Those pass no filter here and must not: adding an expense
    to a product's revenue would be worse than missing the revenue."""
    from fetchers.product_revenue_sec import extract_products

    rows = [_azn_row("RevenueFromSaleOfGoods", "Tagrisso", 7254e6),
            _azn_row("ResearchAndDevelopmentExpense", "Tagrisso", 900e6),
            _azn_row("CostOfGoodsAndServicesSold", "Tagrisso", 500e6)]
    assert extract_products(rows, "azn")["Tagrisso"]["value"] == 7254e6


def test_a_product_with_only_sales_is_unchanged():
    from fetchers.product_revenue_sec import extract_products

    rows = [_azn_row("RevenueFromSaleOfGoods", "Farxiga", 8000e6)]
    assert extract_products(rows, "azn")["Farxiga"]["value"] == 8000e6
