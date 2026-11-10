"""The borrowing a pipeline price rests on, made a link, and the two ways it goes wrong."""

import comparator_link as C


def test_a_cue_is_required_and_a_workbook_cell_is_not_one():
    """evidence.py grades 'workbook' and 'fitted' as analogue. Neither borrowed a drug,
    and repricing Casgevy off a workbook cell would be the error this guards."""
    assert C.CUE.search("comparator estimate: Leqvio (inclisiran), CMS Part D 2024")
    assert C.CUE.search("Leqvio, the closest analogue on file: an injectable siRNA")
    assert not C.CUE.search("~18% gross-to-net; Medicare max 1.65mm (workbook C10)")


def test_two_named_comparators_are_two_links_and_the_longer_brand_wins_its_span():
    brands = {"eliquis": 1, "xarelto": 2, "pulmicort": 3, "pulmicort respules": 4}
    assert C.resolve("comparator estimate: Eliquis 4,695 and Xarelto 4,718", brands) == [1, 2]
    assert C.resolve("priced off Pulmicort Respules", brands) == [4]       # not 3 as well
    assert C.resolve("the price is Eliquis's", brands, own_asset_id=1) == []  # never itself


def test_drift_is_nil_and_says_why_where_the_seed_cites_the_latest_cms_year():
    series = {("D", 2023): {"spend_per_beneficiary": 100.0, "beneficiaries": 1000},
              ("D", 2024): {"spend_per_beneficiary": 110.0, "beneficiaries": 1500}}
    got = C.drift(series, cited_year=2024)
    assert got["moved"] is False and "latest CMS year" in got["reason"]
    got = C.drift(series, cited_year=2023)
    assert got["moved"] is True
    assert abs(got["price_change"] - 0.10) < 1e-9 and abs(got["volume_change"] - 0.5) < 1e-9


def test_the_part_with_the_most_beneficiaries_is_the_one_measured():
    """A drug in both Part B and Part D is measured on the part that carries it."""
    series = {("B", 2023): {"spend_per_beneficiary": 50.0, "beneficiaries": 10},
              ("B", 2024): {"spend_per_beneficiary": 60.0, "beneficiaries": 12},
              ("D", 2023): {"spend_per_beneficiary": 100.0, "beneficiaries": 1000},
              ("D", 2024): {"spend_per_beneficiary": 90.0, "beneficiaries": 1300}}
    assert C.drift(series, 2023)["part"] == "D"
