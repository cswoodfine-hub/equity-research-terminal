"""Which filings the PDUFA extractor is willing to read.

The gate used to be a regular expression over the filing title, which only a domestic
8-K reliably carries. A foreign private issuer files a 6-K whose title is the form name,
so every one was discarded unread: of 429 big pharma 8-K and 6-K filings in a 400 day
window only 35 passed, and AstraZeneca, GSK, Novo, Novartis and Sanofi passed none.
"""

import pdufa


def test_an_untitled_6k_is_read_because_its_title_settles_nothing():
    for title in ("6-K", "FORM 6-K", "form 6-k", "", None, "6-K:"):
        assert pdufa.worth_reading("6-K", title) is True, title


def test_a_titled_6k_about_something_else_is_still_refused():
    for title in ("TOTAL VOTING RIGHTS", "DIRECTOR/PDMR SHAREHOLDING",
                  "TRANSACTION IN OWN SHARES", "FILING OF FORM 20-F WITH SEC"):
        assert pdufa.worth_reading("6-K", title) is False, title


def test_a_title_that_states_a_regulatory_event_is_read_whatever_the_form():
    """The all-capitals 6-K cover is how a foreign filer announces one."""
    assert pdufa.worth_reading("6-K", "BEPIROVIRSEN PRIORITY REVIEW US FILING ACCEPTANCE")
    assert pdufa.worth_reading("8-K", "Accepted the biologics license application")
    assert pdufa.worth_reading("6-K", "PDUFA date set for our lead programme")


def test_the_item_descriptions_the_old_gate_read_are_all_still_read():
    for title in ("Other events", "Material agreement signed, Other events",
                  "Regulation FD Disclosure", "Material impairment",
                  "Entry into a Material Definitive Agreement"):
        assert pdufa.worth_reading("8-K", title) is True, title


def test_a_positive_signal_is_never_overridden_by_the_refusal_list():
    """An 8-K titled "Results of operations, Other events" carries both. Refusing it on
    the first half is how a widened gate would quietly lose what the narrow one read."""
    assert pdufa.worth_reading("8-K", "Results of operations, Other events") is True
    assert pdufa.worth_reading("6-K", "Annual report and PDUFA date confirmed") is True


def test_an_8k_with_no_useful_title_is_not_read():
    """The untitled door is for 6-Ks only. A domestic 8-K always carries item text, so a
    blank one is a gap in the data rather than a filing worth fetching."""
    assert pdufa.worth_reading("8-K", "8-K") is False
    assert pdufa.worth_reading("8-K", "Results of operations") is False
