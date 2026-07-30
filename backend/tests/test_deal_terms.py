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
