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
                 " VALUES ('fda_press', 'Agency press item', 'u2', '2026-07-20')")
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
    assert kinds["Agency press item"] == "press"
    assert kinds["Drug approval note"] == "drugs"

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
    assert counts["safety"] == 1
    assert counts["matched"] == 2          # the scheduled panel and the safety item
