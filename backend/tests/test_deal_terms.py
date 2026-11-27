"""What a deal pays, split the way the filing splits it.

The text is verbatim from the two press releases Johnson & Johnson furnished with one 8-K
on 29 July 2026. Both are in the fixture because they are the case that matters: two deals,
two structures, one filing, and a parser that blurs them reports each at the other's price.
"""

import deal_terms

SAIL = ("Additionally, Johnson & Johnson has been granted an exclusive option to acquire "
        "Sail for $2.58 billion. Under the terms of the agreements, Johnson & Johnson "
        "would make total initial payments of $785 million, including a $465 million "
        "equity investment, and additional contingent payments of $140 million if certain "
        "development milestones are achieved. Subject to Johnson & Johnson's decision to "
        "exercise the option, Johnson & Johnson would make an additional payment of "
        "$2.58 billion.")

FIREFLY = ("Johnson & Johnson today announced it has completed the acquisition of Firefly "
           "Bio, Inc., a biotechnology company advancing its proprietary degrader antibody "
           "conjugate platform, for $1 billion in cash.")


def test_the_four_commitments_are_read_apart():
    terms = deal_terms.parse(SAIL)
    assert terms["upfront"] == 785e6
    assert terms["equity"] == 465e6
    assert terms["milestones"] == 140e6
    assert terms["option"] == 2.58e9


def test_the_equity_is_inside_the_upfront_not_added_to_it():
    """"total initial payments of $785 million, including a $465 million equity
    investment". Summing them would report 1.25bn of cash that does not exist."""
    terms = deal_terms.parse(SAIL)
    assert terms["upfront"] > terms["equity"]
    assert deal_terms.headline(terms) == 2.58e9      # the option, not a sum


def test_an_option_price_is_not_an_acquisition_price():
    """"an exclusive option to acquire Sail for $2.58 billion" reads as a purchase to any
    rule keyed on the word "for", and it is a purchase that may never happen."""
    assert deal_terms.parse(SAIL)["total"] is None


def test_a_plain_cash_acquisition_reads_as_a_total():
    terms = deal_terms.parse(FIREFLY)
    assert terms["total"] == 1e9
    assert terms["option"] is None
    assert deal_terms.headline(terms) == 1e9


def test_the_summary_reads_in_the_order_an_analyst_reads_it():
    assert deal_terms.summary(deal_terms.parse(SAIL)) == (
        "$785m upfront, $465m equity, $140m milestones, $2.58bn option to acquire")


def test_the_evidence_is_the_sentence_the_figures_came_from():
    assert "total initial payments" in deal_terms.parse(SAIL)["evidence"]


def test_a_per_share_price_is_not_a_deal_term():
    """A tender offer states a price per share and a total. Only one of them is the size
    of the deal."""
    text = ("We commenced a tender offer to purchase all outstanding shares at $72.50 per "
            "share in cash, valuing the transaction at $4.9 billion.")
    terms = deal_terms.parse(text)
    assert terms["total"] == 4.9e9


def test_a_headline_with_no_terms_is_no_terms():
    text = ("Johnson & Johnson Announces Collaboration with Sail Biomedicines to Advance "
            "in vivo CAR-T Programs.")
    terms = deal_terms.parse(text)
    assert deal_terms.headline(terms) is None
    assert deal_terms.summary(terms) == ""


def test_upfront_and_milestones_add_to_the_up_to_figure_when_there_is_no_option():
    """What a press release would print as "up to": what is paid now plus what is
    contingent. Only where the text states no total of its own."""
    text = ("We will pay $50 million upfront and up to $450 million in development and "
            "commercial milestones.")
    terms = deal_terms.parse(text)
    assert deal_terms.headline(terms) == 500e6


def test_empty_text_is_empty_terms():
    terms = deal_terms.parse("")
    assert all(terms[f] is None for f in deal_terms.FIELDS)


# --- whose terms these are --------------------------------------------------------------

# Lilly's first-quarter 2026 release (8-K exhibit 0000059478-26-000043), the sentences the
# old parser read as the terms of four acquisitions. Lilly files no 8-K for an
# acquisition, so this is the only exhibit within days of the headline.
LILLY_Q1 = (
    "Business development activity included the agreements to acquire Orna Therapeutics, "
    "Centessa Pharmaceuticals plc., Kelonia Therapeutics, and Ajax Therapeutics. "
    "Company announces planned Investment Community Meeting for December 7, 2026 "
    "INDIANAPOLIS, April 30, 2026 - Eli Lilly and Company (NYSE: LLY) today announced its "
    "financial results for the first quarter of 2026 and provided updated 2026 financial "
    "guidance. \"2026 is off to a strong start, we delivered 56% revenue growth in the "
    "first quarter and raised our full-year revenue guidance by $2 billion,\" said David "
    "A. Ricks, Lilly chair and CEO. A key milestone was the U.S. FDA approval of Foundayo. "
    "Revenue included a $200.0 million sales-based milestone payment for Jardiance "
    "associated with the company's collaboration with Boehringer Ingelheim.")


def test_a_figure_counts_only_where_the_party_is_named_beside_it():
    """An earnings release names the target in a bullet and states its own milestones
    and guidance pages later. Four Lilly acquisitions carried the $2 billion guidance
    raise as their milestones until this rule."""
    for party in ("Ajax Therapeutics", "Orna Therapeutics", "Centessa Pharmaceuticals"):
        terms = deal_terms.parse(LILLY_Q1, party=party)
        assert deal_terms.headline(terms) is None, party


def test_the_party_may_be_named_in_the_sentence_before_the_figures():
    """A release states the party and then what it pays: "option to acquire Sail for
    $2.58 billion. Under the terms of the agreements, ... $785 million"."""
    terms = deal_terms.parse(SAIL, party="Sail Biomedicines")
    assert terms["upfront"] == 785e6 and terms["option"] == 2.58e9
    # and the evidence then names the party, so a later check can hold it to that
    assert "sail" in terms["evidence"].lower()


def test_a_party_with_no_name_of_its_own_binds_nothing():
    assert deal_terms.party_words("Therapeutics, Inc.") == []
    assert deal_terms.headline(deal_terms.parse(SAIL, party="Therapeutics, Inc.")) is None


def test_without_a_party_the_parser_reads_as_before():
    assert deal_terms.headline(deal_terms.parse(LILLY_Q1)) == 200e6
