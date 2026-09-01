"""A biosimilar date the filer states sets the LOE; an orphan date on one indication
does not outrun it.

Keytruda's Purple Book entries are a 12-year reference exclusivity to 2026 and a 2031
orphan exclusivity on its latest indication. Merck's 10-K says biosimilar competition
could begin in December 2028 when the compound patent expires. The rule took the later
of floor and latest exclusivity, so the molecule was protected to 2031 by a date that
protects one indication.
"""

import loe


def test_a_disclosed_date_beats_a_later_orphan_exclusivity():
    date, basis = loe.effective("2031-01-25", "orphan exclusivity", 2026,
                                disclosed=("2028-12-31", "10-K disclosure"))
    assert date == "2028-12-31"
    assert basis == "10-K disclosure"


def test_the_statutory_floor_still_holds_a_disclosure_up():
    """A filer cannot lose exclusivity before the law lets it."""
    date, basis = loe.effective("2027-01-01", "orphan exclusivity", 2030,
                                disclosed=("2028-12-31", "10-K disclosure"))
    assert date == "2030-12-31"
    assert basis.startswith("statutory floor")


def test_without_a_disclosure_the_old_rule_stands():
    assert loe.effective("2031-01-25", "orphan exclusivity", 2026) == (
        "2031-01-25", "orphan exclusivity")
    assert loe.effective("2031-01-25", "orphan exclusivity", 2026, disclosed=None) == (
        "2031-01-25", "orphan exclusivity")
    assert loe.effective("2031-01-25", "orphan exclusivity", 2026,
                         disclosed=(None, None)) == ("2031-01-25", "orphan exclusivity")


def test_a_substance_patent_yields_to_a_disclosure_too():
    date, basis = loe.effective("2035-01-01", "patent", None, substance_max="2033-06-01",
                                disclosed=("2030-12-31", "10-K disclosure"))
    assert date == "2030-12-31"
