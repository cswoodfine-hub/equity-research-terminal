"""The merged FDA regulatory stream over a seeded DB, no network."""

import datetime as dt

import db
import regulatory
import seed


def _seed(tmp_path):
    db_file = tmp_path / "test.db"
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    cid = conn.execute("SELECT id FROM companies WHERE ticker='LLY'").fetchone()[0]
    # One scheduled panel vote ahead, one already held.
    conn.execute("INSERT INTO adcomm_meetings (meeting_key, committee, meeting_date,"
                 " application_label, product, company_id) VALUES"
                 " ('k1', 'Oncologic Drugs Advisory Committee', '2026-09-01',"
                 " 'BLA 125827', 'Testbio', ?)", (cid,))
    conn.execute("INSERT INTO adcomm_meetings (meeting_key, committee, meeting_date,"
                 " application_label, product) VALUES"
                 " ('k2', 'Cellular, Tissue, and Gene Therapies Advisory Committee',"
                 " '2026-06-01', 'BLA 125842', 'Otherdrug')")
    # Announcements: a matched safety item and an unmatched press item on the same day,
    # so the matched-first tiebreak is exercised.
    conn.execute("INSERT INTO news (company_id, source, title, url, published_at)"
                 " VALUES (?, 'fda_safety', 'Safety communication', 'u1', '2026-07-20')",
                 (cid,))
    conn.execute("INSERT INTO news (source, title, url, published_at)"
                 " VALUES ('fda_safety', 'Unmatched safety notice', 'u2', '2026-07-20')")
    conn.execute("INSERT INTO news (source, title, url, published_at)"
                 " VALUES ('fda_press', 'Agency press item', 'u5', '2026-07-19')")
    conn.execute("INSERT INTO news (source, title, url, published_at)"
                 " VALUES ('fda_drugs', 'Drug approval note', 'u3', '2026-07-10')")
    # A non-FDA news row must not leak into the regulatory stream.
    conn.execute("INSERT INTO news (source, title, url, published_at)"
                 " VALUES ('rss_company', 'Company blog post', 'u4', '2026-07-21')")
    conn.commit()
    conn.close()
    return db_file


def test_stream_splits_ahead_from_behind(tmp_path):
    db_file = _seed(tmp_path)
    out = regulatory.build(db_file, today=dt.date(2026, 7, 27))

    # Only the future meeting is ahead; the held one falls back with the announcements.
    assert [i["title"] for i in out["ahead"]] == ["Testbio"]
    assert out["ahead"][0]["kind"] == "panel"
    assert out["ahead"][0]["ticker"] == "LLY"
    assert out["ahead"][0]["detail"] == "Oncologic Drugs"     # boilerplate stripped

    behind_titles = [i["title"] for i in out["behind"]]
    assert "Otherdrug" in behind_titles                       # past meeting
    assert "Company blog post" not in behind_titles           # non-FDA source excluded


def test_kinds_and_matched_first_within_a_day(tmp_path):
    db_file = _seed(tmp_path)
    out = regulatory.build(db_file, today=dt.date(2026, 7, 27))
    kinds = {i["title"]: i["kind"] for i in out["behind"]}
    assert kinds["Safety communication"] == "safety"
    assert kinds["Unmatched safety notice"] == "safety"

    # Both fell on 2026-07-20; the company-matched one leads.
    same_day = [i for i in out["behind"] if i["date"] == "2026-07-20"]
    assert [i["ticker"] for i in same_day] == ["LLY", None]
    # Newest first overall.
    dates = [i["date"] for i in out["behind"]]
    assert dates == sorted(dates, reverse=True)


def test_counts_summarise_the_stream(tmp_path):
    db_file = _seed(tmp_path)
    counts = regulatory.build(db_file, today=dt.date(2026, 7, 27))["counts"]
    assert counts["ahead"] == 1
    assert counts["safety"] == 2           # one matched, one not; both are events
    assert counts["matched"] == 2          # the scheduled panel and the safety item


# --- what counts as an event -----------------------------------------------------------

def test_a_standing_resource_page_is_not_an_event():
    """The feeds that carry a panel vote also carry the FDA's own website upkeep. Of 83
    items over four months, 69 were pages like these republished."""
    for title in ("Withdrawn and Expired Guidances | Drugs",
                  "Over-The-Counter Monograph Drug User Fee Program (OMUFA)",
                  "Patient Listening Session Summaries",
                  "FDA's Labeling Resources for Human Prescription Drugs",
                  "Upcoming Product-Specific Guidances for Generic Drug Product Development",
                  "Untitled Letters"):
        assert not regulatory.is_event({"kind": "drugs", "title": title, "ticker": None})


def test_a_resource_page_matched_to_a_company_is_still_not_an_event():
    """"New Approach Methodologies (NAMs)" was matched to Revolution Medicines. A match on
    a page like that is a false match, not a signal."""
    assert not regulatory.is_event(
        {"kind": "drugs", "title": "New Approach Methodologies (NAMs)", "ticker": "RVMD"})


def test_an_announcement_naming_a_covered_company_is_an_event():
    assert regulatory.is_event(
        {"kind": "press", "ticker": "VRTX",
         "title": "FDA Approves First Gene Therapy for Young Children with Sickle Cell"})


def test_a_scheduled_panel_vote_is_always_an_event():
    """The one firm regulatory date free data gives, so it is kept even unmatched."""
    assert regulatory.is_event(
        {"kind": "panel", "ticker": None, "title": "Vusolimogene Oderparepvec"})


def test_a_device_recall_outside_the_universe_is_not_this_terminal_s_subject():
    """MedWatch is mostly hardware. This universe is large-cap pharma."""
    assert not regulatory.is_event(
        {"kind": "safety", "ticker": None,
         "title": "Early Alert: Ventilator Issue from Resmed"})


def test_a_device_recall_at_a_covered_company_is_kept():
    """J&J owns Abiomed, so its heart pump recall is a J&J event."""
    assert regulatory.is_event(
        {"kind": "safety", "ticker": "JNJ",
         "title": "Heart Pump Recall: Abiomed Removes Impella CP Sets"})


def test_a_drug_safety_communication_is_an_event_even_unmatched():
    assert regulatory.is_event(
        {"kind": "safety", "ticker": None,
         "title": "FDA warns of serious liver injury with high-dose acetaminophen"})


def test_an_unmatched_press_item_is_not_an_event():
    """Agency context with no company and no safety finding is not something that
    happened to anyone this terminal covers."""
    assert not regulatory.is_event(
        {"kind": "press", "ticker": None, "title": "FDA Names New Deputy Commissioner"})


def test_agency_housekeeping_is_counted_rather_than_listed(tmp_path):
    """An unmatched press item and an unmatched drugs item are agency context, not events.
    The count says they were read, so a short stream reads as filtered not as empty."""
    db_file = _seed(tmp_path)
    out = regulatory.build(db_file, today=dt.date(2026, 7, 27))
    titles = [i["title"] for i in out["behind"]]
    assert "Agency press item" not in titles
    assert "Drug approval note" not in titles
    assert out["counts"]["housekeeping"] == 2
