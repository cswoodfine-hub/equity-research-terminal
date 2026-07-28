"""Item 5.02 transitions, and the six ways a job title lies.

Every sentence in the negative tests is real, taken from the filing that produced a
false positive before the guard it now tests existed. That is deliberate: a job title
appears in almost every Item 5.02 filing and means a transition in about one in four, so
these are the tests that matter. A missed transition costs recall; a false CEO departure
gets acted on.
"""

import pytest

import leadership as L


# --- true positives, from real filings -----------------------------------------------

def test_reads_a_chief_executive_retirement():
    """Sarepta, February 2026. The one real CEO transition in a 60-filing corpus."""
    found = L.extract(
        "Item 5.02 Departure of Directors or Certain Officers. On February 25, 2026, "
        "Douglas Ingram notified Sarepta Therapeutics, Inc. (the \"Company\") of his "
        "decision to retire as Chief Executive Officer by the end of 2026.")
    assert [(e["role"], e["kind"]) for e in found] == [("Chief executive", "departure")]


def test_reads_a_step_down():
    """Pfizer, June 2026."""
    found = L.extract(
        "Item 5.02 On June 16, 2026, Dave Denton notified Pfizer Inc. (the \"Company\") "
        "that he will step down from his current position as Chief Financial Officer "
        "effective August 15, 2026.")
    assert ("Chief financial", "departure") in [(e["role"], e["kind"]) for e in found]


def test_one_sentence_can_report_a_swap():
    """A succession names an arrival and a departure at once; both are the news."""
    found = {(e["role"], e["kind"]) for e in L.extract(
        "Item 5.02 Dr. Severino will succeed Douglas Ingram as Chief Executive Officer. "
        "Mr. Ingram will depart from his position as Chief Executive Officer as of the "
        "Effective Date.")}
    assert ("Chief executive", "appointment") in found
    assert ("Chief executive", "departure") in found


# --- the guards, each named after the filing that needed it ---------------------------

def test_a_new_directors_biography_is_not_a_transition():
    """Ionis. An incoming director's history names every company they have run."""
    assert L.extract(
        "Item 5.02 The Board appointed Dr. Hantson as a director. He served as chief "
        "executive officer and board member of Alexion from 2017-2021, prior to its "
        "acquisition by AstraZeneca.") == []


def test_a_role_at_another_company_is_not_a_transition():
    """Vertex. The company's own CFO leaving to run finance elsewhere is reported in a
    sentence that names the other company's job, and reading it books their hire here."""
    assert L.extract(
        "Item 5.02 Mr. Upadhyay has recently been named the forthcoming Chief Financial "
        "Officer of Incyte Corporation.") == []


def test_an_equity_award_is_not_a_transition():
    """Alnylam. Item 5.02(e) is compensatory arrangements, same item number."""
    assert L.extract(
        "Item 5.02 The Compensation Committee approved an award granted under the "
        "Company's Second Amended and Restated 2018 Stock Incentive Plan to Yvonne "
        "Greenstreet, M.D., M.B.A., the Company's Chief Executive Officer.") == []


def test_a_severance_schedule_is_not_a_transition():
    """Axsome. A plan document that lists the CEO as a tier of participant."""
    assert L.extract(
        "Item 5.02 Under the Severance Plan, a Participant is designated by the "
        "Committee as a Tier 1 Participant (which includes the Chief Executive "
        "Officer).") == []


def test_a_reporting_line_is_not_a_transition():
    """Amgen. The CEO named here is the one who is staying."""
    assert L.extract(
        "Item 5.02 Mr. Dittrich will report to Robert A. Bradway, Chairman and Chief "
        "Executive Officer.") == []


def test_forward_looking_boilerplate_is_not_a_transition():
    """Revolution Medicines. The safe-harbour paragraph restates the event as a risk."""
    assert L.extract(
        "Item 5.02 Forward-Looking Statements This Current Report on Form 8-K includes "
        "forward-looking statements within the meaning of the federal securities laws, "
        "including statements regarding Dr. Kelsey's planned retirement as Chief "
        "Executive Officer.") == []


def test_a_vice_president_is_not_the_president():
    """Amgen. "Executive Vice President" read as the President leaving."""
    assert L.extract(
        "Item 5.02 Dr. Reese will remain employed as an Executive Vice President until "
        "his retirement on June 30, 2026.") == []


