"""Results read out of the companies' own releases: the title gate, the duplicate rule,
and storage. No network; the page and the model reply are supplied."""

import datetime as dt

import db
import press_readouts as PR
import seed
import trial_readouts

_DOC = ("AstraZeneca today announced that the Phase III BALTIC trial of durvalumab met "
        "its primary endpoint, demonstrating a statistically significant improvement in "
        "overall survival. " * 20)
_REPLY = ('{"found": true, "drug": "durvalumab", "phase": 3, "outcome": "positive", '
          '"quote": "the Phase III BALTIC trial of durvalumab met its primary endpoint, '
          'demonstrating a statistically significant improvement in overall survival."}')


def _seed(db_file):
    db.init(db_file)
    seed.load_companies(db_file)
    conn = db.get_connection(db_file)
    azn = conn.execute("SELECT id FROM companies WHERE ticker='AZN'").fetchone()[0]
    recent = (dt.date.today() - dt.timedelta(days=30)).isoformat()

    def news(nid, source, title, url):
        conn.execute("INSERT INTO news (id, company_id, source, title, url, published_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)", (nid, azn, source, title, url, recent))
    news(1, "press_ir", "Imfinzi met its primary endpoint in Phase III BALTIC", "https://x/1")
    news(2, "press_ir", "AstraZeneca appoints a new director", "https://x/2")       # no hint
    news(3, "edgar_8k", "Phase III results", "https://x/3")                        # wrong source
    news(4, "press_page", "Roche presents Phase III data for vamikibart", "https://x/4")
    conn.commit()
    conn.close()
    return azn, recent


def test_candidates_take_releases_with_a_result_in_the_title(tmp_path):
    db_file = tmp_path / "t.db"
    _seed(db_file)
    got = {c["id"] for c in PR.candidates(db_file)}
    assert got == {1, 4}


def test_a_release_is_read_stored_and_read_once(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    azn, recent = _seed(db_file)
    monkeypatch.setattr(PR.llm, "provider", lambda prefer=None: "test")
    monkeypatch.setattr(trial_readouts.llm, "complete",
                        lambda system, user, max_tokens, thinking_budget=None:
                        _REPLY if "BALTIC" in user else '{"found": false}')
    monkeypatch.setattr(PR.time, "sleep", lambda s: None)
    pages = {"https://x/1": _DOC, "https://x/4": "Roche presents Phase III data. " * 60}
    got = PR.extract(db_file, get=pages.__getitem__)
    assert got["read"] == 2 and got["positive"] == 1 and got["duplicate"] == 0
    conn = db.get_connection(db_file)
    row = conn.execute("SELECT drug, phase, outcome, source, event_date, read_from FROM trial_readouts"
                       " WHERE accession = 'news:1'").fetchone()
    assert (row["drug"], row["phase"], row["outcome"], row["source"]) == ("durvalumab", 3, "positive", "press")
    assert row["event_date"] == recent and row["read_from"] == "release"
    assert conn.execute("SELECT outcome FROM trial_readouts WHERE accession = 'news:4'").fetchone()[0] == "none"
    conn.close()
    assert PR.extract(db_file, get=pages.__getitem__)["read"] == 0        # nothing left


def test_a_release_that_restates_a_filing_is_a_duplicate_not_a_second_event(tmp_path, monkeypatch):
    """The 6-K furnished three days later carries the same release. One result, one row
    that counts; the second is kept as a duplicate so it is neither re-read nor matched."""
    db_file = tmp_path / "t.db"
    azn, recent = _seed(db_file)
    conn = db.get_connection(db_file)
    three_days_on = (dt.date.fromisoformat(recent) + dt.timedelta(days=3)).isoformat()
    conn.execute("INSERT INTO trial_readouts (accession, company_id, drug, phase, outcome, event_date)"
                 " VALUES ('0001-26-9', ?, 'Imfinzi (durvalumab)', 3, 'positive', ?)", (azn, three_days_on))
    conn.commit()
    conn.close()
    monkeypatch.setattr(PR.llm, "provider", lambda prefer=None: "test")
    monkeypatch.setattr(trial_readouts.llm, "complete",
                        lambda system, user, max_tokens, thinking_budget=None: _REPLY)
    monkeypatch.setattr(PR.time, "sleep", lambda s: None)
    got = PR.extract(db_file, get=lambda url: _DOC)
    assert got["duplicate"] >= 1
    conn = db.get_connection(db_file)
    row = conn.execute("SELECT outcome, quote FROM trial_readouts WHERE accession = 'news:1'").fetchone()
    assert row["outcome"] == "duplicate" and row["quote"].startswith("duplicate of 0001-26-9")
    assert conn.execute("SELECT COUNT(*) FROM trial_readouts WHERE outcome = 'positive'").fetchone()[0] == 1
    conn.close()
