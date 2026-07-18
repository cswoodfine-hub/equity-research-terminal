"""The 8-K item taxonomy. Pure, no network."""

import edgar_items as ei


def test_a_filing_reads_as_what_it_is_about():
    """Regression: every filing stored the title "8-K", so the feed said "8-K: 8-K"."""
    assert ei.describe("2.01") == "Acquisition or disposition completed"
    assert ei.describe("1.01") == "Material agreement signed"
    assert ei.describe("2.02") == "Results of operations"


def test_exhibits_never_lead_a_headline():
    """9.01 rides along with almost everything and says nothing on its own."""
    assert ei.describe("2.01,9.01") == "Acquisition or disposition completed"
    # When routine items are all there is, they are still better than the form name.
    assert ei.describe("9.01") == "Financial statements and exhibits"


def test_several_substantive_items_are_all_named():
    assert ei.describe("1.01,2.03") == ("Material agreement signed, "
                                        "Direct financial obligation created")


def test_unknown_codes_are_not_guessed_at():
    assert ei.describe("9.99") == "Item 9.99"
    assert ei.describe("") == "8-K"
    assert ei.describe(None, "6-K") == "6-K"


def test_material_items_are_the_ones_that_move_a_case():
    assert ei.is_material("2.01") is True      # acquisition completed
    assert ei.is_material("1.01") is True      # material agreement
    assert ei.is_material("5.01") is True      # change in control
    assert ei.is_material("5.07") is False     # shareholder vote
    assert ei.is_material("7.01") is False     # Reg FD
    assert ei.is_material("") is False


def test_materiality_survives_the_round_trip_through_the_title():
    """The filings table keeps the description, not the codes, and the diff engine
    recovers materiality from the words it wrote."""
    for code in ("2.01", "1.01", "5.01", "2.06"):
        assert ei.is_material_title(ei.describe(code)) is True
    for code in ("5.07", "7.01", "8.01"):
        assert ei.is_material_title(ei.describe(code)) is False


def test_reg_fd_never_leads_a_headline():
    """Regulation FD says how something was disclosed, not what happened."""
    assert ei.describe("2.01,7.01") == "Acquisition or disposition completed"
    assert ei.describe("7.01") == "Regulation FD disclosure"   # still better than "8-K"


def test_a_long_item_list_is_capped():
    """Four labels in one headline is unreadable; the count carries the rest."""
    out = ei.describe("1.01,2.01,2.03,2.06,3.01")
    assert out.count(",") == 3 and out.endswith("more")
    assert out.startswith("Material agreement signed")