def test_an_existing_title_in_apposition_is_not_the_new_role():
    """Korro. The CEO is appointed interim CFO; he is not appointed CEO.

    The roles before the comma identify the man. The role after "as" is the event.
    """
    found = {(e["role"], e["kind"]) for e in L.extract(
        "Item 5.02 In light of Mr. Agarwal's resignation, the Board appointed Dr. Ram "
        "Aiyar, President and Chief Executive Officer, to serve as Korro's interim "
        "Chief Financial Officer.")}
    assert found == {("Chief financial", "appointment")}


def test_the_senior_role_absorbing_duties_is_not_leaving():
    """Voyager. One sentence, two people: the CMO resigns and the CEO covers.

    Pairing each role with its nearest verb is what separates them; taking the most
    senior role in the sentence reported the chief executive as departing.
    """
    found = {(e["role"], e["kind"]) for e in L.extract(
        "Item 5.02 Following the resignation of the Chief Medical Officer, Alfred "
        "Sandrock, Jr., M.D., Ph.D., the Company's current President and Chief "
        "Executive Officer, has agreed to assume key responsibilities on an interim "
        "basis.")}
    assert ("Chief executive", "departure") not in found


# --- mechanics -----------------------------------------------------------------------

def test_item_body_stops_at_the_next_item():
    body = L.item_body("Item 5.02 the officer resigned. Item 9.01 Exhibit 99.1")
    assert "resigned" in body and "Exhibit" not in body


def test_item_body_falls_back_to_the_whole_filing():
    """Some filers put the heading only in an exhibit. The guards do the work there."""
    assert "resigned" in L.item_body("A press release. The officer resigned.")


def test_sentences_do_not_break_on_abbreviations():
    parts = L.sentences("Alfred Sandrock, Jr., M.D., Ph.D. resigned from Acme Inc. today.")
    assert len(parts) == 1


@pytest.mark.parametrize("role,kind,expected", [
    ("Chief executive", L.DEPARTURE, "high"),
    ("Chief financial", L.DEPARTURE, "high"),
    ("Chief executive", L.APPOINTMENT, "medium"),
    ("Chief legal", L.APPOINTMENT, "low"),
])
def test_significance(role, kind, expected):
    assert L.significance(role, kind) == expected


def test_detect_marks_read_filings_so_they_are_not_downloaded_twice(tmp_path):
    """EDGAR is rate limited and there are hundreds of these filings."""
    import db

    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('ACME', 'Acme Inc')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
        " VALUES (?, '8-K', date('now'), '0001', 'Director or officer change',"
        "         'http://example.test/a.htm')", (cid,))
    conn.commit()
    conn.close()

    calls = []

    def fake_get(url):
        calls.append(url)
        return ("Item 5.02 On June 1, 2026, Jane Roe notified Acme Inc. of her decision "
                "to resign as Chief Financial Officer.")

    first = L.detect(path, get=fake_get)
    assert first["written"] == 1 and len(calls) == 1

    second = L.detect(path, get=fake_get)
    assert second["read"] == 0 and len(calls) == 1, "filing was downloaded twice"


def test_detect_records_a_filing_that_reports_nothing(tmp_path):
    """A routine director election must also be marked read, or it is re-fetched daily."""
    import db

    path = str(tmp_path / "t.db")
    db.init(path)
    conn = db.get_connection(path)
    conn.execute("INSERT INTO companies (ticker, name) VALUES ('ACME', 'Acme Inc')")
    cid = conn.execute("SELECT id FROM companies").fetchone()[0]
    conn.execute(
        "INSERT INTO filings (company_id, form_type, filed_date, accession, title, url)"
        " VALUES (?, '8-K', date('now'), '0002', 'Director or officer change',"
        "         'http://example.test/b.htm')", (cid,))
    conn.commit()
    conn.close()

    result = L.detect(path, get=lambda url: (
        "Item 5.02 The Board increased its size to 13 members and appointed "
        "Victor Dzau, M.D., to serve as a member of the Board."))
    assert result["written"] == 0
    assert L.detect(path, get=lambda url: "")["read"] == 0


def test_cease_to_serve_is_a_departure_not_an_arrival():
    """Kyverna. "will cease to serve as Chief Technology Officer" ends in the same words
    as an appointment and means the opposite, so one filing reported both."""
    found = {(e["role"], e["kind"]) for e in L.extract(
        "Item 5.02 On January 29, 2026, Karen Walker notified Kyverna Therapeutics, "
        "Inc. that she will cease to serve as the Company's Chief Technology Officer.")}
    assert found == {("Chief technology", "departure")}
