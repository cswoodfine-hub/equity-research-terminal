"""Deals the press reports are being discussed, which nobody has announced.

The lane exists for one story a year: two large caps confirmed to be in merger talks,
which moves both on the day and which the announced-deals extractor deliberately throws
away. Everything short of that has to keep being thrown away, so most of these tests are
about what does not qualify.
"""

from fetchers import deals_news

NAMES = {"AstraZeneca", "AZN"}


def test_a_merger_at_hundreds_of_billions_is_kept():
    got = deals_news.parse_reported(
        "AstraZeneca in merger talks with Bristol Myers Squibb in $400 billion deal"
        " - Reuters", NAMES)
    assert got["deal_type"] == "merger"
    assert got["counterparty"] == "Bristol Myers Squibb"
    assert got["reported_usd"] == 400e9
    assert got["reported_value"] == "$400 billion"
    # The headline verbatim, minus the publisher Google appends, because a report is
    # worth the words that were written and no summary of them.
    assert got["quote"].endswith("$400 billion deal")
    assert "Reuters" not in got["quote"]


def test_the_publisher_is_kept_beside_the_words():
    assert deals_news._publisher("AZN weighs $30 billion bid - Financial Times") == \
        "Financial Times"
    assert deals_news._publisher("No publisher here") is None


def test_a_report_with_no_figure_is_refused():
    """Without a number there is no way to tell a sector-moving merger from two
    executives having lunch, and this lane is only for the first."""
    assert deals_news.parse_reported(
        "AstraZeneca in merger talks with Bristol Myers Squibb - Reuters", NAMES) is None


def test_a_small_reported_deal_is_refused():
    """Ten billion is the bar. Below it a rumour is a business development story, and a
    lane that took them all would fill with them and bury the one that matters."""
    assert deals_news.parse_reported(
        "AstraZeneca weighs $2 billion bid for Acme Bio - Bloomberg", NAMES) is None
    assert deals_news.parse_reported(
        "AstraZeneca weighs $12 billion bid for Acme Bio - Bloomberg",
        NAMES)["reported_usd"] == 12e9


def test_an_announced_deal_is_not_a_reported_one():
    """A headline that states a deal plainly is the other extractor's job. This one must
    not also claim it, or the same deal would appear twice on the front page, once as a
    fact and once as a rumour."""
    assert deals_news.parse_reported(
        "AstraZeneca agrees to acquire Acme Bio for $15 billion - Reuters",
        NAMES) is None


def test_a_report_naming_no_other_party_is_refused():
    assert deals_news.parse_reported(
        "AstraZeneca explores options worth $20 billion - Reuters", NAMES) is None


def test_the_company_itself_is_never_the_counterparty():
    """"X in talks to be acquired by AstraZeneca" names AstraZeneca after the verb, and
    reading it as the counterparty would have the company in talks with itself."""
    got = deals_news.parse_reported(
        "Acme Bio in merger talks with AstraZeneca worth $25 billion - Reuters", NAMES)
    assert got is None or got["counterparty"] != "AstraZeneca"


def test_value_usd_reads_the_scale():
    assert deals_news.value_usd("worth $400 billion") == 400e9
    assert deals_news.value_usd("worth $750 million") == 750e6
    assert deals_news.value_usd("worth $2.5bn") == 2.5e9
    assert deals_news.value_usd("no figure stated") is None


def test_the_threshold_is_stated_rather_than_scored():
    """It is a number in one place that can be argued with and changed."""
    assert deals_news.REPORTED_MIN_USD == 10e9


def test_a_verb_after_the_subject_is_not_the_counterparty():
    """"AbbVie (ABBV) Approaches $10.9 Billion Acquisition of Apogee" gave Approaches as
    the party, because a headline capitalises the verb that follows the subject."""
    got = deals_news.parse_reported(
        "AbbVie (ABBV) Approaches $10.9 Billion Acquisition of Apogee - GuruFocus",
        {"AbbVie", "ABBV"})
    assert got is None or got["counterparty"] != "Approaches"


def test_a_story_about_who_advised_is_not_a_deal_report():
    """"Kirkland, Wachtell Advise On AbbVie's $63B Merger With Allergan" is trade press
    about law firms, and the names leading it are the advisers."""
    assert deals_news.parse_reported(
        "Kirkland, Wachtell Advise On AbbVie\u2019s $63B Merger With Allergan"
        " - Bloomberg Law News", {"AbbVie", "ABBV"}) is None


def test_the_real_story_still_parses():
    """The one this lane exists for, as the wire actually wrote it."""
    got = deals_news.parse_reported(
        "AstraZeneca held talks with Bristol Myers Squibb on $400 billion megadeal,"
        " source says - Reuters", {"AstraZeneca", "AZN"})
    assert got["counterparty"] == "Bristol Myers Squibb"
    assert got["reported_usd"] == 400e9


def test_a_party_named_before_the_verb_keeps_its_name():
    """"Summit Is in Talks for a $15 Billion Partnership" put the auxiliary inside the
    name."""
    got = deals_news.parse_reported(
        "Summit Is in Talks for $15 Billion Partnership With AstraZeneca - Bloomberg",
        {"AstraZeneca", "AZN"})
    assert got["counterparty"] == "Summit"
