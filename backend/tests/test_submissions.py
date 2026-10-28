"""Regulatory submissions announced in the news, recorded as dated catalysts.

The rule under test is the one auto_resolve already follows: a plan to file is not a
filing. The regulatory feed carries "remains on track to submit an NDA in the first half
of 2027" beside "submits New Drug Application", and recording the first as a thing that
happened would put a guided milestone on the calendar as history.
"""

import datetime as dt

import db
import submissions as S


def _book(tmp_path, press, assets=(("Omvoh", "mirikizumab"),)):
    path = str(tmp_path / "s.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (id, ticker, name) VALUES (1,'LLY','Lilly')")
    for n, (brand, generic) in enumerate(assets, start=1):
        conn.execute("INSERT INTO assets (id, owner_company_id, brand_name,"
                     " generic_name, modality) VALUES (?, 1, ?, ?, 'small molecule')",
                     (n, brand, generic))
    today = dt.date.today().isoformat()
    for url, headline, kind in press:
        conn.execute(
            """INSERT INTO changes (entity_type, entity_key, field, new_value,
                                    change_type, significance, detected_at)
               VALUES ('company', ?, 'press release', ?, ?, 'high', ?)""",
            (f"LLY|{url}", headline, kind, f"{today} 09:00:00"))
    conn.commit(); conn.close()
    return path


def _rows(path):
    conn = db.get_connection(path)
    out = [dict(r) for r in conn.execute(
        "SELECT * FROM catalysts WHERE catalyst_type = ? ORDER BY id",
        (S.CATALYST_TYPE,))]
    conn.close()
    return out


# --- what the words say --------------------------------------------------------------

def test_a_plan_to_file_is_not_a_filing():
    for line in ("Lilly remains on track to submit an NDA in the first half of 2027",
                 "Lilly plans to file a BLA for mirikizumab in 2027",
                 "Lilly expects to submit a BLA by year end",
                 "Lilly intends to submit a New Drug Application next year"):
        assert S.classify(line) == (None, None, None), line


def test_a_filing_is_recorded_with_the_application_it_names():
    assert S.classify("Lilly submits New Drug Application for Omvoh")[:2] == ("submitted", "NDA")
    assert S.classify("Lilly completes submission of sNDA for Omvoh")[:2] == ("submitted", "sNDA")
    assert S.classify(
        "Lilly announces submission of a Marketing Authorisation Application"
    )[:2] == ("submitted", "MAA")


def test_an_acceptance_is_its_own_stage():
    """The FDA clock starts at acceptance, not at receipt, so the two are not one event."""
    assert S.classify("FDA accepts Biologics License Application for Omvoh")[:2] == (
        "accepted", "BLA")


def test_a_headline_about_neither_is_not_classified():
    assert S.classify("Phase 3 results published in NEJM") == (None, None, None)
    assert S.classify("") == (None, None, None)
    assert S.classify(None) == (None, None, None)


# --- what reaches the calendar -------------------------------------------------------

def test_an_announced_submission_becomes_a_dated_catalyst(tmp_path):
    path = _book(tmp_path, [("u1", "Lilly submits New Drug Application for Omvoh",
                             "press_regulatory")])
    assert S.derive(path) == {"written": 1, "updated": 0, "skipped": 0}
    row = _rows(path)[0]
    assert row["catalyst_type"] == "regulatory submission"
    assert row["title"] == "Omvoh NDA submitted"
    assert row["asset_id"] == 1, "the asset the headline names"
    assert row["is_curated"] == 0
    assert row["date_confidence"] == "confirmed", "the day it was announced is known"
    assert row["expected_date"] == dt.date.today().isoformat()
    assert "matched" in row["description"], "the words that decided it travel with it"


def test_a_plan_never_reaches_the_calendar(tmp_path):
    path = _book(tmp_path, [("u1", "Lilly remains on track to submit an NDA for Omvoh",
                             "press_regulatory")])
    assert S.derive(path)["written"] == 0
    assert _rows(path) == []


def test_the_press_url_is_the_row_s_identity(tmp_path):
    """A second run revises the row rather than adding a second copy of the same event."""
    path = _book(tmp_path, [("u1", "Lilly submits New Drug Application for Omvoh",
                             "press_regulatory")])
    S.derive(path)
    again = S.derive(path)
    assert again == {"written": 0, "updated": 1, "skipped": 0}
    assert len(_rows(path)) == 1


def test_a_row_the_analyst_accepted_is_left_alone(tmp_path):
    """Their judgement outranks the derivation, the rule derive_readouts follows."""
    path = _book(tmp_path, [("u1", "Lilly submits New Drug Application for Omvoh",
                             "press_regulatory")])
    S.derive(path)
    conn = db.get_connection(path)
    conn.execute("UPDATE catalysts SET is_curated = 1, title = 'by hand'")
    conn.commit(); conn.close()
    assert S.derive(path) == {"written": 0, "updated": 0, "skipped": 1}
    assert _rows(path)[0]["title"] == "by hand"


def test_a_headline_naming_two_assets_names_neither(tmp_path):
    """One of them filed and the row cannot say which, so it carries no asset rather
    than the first one matched."""
    path = _book(tmp_path,
                 [("u1", "Lilly submits New Drug Application for Omvoh and Taltz",
                   "press_regulatory")],
                 assets=(("Omvoh", "mirikizumab"), ("Taltz", "ixekizumab")))
    S.derive(path)
    assert _rows(path)[0]["asset_id"] is None
    assert _rows(path)[0]["title"] == "NDA submitted"


def test_a_headline_naming_no_asset_still_records_the_event(tmp_path):
    path = _book(tmp_path, [("u1", "Lilly submits a New Drug Application to the FDA",
                             "press_regulatory")])
    S.derive(path)
    assert _rows(path)[0]["asset_id"] is None


def test_a_ticker_the_book_does_not_carry_is_skipped(tmp_path):
    path = _book(tmp_path, [])
    conn = db.get_connection(path)
    conn.execute("""INSERT INTO changes (entity_type, entity_key, field, new_value,
                        change_type, significance, detected_at)
                    VALUES ('company', 'ZZZZ|u9', 'press release',
                        'Zed submits New Drug Application', 'press_regulatory', 'high',
                        ?)""", (f"{dt.date.today().isoformat()} 09:00:00",))
    conn.commit(); conn.close()
    assert S.derive(path) == {"written": 0, "updated": 0, "skipped": 1}
