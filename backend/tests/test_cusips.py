"""The CUSIP register, guarded.

`data/cusips.csv` decides whose holders the book shows under each company's name. A
wrong row is not a missing number, it is another company's shareholders presented as
this one's, and nothing downstream can tell. So the file itself is tested: every check
digit, every ticker, and that each company in the universe is either on the register
or left out for a stated reason. Adding a company to the seed fails this until one of
the two is decided.
"""

from __future__ import annotations

import csv

import cusips

# What the SEC's official list calls a share or a depositary share. A row whose class
# is anything else (a note, a warrant, a right, a unit) is not what a holder holds.
_EQUITY_CLASSES = {"COM", "COM NEW", "COM SHS", "SHS", "ORD", "ORDINARY SHARES",
                   "NAMEN AKT", "ADR", "SPONSORED ADR", "SPONSORED ADS", "SPON ADS"}


def _universe() -> set:
    seed = cusips.DATA / "companies_seed.csv"
    with seed.open(newline="", encoding="utf-8") as handle:
        return {row["ticker"].strip().upper() for row in csv.DictReader(handle)}


def test_the_check_digit_is_the_standards():
    # Lilly, AstraZeneca's ordinary share (a letter first), Dyne (a letter inside).
    for cusip in ("532457108", "G0593M107", "26818M108", "00287Y109"):
        assert cusips.valid_cusip(cusip), cusip
    assert cusips.valid_cusip(" 532457108 ") and cusips.valid_cusip("g0593m107")
    # One digit off, two characters swapped, too short, a letter where the check goes.
    for cusip in ("532457109", "523457108", "53245710", "53245710X", "", None):
        assert not cusips.valid_cusip(cusip), cusip
    # The official list's labels for a company's calls and puts are not securities.
    assert not cusips.valid_cusip("532457908") and not cusips.valid_cusip("532457958")


def test_every_row_of_the_register_is_usable():
    assert cusips.problems() == []
    rows = cusips.load()
    assert rows, "the register is empty"
    for row in rows:
        assert cusips.valid_cusip(row["cusip"]), row
        assert row["class_title"] in _EQUITY_CLASSES, row
        assert row["source"] and row["note"], row


def test_a_cusip_belongs_to_one_company():
    seen = [row["cusip"] for row in cusips.load()]
    assert len(seen) == len(set(seen))
    assert cusips.by_cusip()["532457108"] == "LLY"


def test_every_company_is_on_the_register_or_left_out_for_a_reason():
    universe = _universe()
    on_register = {row["ticker"] for row in cusips.load()}
    left_out = cusips.left_out()
    assert on_register <= universe, on_register - universe
    assert set(left_out) <= universe, set(left_out) - universe
    assert not on_register & set(left_out)
    assert on_register | set(left_out) == universe, universe - on_register - set(left_out)
    assert all(len(reason) > 40 for reason in left_out.values())
    # The four with no free data: two depositary receipts that trade over the counter
    # and two shares that left the official list.
    assert set(left_out) == {"ROG", "BAYN", "SGMOQ", "ADAPY"}


def test_names_that_share_a_word_are_not_the_company():
    # Viking Holdings is the cruise line and Vertex Inc the tax software company.
    # Merck's pre-2009 CUSIP and AstraZeneca's ended ADR are stale identifiers.
    register = cusips.by_cusip()
    for wrong in ("G93A5A101", "92538J106", "589331107", "046353108"):
        assert wrong not in register
    assert register["92686J106"] == "VKTX" and register["92532F100"] == "VRTX"


def test_a_depositary_class_is_told_from_a_share():
    assert cusips.is_depositary("SPONSORED ADR") and cusips.is_depositary("SPON ADS")
    assert cusips.is_depositary("ADR")
    assert not cusips.is_depositary("COM") and not cusips.is_depositary("ORD")
    assert [row["class_title"] for row in cusips.for_ticker("nvo")] == ["ADR"]
    # AstraZeneca has been an ordinary share on the NYSE since February 2026.
    assert [row["class_title"] for row in cusips.for_ticker("AZN")] == ["ORD"]


def test_a_changed_cusip_is_two_rows_under_one_ticker():
    assert [row["cusip"] for row in cusips.for_ticker("WVE")] == ["Y95308105",
                                                                  "94352A104"]


def test_a_bad_row_is_refused_and_said(tmp_path):
    register = tmp_path / "cusips.csv"
    register.write_text(
        "# a comment line is skipped\n"
        "ticker,cusip,class_title,source,note\n"
        "LLY,532457108,COM,test,\n"
        "DYN,26818M109,COM,test,the check digit is wrong\n"
        "MRK,532457108,COM,test,Lilly's CUSIP again\n"
        ",00287Y109,COM,test,no ticker\n", encoding="utf-8")
    assert cusips.load(register) == [{"ticker": "LLY", "cusip": "532457108",
                                      "class_title": "COM", "source": "test",
                                      "note": None}]
    problems = cusips.problems(register)
    assert len(problems) == 3
    assert "26818M109" in problems[0] and "already LLY's" in problems[1]
    assert cusips.load(tmp_path / "missing.csv") == []
