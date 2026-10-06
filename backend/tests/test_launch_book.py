"""Book guards for the launch floor: on the built database every reading is well formed,
says what it rests on, is written in house style and writes nothing."""

import re

import launch_timing as L

BANNED = ("additionally", "highlight", "underscore", "pivotal", "showcase", "testament")


def _all(book):
    out = []
    for company in book.execute("SELECT id, ticker FROM companies ORDER BY ticker"):
        out.extend(L.for_company(book, company["id"]))
    return out


def test_every_reading_is_well_formed_and_says_what_it_rests_on(book):
    before = book.total_changes
    rows = _all(book)
    assert book.total_changes == before
    assert rows, "no unmarketed asset carries a seeded start year"
    for row in rows:
        assert row["status"] in L.STATUSES, row
        assert row["flag"] == L.FLAGS.get(row["status"]), row
        text = row["message"]
        assert text and (text[0].isupper() or text[0].isdigit()), row
        assert "—" not in text and "–" not in text, text
        assert not any(re.search(rf"\b{w}\b", text, re.I) for w in BANNED), text
        if row["status"] in ("before_floor", "before_floor_cited", "part_year", "clear"):
            evidence = row["evidence"]
            assert evidence["kind"] in ("accepted", "readout", "registry"), row
            assert row["decision_date"] and row["first_possible_year"], row
            assert row["first_full_year"] == row["first_possible_year"] + 1, row
            if evidence["kind"] != "accepted":
                assert row["clock"]["applied"] and row["clock"]["source"], row
            assert (row["seed_year"] < row["first_possible_year"]) == (
                row["status"] in ("before_floor", "before_floor_cited")), row
            # Amber only where the floor rests on the registry alone and the seed cites
            # what the database lacks; on a filing or readout on file it stays red.
            assert (row["status"] == "before_floor_cited") == bool(
                row["status"] in ("before_floor", "before_floor_cited")
                and row["seed_basis"]["cites"] and evidence["kind"] == "registry"), row


def test_a_flag_is_never_raised_without_a_dated_study_or_application(book):
    for row in _all(book):
        if row["flag"]:
            evidence = row["evidence"]
            assert L.parse_date(evidence["date"]) is not None, row
            if evidence["kind"] == "registry":
                assert evidence["nct_id"] and evidence["source_url"].endswith(
                    evidence["nct_id"]), row
